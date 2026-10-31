"""Consistent setup snapshots and cancellable publication to an external folder."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager, closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

from .ad_catalog import AdCatalogStore
from .broadcaster import channel_to_mapping
from .library import MediaLibrary, SCHEMA_VERSION
from .loader import load_channel
from .portable import (APP_FOLDER, DATA_FOLDER, FORMAT_VERSION, MANIFEST_NAME,
                       PortablePaths, PortableSetupError, load_setup, path_tree)
from .portable import SetupLock
from .resolve import resolve_channel
from .runtime import RUNTIME_SCHEMA_VERSION, advertising_signature
from .storage import inspect_database_version


class CopyCancelled(PortableSetupError):
    pass


PENDING_COPY = '.channelos-copy.pending.json'
COPY_OWNER = '.channelos-copy-owner'


def _atomic_json(path: Path, value: Any):
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as handle:
        json.dump(value, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    if os.name != 'nt':
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _owned(path: Path, identity: str) -> bool:
    try:
        return not path.is_symlink() and (path / COPY_OWNER).read_text(encoding='utf-8') == identity
    except OSError:
        return False


def recover_incomplete_copy(root: str | Path) -> bool:
    """Recover only directories bearing the interrupted transaction's nonce."""
    root = Path(root).resolve(strict=False)
    journal_path = root / PENDING_COPY
    if not journal_path.is_file():
        return False
    try:
        journal = json.loads(journal_path.read_text(encoding='utf-8'))
        identity = str(uuid.UUID(journal['setup_id']))
        if journal.get('format') != 'channelos-copy-journal':
            raise ValueError()
        allowed = {DATA_FOLDER, APP_FOLDER, f'Media/ChannelOS-{identity[:8]}'}
        folders = journal['folders']
        if not isinstance(folders, list) or not folders or set(folders) - allowed:
            raise ValueError()
        manifest = journal['manifest']
        if manifest['setup_id'] != identity or manifest['version'] != FORMAT_VERSION:
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise PortableSetupError('This interrupted copy needs manual recovery; no existing files were changed') from exc
    paths = PortablePaths(root, identity, require_marker=False)
    with SetupLock(paths):
        marker = root / MANIFEST_NAME
        if marker.is_file():
            if load_setup(root).setup_id != identity:
                raise PortableSetupError('The destination contains a different setup; interrupted files were kept for review')
        elif journal.get('ready') and all(_owned(root / folder, identity) for folder in folders):
            _atomic_json(marker, manifest)
        else:
            for folder in reversed(folders):
                target = root / folder
                if _owned(target, identity):
                    shutil.rmtree(target)
        staging = root / ('.channelos-copy-' + identity)
        if _owned(staging, identity):
            shutil.rmtree(staging)
        journal_path.unlink()
    return marker.is_file()


@dataclass(frozen=True)
class SourceMapping:
    original: Path
    relative: str
    rank: int


@dataclass(frozen=True)
class MediaCopy:
    source: Path
    reference: str
    size: int
    content_sha256: str
    needs_copy: bool
    available: bool
    indexed: bool = True


@dataclass
class CopyPlan:
    destination: Path
    setup_id: str
    case_sensitive: bool
    roots: tuple[SourceMapping, ...]
    files: tuple[MediaCopy, ...]
    channel_paths: tuple[Path, ...]
    application_directory: Path | None = None
    application_files: tuple[Path, ...] = ()
    include_artwork: bool = True
    source_portable: PortablePaths | None = None

    @property
    def copy_application(self) -> bool:
        return self.application_directory is not None and self.application_directory != self.destination / APP_FOLDER

    @property
    def paths(self) -> PortablePaths:
        return PortablePaths(self.destination, self.setup_id, self.case_sensitive,
            tuple({'source_id': f'source-{root.rank}', 'relative_path': root.relative,
                   'sort_rank': root.rank} for root in self.roots), require_marker=False)

    def encode(self, path: str) -> str:
        if str(path).startswith('portable://'):
            if not self.source_portable:
                raise PortableSetupError('A portable source reference needs its original setup')
            path = str(self.source_portable.decode(path))
        physical = Path(path).expanduser().resolve(strict=False)
        for source in sorted(self.roots, key=lambda item: len(item.original.parts), reverse=True):
            if physical.is_relative_to(source.original):
                relative = Path(source.relative) / physical.relative_to(source.original)
                return 'portable://' + relative.as_posix().removeprefix('./')
        if physical.is_relative_to(self.destination):
            return self.paths.encode(physical)
        raise PortableSetupError(f'A source is outside this copy plan: {physical}. Review the destination again.')

    def summary(self) -> dict[str, Any]:
        copied = [item for item in self.files if item.needs_copy and item.available]
        return {'destination': str(self.destination), 'setupId': self.setup_id,
                'channelCount': len(self.channel_paths), 'indexedFiles': sum(item.indexed for item in self.files),
                'mediaFilesToCopy': len(copied), 'mediaBytesToCopy': sum(item.size for item in copied),
                'offlineFiles': sum(not item.available for item in self.files),
                'applicationIncluded': self.application_directory is not None,
                'applicationBytes': sum(path.stat().st_size for path in self.application_files if path.is_file()) if self.copy_application else 0,
                'sources': [{'name': source.original.name or str(source.original),
                             'relativePath': source.relative} for source in self.roots]}


def _target_available(destination: Path) -> None:
    if (destination / PENDING_COPY).exists():
        raise PortableSetupError('An interrupted copy is here. Use Open Existing Setup to recover it before copying again.')
    if (destination / MANIFEST_NAME).exists() or (destination / DATA_FOLDER).exists():
        raise PortableSetupError('This folder already contains a setup. Open it, or choose a different destination for the new copy.')
    if destination.exists() and (not destination.is_dir() or destination.is_symlink()):
        raise PortableSetupError('Choose an ordinary writable drive or folder')


def plan_copy(library: MediaLibrary, channel_paths: Iterable[Path], destination: str | Path, *,
              copy_media: bool = False, application_directory: Path | None = None,
              include_artwork: bool = True, runtime_database: Path | None = None) -> CopyPlan:
    destination = Path(destination).expanduser().resolve(strict=False)
    _target_available(destination)
    paths = tuple(Path(path) for path in channel_paths)
    if not paths:
        raise PortableSetupError('Create at least one channel before copying a setup.')
    sources = {source.source_root.resolve(strict=False) for source in library.list_sources()}

    def collect(text):
        sources.add(Path(text).expanduser().resolve(strict=False))
        return text

    for path in paths:
        path_tree(channel_to_mapping(load_channel(path)), collect)
    catalog_path = library.database_path.with_name('ad_catalog.sqlite')
    if catalog_path.is_file():
        catalog = AdCatalogStore(catalog_path)
        for collection in catalog.list_collections():
            sources.update(Path(path).resolve(strict=False) for path in collection.source_paths)
        for profile in catalog.list_profiles():
            path_tree(dict(profile.defaults), collect)
        for assignment in catalog.list_assignments():
            path_tree(dict(assignment.overrides), collect)
            for placement in assignment.placements:
                path_tree(dict(placement.overrides), collect)
    # Retired break plans remain meaningful after a source is removed from the
    # active index. Keep their path snapshots and optional original clips too.
    historical_files = {}
    runtime_path = runtime_database or library.database_path.with_name('runtime.db')
    if runtime_path.is_file():
        with closing(sqlite3.connect(f'{runtime_path.resolve().as_uri()}?mode=ro', uri=True)) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'ad_break_plans' in tables:
                for row in db.execute('SELECT payload FROM ad_break_plans'):
                    for segment in json.loads(row[0]):
                        if segment.get('media_path'):
                            path = library.physical_path(segment['media_path']).resolve(strict=False)
                            sources.add(path.parent)
                            historical_files[path] = str(segment.get('asset_id', '')).removeprefix('sha256:')
    # Parent sources must keep their entire indexed subtree together.
    ordered_sources = sorted(sources, key=library.order_key)
    bases = [path for path in ordered_sources if not any(path != other and path.is_relative_to(other) for other in sources)]
    setup_id = str(uuid.uuid4())
    roots = []
    for rank, source in enumerate(bases):
        if source.is_relative_to(destination):
            relative = source.relative_to(destination).as_posix()
            relative = '' if relative == '.' else relative
        else:
            name = re.sub(r'[^\w .-]+', '-', source.name).strip(' .-')[:60] or 'media'
            relative = f'Media/ChannelOS-{setup_id[:8]}/{rank:02d}-{name}'
        roots.append(SourceMapping(source, relative, rank))
    case_sensitive = library.portable.case_sensitive if library.portable else os.path.normcase('A') != 'a'
    plan = CopyPlan(destination, setup_id, case_sensitive, tuple(roots), (), paths,
                    application_directory, (), include_artwork, library.portable)
    items = []
    with library.connect() as db:
        rows = db.execute('SELECT l.path, l.size_bytes, a.content_sha256 FROM media_locations l '
                          'JOIN media_assets a ON a.asset_id=l.asset_id ORDER BY l.path_key').fetchall()
    targets = {}
    indexed_paths = set()
    for row in rows:
        source = library.physical_path(row['path'])
        indexed_paths.add(source)
        reference = plan.encode(str(source))
        target_key = reference.casefold() if os.name == 'nt' else reference
        if target_key in targets and targets[target_key] != source:
            raise PortableSetupError('Two indexed files collide at the destination; their names need to be distinguishable on this filesystem')
        targets[target_key] = source
        available = source.is_file()
        target = plan.paths.decode(reference)
        needs_copy = target != source
        if available and needs_copy and not copy_media:
            raise PortableSetupError('Some indexed media is outside the destination. Select its containing drive/folder, or enable "Copy media outside destination".')
        items.append(MediaCopy(source, reference, int(row['size_bytes']), row['content_sha256'], needs_copy, available))
    for source, digest in historical_files.items():
        if source in indexed_paths:
            continue
        reference = plan.encode(str(source))
        available = source.is_file()
        needs_copy = plan.paths.decode(reference) != source
        if available and needs_copy and not copy_media:
            raise PortableSetupError('A saved ad plan references media outside the destination. Enable "Copy media outside destination" to carry its history and clips together.')
        items.append(MediaCopy(source, reference, source.stat().st_size if available else 0,
                               digest if len(digest) == 64 else '', needs_copy, available, indexed=False))
    plan.files = tuple(items)
    if application_directory is not None:
        app = application_directory.resolve(strict=True)
        plan.application_directory = app
        if destination.is_relative_to(app):
            raise PortableSetupError('The copy destination cannot be inside the running application folder')
        if app != destination / APP_FOLDER and (destination / APP_FOLDER).exists():
            raise PortableSetupError('The destination already has an application folder; choose another destination or exclude the app')
        app_files = []
        for directory, directories, files in os.walk(app, followlinks=False):
            for name in [*directories, *files]:
                path = Path(directory) / name
                if path.is_symlink() and not path.resolve(strict=False).is_relative_to(app):
                    raise PortableSetupError('The application contains a link outside its folder and cannot be copied as a standalone app')
                if path.is_file() or path.is_symlink():
                    app_files.append(path)
        plan.application_files = tuple(app_files)
    return plan


def _backup_database(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(f'{source.resolve().as_uri()}?mode=ro', uri=True)) as original:
        copied = sqlite3.connect(destination)
        try:
            original.backup(copied)
        finally:
            copied.close()


@contextmanager
def _database(path):
    connection = sqlite3.connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


@dataclass
class SetupSnapshot:
    plan: CopyPlan
    temporary: tempfile.TemporaryDirectory
    root: Path
    artifact_source: Path | None

    def close(self):
        self.temporary.cleanup()


def snapshot_setup(plan: CopyPlan, library: MediaLibrary, runtime_database: Path,
                   channels_directory: Path) -> SetupSnapshot:
    """Call on the application's writer thread after active scans have finished.

    One GUI turn takes SQLite backup snapshots and captures channel intent;
    expensive media/application copying happens later in a worker.
    """
    if library.portable:
        library.portable.check_available()
    temporary = tempfile.TemporaryDirectory(prefix='channelos-portable-snapshot-')
    root = Path(temporary.name)
    data = root / DATA_FOLDER
    data.mkdir()
    snapshot = SetupSnapshot(plan, temporary, root,
        library.database_path.parent / 'artwork' if plan.include_artwork else None)
    try:
        _backup_database(library.database_path, data / 'library.db')
        for name, source in [('runtime.db', runtime_database),
                             ('ad_catalog.sqlite', library.database_path.with_name('ad_catalog.sqlite'))]:
            if source.is_file():
                _backup_database(source, data / name)
        channel_dir = data / 'channels'
        channel_dir.mkdir()
        revisions = {}
        for path in plan.channel_paths:
            definition = load_channel(path)
            resolved = resolve_channel(definition, library, allow_offline_ads=True)
            revisions[definition.channel] = advertising_signature(resolved, path_encoder=plan.encode)
            encoded = path_tree(channel_to_mapping(definition), plan.encode)
            (channel_dir / f'channel-{definition.channel:04d}.yaml').write_text(
                yaml.safe_dump(encoded, sort_keys=False, allow_unicode=True), encoding='utf-8')
        studio = channels_directory / 'studio'
        if studio.is_dir():
            shutil.copytree(studio, channel_dir / 'studio')
        settings = library.database_path.parent / 'settings.json'
        if settings.is_file():
            raw = json.loads(settings.read_text(encoding='utf-8'))
            if not isinstance(raw, dict):
                raise PortableSetupError('The saved settings are invalid. Save your preferences in Settings, then retry the copy.')
            raw.pop('audio_output_device_id', None)
            (data / 'settings.json').write_text(json.dumps(raw, indent=2), encoding='utf-8')
        _convert_library(data / 'library.db', plan, library)
        _convert_catalog(data / 'ad_catalog.sqlite', plan)
        _convert_runtime(data / 'runtime.db', plan, revisions)
        manifest = {'format': 'channelos-portable', 'version': FORMAT_VERSION,
                    'setup_id': plan.setup_id, 'case_sensitive': plan.case_sensitive,
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'name': plan.destination.name or 'My ChannelOS',
                    'roots': list(plan.paths.roots), 'index_schema': SCHEMA_VERSION}
        (root / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        return snapshot
    except BaseException:
        snapshot.close()
        raise


def _convert_library(database: Path, plan: CopyPlan, library: MediaLibrary):
    with _database(database) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute('SELECT * FROM media_locations').fetchall()
        # Reinsert keys together; changing one at a time can collide with an old key.
        db.execute('DELETE FROM media_locations')
        for row in rows:
            values = dict(row)
            reference = plan.encode(str(library.physical_path(row['path'])))
            source = plan.encode(str(library.physical_path(row['source_root'])))
            values.update(path=reference, path_key=plan.paths.storage_path(reference)[1],
                          source_root=source, source_root_key=plan.paths.storage_path(source)[1])
            db.execute('INSERT INTO media_locations (' + ','.join(values) + ') VALUES (' + ','.join('?' for _ in values) + ')', tuple(values.values()))
        rows = db.execute('SELECT * FROM media_sources').fetchall()
        db.execute('DELETE FROM media_sources')
        for row in rows:
            values = dict(row)
            source = plan.encode(str(library.physical_path(row['source_root'])))
            values.update(source_root=source, source_root_key=plan.paths.storage_path(source)[1])
            db.execute('INSERT INTO media_sources (' + ','.join(values) + ') VALUES (' + ','.join('?' for _ in values) + ')', tuple(values.values()))
        db.execute("UPDATE library_meta SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))


def _convert_catalog(database: Path, plan: CopyPlan):
    if not database.is_file():
        return
    with _database(database) as db:
        for table, key, fields in [('ad_collections', 'collection_id', ['asset_ids_json']),
                                    ('ad_break_profiles', 'profile_id', ['defaults_json']),
                                    ('channel_ad_assignments', 'channel_number', ['overrides_json', 'placements_json'])]:
            columns = {row[1] for row in db.execute('PRAGMA table_info(' + table + ')')}
            for field in fields:
                if field not in columns:
                    continue
                for identity, payload in db.execute(f'SELECT {key},{field} FROM {table}').fetchall():
                    # Decode a source portable copy before encoding its new destination.
                    value = path_tree(json.loads(payload), plan.encode)
                    db.execute(f'UPDATE {table} SET {field}=? WHERE {key}=?', (json.dumps(value), identity))


def _convert_runtime(database: Path, plan: CopyPlan, revisions: dict[int, str]):
    if not database.is_file():
        return
    with _database(database) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'ad_break_plans' in tables:
            for identity, payload in db.execute('SELECT plan_id,payload FROM ad_break_plans').fetchall():
                value = path_tree(json.loads(payload), plan.encode)
                db.execute('UPDATE ad_break_plans SET payload=? WHERE plan_id=?', (json.dumps(value), identity))
        for number, revision in revisions.items():
            for table in ['ad_break_policy_state', 'ad_break_catchup_state']:
                if table in tables:
                    db.execute(f'UPDATE {table} SET policy_revision=? WHERE channel_number=?', (revision, number))
            if 'ad_plan_metadata' in tables:
                rows = db.execute('SELECT m.plan_id,m.payload FROM ad_plan_metadata m JOIN ad_break_plans p ON m.plan_id=p.plan_id WHERE p.channel_number=?', (number,)).fetchall()
                for identity, payload in rows:
                    value = json.loads(payload)
                    value['policy_revision'] = revision
                    db.execute('UPDATE ad_plan_metadata SET payload=? WHERE plan_id=?', (json.dumps(value), identity))


def publish_snapshot(snapshot: SetupSnapshot, *, on_progress: Callable | None = None,
                     should_cancel: Callable[[], bool] | None = None) -> dict[str, Any]:
    root = snapshot.plan.destination
    try:
        _target_available(root)
        root.mkdir(parents=True, exist_ok=True)
        with SetupLock(snapshot.plan.paths):
            return _publish_locked(snapshot, on_progress=on_progress, should_cancel=should_cancel)
    finally:
        staging = root / ('.channelos-copy-' + snapshot.plan.setup_id)
        if _owned(staging, snapshot.plan.setup_id):
            shutil.rmtree(staging, ignore_errors=True)
        snapshot.close()


def _publish_locked(snapshot: SetupSnapshot, *, on_progress=None, should_cancel=None):
    plan = snapshot.plan
    root = plan.destination
    _target_available(root)
    staging = root / ('.channelos-copy-' + plan.setup_id)
    staging.mkdir()
    (staging / COPY_OWNER).write_text(plan.setup_id, encoding='utf-8')
    published = []
    committed = False
    metadata_bytes = sum(path.stat().st_size for path in (snapshot.root / DATA_FOLDER).rglob('*') if path.is_file())
    total = max(1, metadata_bytes + sum(item.size for item in plan.files if item.needs_copy and item.available)
                + (sum(path.stat().st_size for path in plan.application_files if path.is_file()) if plan.copy_application else 0))
    if shutil.disk_usage(root).free < total:
        raise PortableSetupError('There is not enough free space on the destination for this copy.')
    completed = 0
    folders = [DATA_FOLDER]
    if any(item.needs_copy and item.available for item in plan.files):
        folders.append('Media/ChannelOS-' + plan.setup_id[:8])
    if plan.copy_application:
        folders.append(APP_FOLDER)
    manifest = json.loads((snapshot.root / MANIFEST_NAME).read_text(encoding='utf-8'))
    journal = {'format': 'channelos-copy-journal', 'setup_id': plan.setup_id,
               'folders': folders, 'manifest': manifest, 'ready': False}
    _atomic_json(root / PENDING_COPY, journal)

    def check():
        if not _owned(staging, plan.setup_id):
            raise PortableSetupError('The copy drive was disconnected or replaced. Reconnect it to recover the interrupted copy.')
        if should_cancel and should_cancel():
            raise CopyCancelled('Copy cancelled. The existing setup and media were kept.')

    def copy_file(source, target, expected_hash=None):
        nonlocal completed
        check()
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256() if expected_hash else None
        with source.open('rb') as src, target.open('xb') as dst:
            while chunk := src.read(4 * 1024 * 1024):
                check()
                dst.write(chunk)
                if digest:
                    digest.update(chunk)
                completed += len(chunk)
                if on_progress:
                    on_progress(completed, total, 'Copying ' + source.name)
            dst.flush()
            os.fsync(dst.fileno())
        if digest and digest.hexdigest() != expected_hash:
            raise PortableSetupError('An indexed media file changed since its last scan: ' + str(source) + '. Rescan that source before copying.')
        shutil.copystat(source, target)

    try:
        shutil.copytree(snapshot.root / DATA_FOLDER, staging / DATA_FOLDER,
                        copy_function=lambda source, target: copy_file(Path(source), Path(target)))
        for item in plan.files:
            check()
            if item.available and item.needs_copy:
                copy_file(item.source, staging / item.reference[len('portable://'):], item.content_sha256)
                for image in [*(item.source.with_suffix(suffix) for suffix in ('.jpg', '.png', '.webp')),
                              *(item.source.parent / name for name in ('poster.jpg', 'folder.jpg', 'cover.jpg'))]:
                    if image.is_file() and not image.is_symlink():
                        target = staging / plan.encode(str(image))[len('portable://'):]
                        if not target.exists():
                            copy_file(image, target)
        # Preserve known-good cache entries without requiring them for playback.
        if snapshot.artifact_source and snapshot.artifact_source.is_dir():
            for source in snapshot.artifact_source.glob('*.jpg'):
                if source.is_file() and not source.is_symlink():
                    copy_file(source, staging / DATA_FOLDER / 'artwork' / source.name)
        if plan.copy_application:
            for source in plan.application_files:
                target = staging / APP_FOLDER / source.relative_to(plan.application_directory)
                if source.is_symlink():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.symlink_to(os.path.relpath(source.resolve(), source.parent), target_is_directory=source.is_dir())
                else:
                    copy_file(source, target)
        # Reuse the index; refresh only location stats, never hash/probe every file.
        with _database(staging / DATA_FOLDER / 'library.db') as db:
            for item in plan.files:
                target = staging / item.reference[len('portable://'):] if item.needs_copy else item.source
                if target.is_file() and item.needs_copy:
                    stat = target.stat()
                    db.execute('UPDATE media_locations SET size_bytes=?,mtime_ns=?,online=1 WHERE path_key=?',
                               (stat.st_size, stat.st_mtime_ns, plan.paths.storage_path(item.reference)[1]))
                else:
                    # Reused files have not been hashed here. Retain their saved
                    # stat fingerprint so a later scan detects changed content.
                    db.execute('UPDATE media_locations SET online=? WHERE path_key=?',
                               (int(target.is_file()), plan.paths.storage_path(item.reference)[1]))
        check()
        for folder in folders:
            owned = staging / folder
            owned.mkdir(parents=True, exist_ok=True)
            (owned / COPY_OWNER).write_text(plan.setup_id, encoding='utf-8')
        journal['ready'] = True
        _atomic_json(root / PENDING_COPY, journal)
        # The manifest is the commit marker. A partial copy is never discoverable.
        for item in staging.iterdir():
            if item.name == COPY_OWNER:
                continue
            if item.name == 'Media':
                media_parent = root / 'Media'
                media_parent.mkdir(exist_ok=True)
                for child in item.iterdir():
                    target = media_parent / child.name
                    if target.exists():
                        raise PortableSetupError('A destination media folder appeared during copying; choose a fresh destination')
                    child.rename(target)
                    published.append(target)
            else:
                target = root / item.name
                if target.exists():
                    raise PortableSetupError('The destination changed while copying; no existing files were overwritten')
                item.rename(target)
                published.append(target)
        _atomic_json(root / MANIFEST_NAME, manifest)
        committed = True
        try:
            (root / PENDING_COPY).unlink()
        except OSError:
            pass  # A completed commit can clean up its journal next time it opens.
        if on_progress:
            on_progress(total, total, 'Portable setup is ready')
        return {'ok': True, 'message': 'Portable setup copied. Open it to save changes on this drive.', **plan.summary()}
    except BaseException:
        for path in reversed(published):
            if not committed and _owned(path, plan.setup_id):
                shutil.rmtree(path, ignore_errors=True)
        try:
            if _owned(staging, plan.setup_id):
                (root / PENDING_COPY).unlink(missing_ok=True)
        except OSError:
            pass
        raise
    finally:
        if _owned(staging, plan.setup_id):
            shutil.rmtree(staging, ignore_errors=True)


def inspect_setup(path: str | Path) -> dict[str, Any]:
    """Recover owned interrupted copies, then validate existing metadata read-only."""
    supplied = Path(path).resolve(strict=False)
    root = supplied.parent if supplied.name == MANIFEST_NAME else supplied
    recover_incomplete_copy(root)
    setup = load_setup(root)
    setup.check_available()
    for name in ('library.db', 'runtime.db', 'ad_catalog.sqlite', 'settings.json', 'channels'):
        managed = setup.data_directory / name
        if not managed.resolve(strict=False).is_relative_to(setup.data_directory):
            raise PortableSetupError('Portable data points outside its setup folder. Keep the setup together before opening it.')
    library_db = setup.data_directory / 'library.db'
    if inspect_database_version(library_db, meta_table='library_meta') != SCHEMA_VERSION:
        raise PortableSetupError('This setup index needs a compatible ChannelOS build; its data was not changed')
    if inspect_database_version(setup.data_directory / 'runtime.db', meta_table='runtime_meta') not in (None, *range(RUNTIME_SCHEMA_VERSION + 1)):
        raise PortableSetupError('This setup history needs a compatible ChannelOS build; its data was not changed')
    with closing(sqlite3.connect(f'{library_db.resolve().as_uri()}?mode=ro', uri=True)) as db:
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise PortableSetupError('The portable index needs recovery; keep this copy and open a prior setup copy')
        count = db.execute('SELECT COUNT(*) FROM media_assets').fetchone()[0]
        for row in db.execute('SELECT path,source_root FROM media_locations'):
            setup.decode(row[0])
            setup.decode(row[1])
        for row in db.execute('SELECT source_root FROM media_sources'):
            setup.decode(row[0])
    for name in ('runtime.db', 'ad_catalog.sqlite'):
        path = setup.data_directory / name
        if path.is_file():
            with closing(sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro', uri=True)) as db:
                if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise PortableSetupError(f'The portable {name} needs recovery. Keep this copy and open a prior setup copy.')
    channels = list((setup.data_directory / 'channels').glob('*.yaml')) + list((setup.data_directory / 'channels').glob('*.yml'))
    for channel in channels:
        definition = load_channel(channel)
        path_tree(channel_to_mapping(definition), lambda value: str(setup.decode(value)))
    if not channels:
        raise PortableSetupError('This setup has no channel definitions. Open a prior complete setup copy.')
    return {'ok': True, 'name': setup.root.name, 'root': str(setup.root),
            'setupId': setup.setup_id, 'channelCount': len(channels), 'assetCount': count,
            'message': 'Setup ready. Channels, index and history will be saved on this drive.'}
