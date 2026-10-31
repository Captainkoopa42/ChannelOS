"""Versioned, drive-relative ChannelOS setups. No global active-profile state."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable

MANIFEST_NAME = "ChannelOS.portable.json"
DATA_FOLDER = "ChannelOS-Data"
APP_FOLDER = "ChannelOS-App"
FORMAT_VERSION = 1
REFERENCE_PREFIX = "portable://"


class PortableSetupError(ValueError):
    pass


class PortableUnavailableError(OSError):
    pass


def relative_parts(value: str) -> tuple[str, ...]:
    if not isinstance(value, str) or "\\" in value or "\x00" in value:
        raise PortableSetupError("Portable paths must use relative forward-slash paths")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"..", ":"} or ":" in part for part in path.parts):
        raise PortableSetupError("Portable path cannot escape its setup folder")
    return path.parts


@dataclass(frozen=True)
class PortablePaths:
    root: Path
    setup_id: str
    case_sensitive: bool = True
    roots: tuple[dict[str, Any], ...] = ()
    require_marker: bool = field(default=True, repr=False, compare=False)
    _marker_stamp: tuple | None = field(default=None, init=False, repr=False, compare=False)

    @property
    def data_directory(self) -> Path:
        return self.root / DATA_FOLDER

    def check_available(self) -> None:
        if not self.require_marker:
            return
        try:
            marker = self.root / MANIFEST_NAME
            stat = marker.stat()
            stamp = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
            if stamp != self._marker_stamp:
                raw = json.loads(marker.read_text(encoding="utf-8"))
                if (not isinstance(raw, dict) or raw.get("setup_id") != self.setup_id
                        or raw.get("format") != "channelos-portable"
                        or type(raw.get("version")) is not int
                        or raw["version"] != FORMAT_VERSION):
                    raise ValueError("different setup")
                object.__setattr__(self, "_marker_stamp", stamp)
            valid = self.data_directory.is_dir() and not self.data_directory.is_symlink()
        except (OSError, ValueError, AttributeError):
            valid = False
        if not valid:
            raise PortableUnavailableError("The portable drive is unavailable. Reconnect the same drive or open another setup.")

    def encode(self, path: str | Path) -> str:
        text = str(path)
        if text.startswith(REFERENCE_PREFIX):
            relative_parts(text[len(REFERENCE_PREFIX):])
            return text
        resolved = Path(path).expanduser().resolve(strict=False)
        try:
            relative = resolved.relative_to(self.root.resolve(strict=False)).as_posix()
        except ValueError as exc:
            raise PortableSetupError("This portable setup keeps media on its own drive/folder. Copy this source into the setup first.") from exc
        relative_parts(relative)
        return REFERENCE_PREFIX + ("" if relative == "." else relative)

    def decode(self, reference: str | Path) -> Path:
        text = str(reference)
        if not text.startswith(REFERENCE_PREFIX):
            # Physical paths are accepted only when they are still in this setup.
            text = self.encode(text)
        result = self.root.joinpath(*relative_parts(text[len(REFERENCE_PREFIX):]))
        if not result.resolve(strict=False).is_relative_to(self.root.resolve(strict=False)):
            raise PortableSetupError("A portable path points outside the setup through a symbolic link")
        return result

    def storage_path(self, path: str | Path) -> tuple[str, str]:
        reference = self.encode(path)
        key = reference.rstrip("/") if reference == REFERENCE_PREFIX else reference
        return reference, key if self.case_sensitive else key.casefold()

    def order_key(self, path: str | Path) -> str:
        relative = self.encode(path)[len(REFERENCE_PREFIX):]
        compare = relative if self.case_sensitive else relative.casefold()
        matches = []
        for source in self.roots:
            prefix = source["relative_path"].rstrip("/")
            prefix_key = prefix if self.case_sensitive else prefix.casefold()
            if compare == prefix_key or compare.startswith(prefix_key + "/") or not prefix_key:
                suffix = compare[len(prefix_key):].lstrip("/")
                matches.append((len(prefix_key), f"{int(source['sort_rank']):08d}/{suffix}"))
        return max(matches)[1] if matches else "new/" + compare


def load_setup(path: str | Path) -> PortablePaths:
    supplied = Path(path).expanduser().resolve(strict=False)
    root = supplied.parent if supplied.name == MANIFEST_NAME else supplied
    try:
        raw = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PortableSetupError("Choose a folder containing " + MANIFEST_NAME) from exc
    if not isinstance(raw, dict) or raw.get("format") != "channelos-portable":
        raise PortableSetupError("This is not a ChannelOS portable setup")
    if type(raw.get("version")) is not int or raw["version"] != FORMAT_VERSION:
        raise PortableSetupError("This setup format needs a compatible ChannelOS build; no files were changed")
    try:
        uuid.UUID(raw["setup_id"])
        if type(raw["case_sensitive"]) is not bool or not isinstance(raw["roots"], list):
            raise ValueError()
        for source in raw["roots"]:
            relative_parts(source["relative_path"])
            if type(source["sort_rank"]) is not int or source["sort_rank"] < 0:
                raise ValueError()
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise PortableSetupError("Portable setup metadata is invalid") from exc
    paths = PortablePaths(root, raw["setup_id"], raw["case_sensitive"], tuple(raw["roots"]))
    if paths.data_directory.is_symlink() or not paths.data_directory.resolve(strict=False).is_relative_to(root):
        raise PortableSetupError("Portable data must stay inside its setup folder")
    return paths


def find_setup(location: str | Path) -> PortablePaths | None:
    path = Path(location).expanduser().resolve(strict=False)
    for ancestor in (path, *list(path.parents)[:6]):
        if (ancestor / MANIFEST_NAME).is_file():
            setup = load_setup(ancestor)
            if path == ancestor or path.is_relative_to(setup.data_directory) or path.is_relative_to(ancestor / APP_FOLDER):
                return setup
    return None


def path_tree(value: Any, transform: Callable[[str], str], *, key: str = "") -> Any:
    """Transform documented path fields, leaving titles and other strings alone."""
    if isinstance(value, dict):
        return {name: path_tree(item, transform, key=name) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [transform(str(item)) if key == "source_paths" else path_tree(item, transform) for item in value]
    if isinstance(value, str) and key in {"path", "media_path", "source_root"} and value:
        return transform(value)
    return value


def decode_tree(value: Any, paths: PortablePaths | None) -> Any:
    def decode(text: str) -> str:
        if text.startswith(REFERENCE_PREFIX):
            if paths is None:
                raise PortableSetupError("Portable references need their ChannelOS setup folder")
            return str(paths.decode(text))
        return text
    return path_tree(value, decode)


def host_data_directory() -> Path:
    if os.environ.get('LOCALAPPDATA'):
        return Path(os.environ['LOCALAPPDATA']) / 'ChannelOS'
    return Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local' / 'state'))) / 'ChannelOS'


def recent_setups() -> list[dict[str, Any]]:
    try:
        records = json.loads((host_data_directory() / 'portable-recents.json').read_text(encoding='utf-8'))
        if not isinstance(records, list):
            return []
        result = []
        for record in records[:10]:
            if not isinstance(record, dict) or not isinstance(record.get('root'), str) or not isinstance(record.get('setupId'), str):
                continue
            try:
                paths = load_setup(record['root'])
                paths.check_available()
                available = paths.setup_id == record['setupId']
            except (OSError, ValueError):
                available = False
            result.append({**record, 'available': available})
        return result
    except (OSError, ValueError):
        return []


def remember_setup(paths: PortablePaths) -> None:
    records = [{'setupId': paths.setup_id, 'root': str(paths.root), 'name': paths.root.name}]
    records.extend({key: value for key, value in record.items() if key != 'available'}
                   for record in recent_setups() if record['setupId'] != paths.setup_id)
    path = host_data_directory() / 'portable-recents.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(records[:10], indent=2), encoding='utf-8')
    temporary.replace(path)


class SetupLock:
    """OS-owned exclusive lease, released automatically after process death."""
    def __init__(self, paths: PortablePaths) -> None:
        self.paths = paths
        self.handle = None

    def __enter__(self):
        self.paths.check_available()
        self.handle = (self.paths.root / ".channelos.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.handle.seek(0)
                self.handle.write(b"\0")
                self.handle.flush()
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            self.handle = None
            raise PortableSetupError("This portable setup is already open in another ChannelOS process") from exc
        return self

    def __exit__(self, *args):
        if self.handle is not None:
            try:
                if os.name == "nt":
                    import msvcrt
                    self.handle.seek(0)
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass  # A removed drive must still release its process handle.
            finally:
                self.handle.close()
                self.handle = None


class PortableConnection(sqlite3.Connection):
    """Check the drive identity before database access, including persistent plans."""
    portable: PortablePaths | None = None

    def _check(self):
        if self.portable:
            self.portable.check_available()

    def execute(self, *args, **kwargs):
        self._check()
        return super().execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        self._check()
        return super().executemany(*args, **kwargs)

    def executescript(self, *args, **kwargs):
        self._check()
        return super().executescript(*args, **kwargs)

    def cursor(self, *args, **kwargs):
        kwargs.setdefault("factory", PortableCursor)
        return super().cursor(*args, **kwargs)

    def commit(self):
        self._check()
        return super().commit()

    def __enter__(self):
        self._check()
        return super().__enter__()

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            self._check()
        return super().__exit__(exc_type, exc_value, traceback)


class PortableCursor(sqlite3.Cursor):
    def execute(self, *args, **kwargs):
        self.connection._check()
        return super().execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        self.connection._check()
        return super().executemany(*args, **kwargs)
