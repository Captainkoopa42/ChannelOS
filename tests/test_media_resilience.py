from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from channelos.library import IndexedMedia, MediaAsset, MediaLocation, normalize_path
from channelos.media_resilience import (
    _degrade_calendar_for_available_media,
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
from channelos.resolve import ResolvedChannel


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
        start_utc=pytest.importorskip("datetime").datetime.now(
            pytest.importorskip("datetime").timezone.utc
        ),
        asset_id="sha256:available",
        filler=CalendarFillerDefinition(
            mode="sequential",
            asset_ids=("sha256:available", "sha256:missing"),
        ),
    )
    second = CalendarBlockDefinition(
        start_utc=first.start_utc.replace(year=first.start_utc.year + 1),
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
