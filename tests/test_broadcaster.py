from __future__ import annotations

from pathlib import Path

import pytest

from channelos.broadcaster import (
    BroadcasterError,
    BroadcasterService,
    ChannelConflictError,
    definition_from_editor,
    serialize_channel,
)
from channelos.library import MediaLibrary
from channelos.loader import load_channel
from channelos.probe import MediaProbeResult
from channelos.scanner import MediaScanner


class FixedProbe:
    def probe(self, path: Path) -> MediaProbeResult:
        return MediaProbeResult(
            duration_seconds=30.0,
            container_format=path.suffix.lstrip(".") or "mp4",
        )


def make_library(tmp_path: Path) -> tuple[MediaLibrary, Path]:
    media_root = tmp_path / "media"
    media_root.mkdir()
    for name in ("01-alpha.mp4", "02-beta.mp4", "03-gamma.mp4"):
        (media_root / name).write_bytes((name + "-owned").encode("utf-8"))

    library = MediaLibrary(tmp_path / "library.db")
    summary = MediaScanner(library, FixedProbe()).scan(media_root)
    assert summary.discovered == 3
    return library, media_root.resolve()


def editor(
    channel: int,
    source: Path,
    *,
    name: str | None = None,
    mode: str = "sequential",
) -> dict[str, object]:
    return {
        "channel": channel,
        "name": name or f"Channel {channel}",
        "description": "Broadcaster test channel",
        "sources": [str(source)],
        "mode": mode,
        "preserveEpisodeOrder": False,
        "avoidRepeatDays": 0,
        "numberWidth": 3,
    }


def test_create_channel_writes_portable_yaml_roundtrip(tmp_path: Path) -> None:
    library, source = make_library(tmp_path)
    managed = tmp_path / "channels"
    service = BroadcasterService((), managed, library)

    result = service.create(editor(25, source, name="Sci-Fi Classics"))

    assert result.record.path == (managed / "channel-0025.yaml").resolve()
    assert result.record.path.is_file()

    loaded = load_channel(result.record.path)
    assert loaded.channel == 25
    assert loaded.display_number == "025"
    assert loaded.name == "Sci-Fi Classics"
    assert loaded.sources[0].path == source
    assert loaded.programming.mode == "sequential"

    text = result.record.path.read_text(encoding="utf-8")
    assert "schema_version" in text
    assert "channel: 25" in text
    assert "runtime" not in text.lower()


def test_create_never_overwrites_existing_channel_number(tmp_path: Path) -> None:
    library, source = make_library(tmp_path)
    service = BroadcasterService((), tmp_path / "channels", library)
    created = service.create(editor(7, source, name="Original"))
    before = created.record.path.read_text(encoding="utf-8")

    with pytest.raises(ChannelConflictError, match="already exists"):
        service.create(editor(7, source, name="Replacement"))

    assert created.record.path.read_text(encoding="utf-8") == before
    assert load_channel(created.record.path).name == "Original"


def test_create_refuses_unknown_existing_target_file(tmp_path: Path) -> None:
    library, source = make_library(tmp_path)
    managed = tmp_path / "channels"
    managed.mkdir()

    # The filename looks like Channel 42's managed target, but its contents are
    # a different valid channel. ChannelOS must not silently repurpose it.
    foreign_target = managed / "channel-0042.yaml"
    foreign_target.write_text(
        serialize_channel(definition_from_editor(editor(43, source))),
        encoding="utf-8",
    )

    service = BroadcasterService((), managed, library)
    before = foreign_target.read_text(encoding="utf-8")

    with pytest.raises(ChannelConflictError, match="will not overwrite"):
        service.create(editor(42, source))

    assert foreign_target.read_text(encoding="utf-8") == before
    assert load_channel(foreign_target).channel == 43


def test_explicit_edit_creates_backup_and_locks_channel_identity(tmp_path: Path) -> None:
    library, source = make_library(tmp_path)
    service = BroadcasterService((), tmp_path / "channels", library)
    created = service.create(editor(12, source, name="Before"))
    before = created.record.path.read_text(encoding="utf-8")

    updated = service.update(12, editor(12, source, name="After", mode="shuffle"))

    assert updated.backup_path is not None
    assert updated.backup_path.is_file()
    assert updated.backup_path.read_text(encoding="utf-8") == before
    assert load_channel(updated.record.path).name == "After"
    assert load_channel(updated.record.path).programming.mode == "shuffle"

    with pytest.raises(ChannelConflictError, match="renumbering"):
        service.update(12, editor(13, source, name="Renumbered"))

    assert load_channel(updated.record.path).channel == 12


def test_invalid_unindexed_source_fails_before_any_file_is_written(tmp_path: Path) -> None:
    library, _ = make_library(tmp_path)
    managed = tmp_path / "channels"
    service = BroadcasterService((), managed, library)

    missing_source = tmp_path / "not-indexed"
    with pytest.raises(BroadcasterError, match="does not resolve any indexed online media"):
        service.create(editor(31, missing_source))

    assert not managed.exists()


def test_preview_uses_real_resolver_and_deterministic_program_order(tmp_path: Path) -> None:
    library, source = make_library(tmp_path)
    service = BroadcasterService((), tmp_path / "channels", library)

    sequential = service.preview(editor(22, source, mode="sequential"))
    shuffle_one = service.preview(editor(23, source, mode="shuffle"))
    shuffle_two = service.preview(editor(23, source, mode="shuffle"))

    assert sequential["resolvedCount"] == 3
    assert [item["title"] for item in sequential["items"]] == [
        "01-alpha",
        "02-beta",
        "03-gamma",
    ]
    assert shuffle_one["resolvedCount"] == 3
    assert shuffle_one["items"] == shuffle_two["items"]
    assert {item["title"] for item in shuffle_one["items"]} == {
        "01-alpha",
        "02-beta",
        "03-gamma",
    }


def test_snapshot_lists_external_and_managed_channels_and_indexed_sources(tmp_path: Path) -> None:
    library, source = make_library(tmp_path)
    managed = tmp_path / "channels"
    managed.mkdir()

    managed_path = managed / "channel-0050.yaml"
    managed_path.write_text(
        serialize_channel(definition_from_editor(editor(50, source, name="Managed"))),
        encoding="utf-8",
    )

    external_path = tmp_path / "external.yaml"
    external_path.write_text(
        serialize_channel(definition_from_editor(editor(51, source, name="External"))),
        encoding="utf-8",
    )

    service = BroadcasterService((external_path,), managed, library)
    snapshot = service.snapshot()

    assert snapshot["channelCount"] == 2
    assert [channel["channelNumber"] for channel in snapshot["channels"]] == [50, 51]
    assert snapshot["channels"][0]["managed"] is True
    assert snapshot["channels"][1]["managed"] is False
    assert snapshot["sourceOptions"] == [str(source)]
    assert snapshot["suggestedChannel"] == 1
