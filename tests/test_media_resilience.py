from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from channelos.library import (
    IndexedMedia,
    MediaAsset,
    MediaLibrary,
    MediaLocation,
    normalize_path,
)
from channelos.media_resilience import (
    _degrade_calendar_for_available_media,
    _resolved_runtime,
    _transient_available_media,
    install_media_resilience_support,
)
from channelos.models import (
    CalendarBlockDefinition,
    CalendarFillerDefinition,
    ChannelDefinition,
    ProgrammingDefinition,
    SourceDefinition,
)
from channelos.probe import MediaProbeResult
from channelos.resolve import ResolvedChannel, resolve_channel
from channelos.runtime import ChannelRuntime, RuntimeStore, TelevisionRuntime
from channelos.scanner import MediaScanner


class FixedProbe:
    def probe(self, path: Path) -> MediaProbeResult:
        return MediaProbeResult(
            duration_seconds=30.0,
            container_format=path.suffix.lstrip(".") or "mp4",
        )


def _media(root: Path, name: str, asset_id: str) -> IndexedMedia:
    path = root / name
    _, path_key = normalize_path(path)
    return IndexedMedia(
        asset=MediaAsset(
            asset_id=asset_id,
            content_sha256=asset_id.removeprefix("sha256:"),
            size_bytes=100,
            duration_seconds=60.0,
            container_format="mp4",
        ),
        location=MediaLocation(
            path=path,
            path_key=path_key,
            asset_id=asset_id,
            source_root=root,
            online=True,
        ),
    )


def test_transient_source_filter_does_not_require_files_to_exist(tmp_path: Path) -> None:
    connected = tmp_path / "connected"
    connected.mkdir()
    disconnected = tmp_path / "missing-drive"

    available = _media(connected, "present.mp4", "sha256:available")
    unavailable = _media(disconnected, "gone.mp4", "sha256:missing")
    definition = ChannelDefinition(
        schema_version="0.1",
        channel=1,
        name="Test",
        sources=(SourceDefinition(path=connected), SourceDefinition(path=disconnected)),
        programming=ProgrammingDefinition(mode="sequential"),
    )
    resolved = ResolvedChannel(
        definition=definition,
        media=(available, unavailable),
    )

    filtered = _transient_available_media(resolved)

    assert filtered == (available,)


def test_calendar_degrades_missing_fixed_blocks_and_filler(tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    available = _media(root, "available.mp4", "sha256:available")

    first = CalendarBlockDefinition(
        start_utc=datetime.now(timezone.utc),
        asset_id="sha256:available",
        filler=CalendarFillerDefinition(
            mode="sequential",
            asset_ids=("sha256:available", "sha256:missing"),
        ),
    )
    second = CalendarBlockDefinition(
        start_utc=first.start_utc + timedelta(days=1),
        asset_id="sha256:missing",
    )
    definition = ChannelDefinition(
        schema_version="0.3",
        channel=7,
        name="Calendar",
        sources=(SourceDefinition(path=root),),
        programming=ProgrammingDefinition(
            mode="calendar",
            filler_mode="sequential",
            calendar=(first, second),
        ),
    )

    degraded = _degrade_calendar_for_available_media(
        ResolvedChannel(definition=definition, media=(available,))
    )

    assert degraded.definition.programming.mode == "calendar"
    assert len(degraded.definition.programming.calendar) == 1
    block = degraded.definition.programming.calendar[0]
    assert block.asset_id == "sha256:available"
    assert block.filler is not None
    assert block.filler.asset_ids == ("sha256:available",)


def test_calendar_falls_back_to_normal_filler_when_all_blocks_are_missing(
    tmp_path: Path,
) -> None:
    root = tmp_path / "media"
    root.mkdir()
    definition = ChannelDefinition(
        schema_version="0.3",
        channel=8,
        name="Calendar",
        sources=(SourceDefinition(path=root),),
        programming=ProgrammingDefinition(
            mode="calendar",
            filler_mode="shuffle",
            calendar=(),
        ),
    )

    degraded = _degrade_calendar_for_available_media(
        ResolvedChannel(definition=definition, media=())
    )

    assert degraded.definition.programming.mode == "shuffle"
    assert degraded.definition.programming.calendar == ()


def test_media_resilience_installer_is_idempotent() -> None:
    class FakeController:
        pass

    class FakeModule:
        BroadcasterCouchController = FakeController

    install_media_resilience_support(FakeModule)
    first = FakeModule.BroadcasterCouchController
    install_media_resilience_support(FakeModule)

    assert FakeModule.BroadcasterCouchController is first


@pytest.mark.parametrize("mode", ["sequential", "shuffle"])
def test_transient_runtime_preserves_viewer_clock_and_saved_signature(
    tmp_path: Path,
    mode: str,
) -> None:
    connected = tmp_path / "connected"
    removable = tmp_path / "removable"
    connected.mkdir()
    removable.mkdir()
    (connected / "a.mp4").write_bytes(b"available")
    (removable / "b.mp4").write_bytes(b"temporarily-disconnected")

    library = MediaLibrary(tmp_path / "library.db")
    scanner = MediaScanner(library, FixedProbe())
    scanner.scan(connected)
    scanner.scan(removable)
    definition = ChannelDefinition(
        schema_version="0.1",
        channel=7,
        name="Continuity",
        sources=(SourceDefinition(path=connected), SourceDefinition(path=removable)),
        programming=ProgrammingDefinition(mode=mode),
    )
    store = RuntimeStore(tmp_path / "runtime.db")
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    original = ChannelRuntime.open(
        resolve_channel(definition, library),
        store,
        now=epoch,
    )
    television = TelevisionRuntime((original,), store)
    television.tune(7, now=epoch + timedelta(seconds=5))
    television.pause(now=epoch + timedelta(seconds=10))
    persisted_before = store.load_channel(7)
    assert persisted_before is not None

    parked = tmp_path / "removable-unplugged"
    removable.rename(parked)
    degraded = _resolved_runtime(definition, library, store)

    assert degraded is not None
    assert len(degraded.channel.media) == 1
    assert degraded.channel.media[0].location.source_root == connected
    restored = TelevisionRuntime((degraded,), store)
    decision = restored.status(now=epoch + timedelta(seconds=30))
    assert decision.channel_number == 7
    assert decision.viewer_time_utc == epoch + timedelta(seconds=10)
    resumed = restored.play(now=epoch + timedelta(seconds=31))
    assert resumed.channel_number == 7
    assert resumed.viewer_time_utc == epoch + timedelta(seconds=10)
    assert degraded.epoch_utc == original.epoch_utc
    assert store.load_channel(7) == persisted_before

    parked.rename(removable)
    reconnected = _resolved_runtime(definition, library, store)
    assert reconnected is not None
    assert len(reconnected.channel.media) == 2
    assert store.load_channel(7) == persisted_before


def test_transient_runtime_uses_connected_duplicate_location(tmp_path: Path) -> None:
    preferred = tmp_path / "a-preferred"
    alternate = tmp_path / "b-alternate"
    preferred.mkdir()
    alternate.mkdir()
    payload = b"same-owned-media"
    (preferred / "episode.mp4").write_bytes(payload)
    alternate_path = alternate / "episode-copy.mp4"
    alternate_path.write_bytes(payload)

    library = MediaLibrary(tmp_path / "library.db")
    scanner = MediaScanner(library, FixedProbe())
    scanner.scan(preferred)
    scanner.scan(alternate)
    definition = ChannelDefinition(
        schema_version="0.1",
        channel=8,
        name="Duplicate fallback",
        sources=(SourceDefinition(path=preferred), SourceDefinition(path=alternate)),
        programming=ProgrammingDefinition(mode="sequential"),
    )
    preferred.rename(tmp_path / "a-preferred-unplugged")

    runtime = _resolved_runtime(
        definition,
        library,
        RuntimeStore(tmp_path / "runtime.db"),
    )

    assert runtime is not None
    assert len(runtime.channel.media) == 1
    assert runtime.channel.media[0].location.path == alternate_path


def test_returned_source_stays_pending_when_lineup_restore_fails(
    tmp_path: Path,
) -> None:
    class FakeController:
        def __init__(self) -> None:
            self._playback = {"temporaryUnavailable": True}
            self.base_refresh_called = False

        def refresh(self) -> None:
            self.base_refresh_called = True

    class FakeModule:
        BroadcasterCouchController = FakeController

    install_media_resilience_support(FakeModule)
    controller = FakeModule.BroadcasterCouchController()
    returned = tmp_path / "returned"
    returned.mkdir()
    controller._temporarily_unavailable_roots.add(returned)
    controller._reload_resilient_lineup = lambda **_kwargs: False

    controller.refresh()

    assert controller.base_refresh_called
    assert returned in controller._temporarily_unavailable_roots


def test_returned_source_clears_after_successful_lineup_restore(
    tmp_path: Path,
) -> None:
    class FakeController:
        def __init__(self) -> None:
            self._playback = {"temporaryUnavailable": True}

        def refresh(self) -> None:
            return None

    class FakeModule:
        BroadcasterCouchController = FakeController

    install_media_resilience_support(FakeModule)
    controller = FakeModule.BroadcasterCouchController()
    returned = tmp_path / "returned"
    returned.mkdir()
    controller._temporarily_unavailable_roots.add(returned)
    controller._reload_resilient_lineup = lambda **_kwargs: True

    controller.refresh()

    assert returned not in controller._temporarily_unavailable_roots
