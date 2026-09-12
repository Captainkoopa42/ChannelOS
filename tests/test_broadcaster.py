from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest

from channelos.broadcaster import (
    BroadcasterError,
    BroadcasterService,
    ChannelConflictError,
    StudioAutoFillCancelled,
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


def test_delete_managed_channel_keeps_recovery_backup(tmp_path: Path) -> None:
    library, source = make_library(tmp_path)
    service = BroadcasterService((), tmp_path / "channels", library)
    deleted_record = service.create(editor(7, source, name="Delete Me")).record
    service.create(editor(12, source, name="Keep Me"))
    original = deleted_record.path.read_text(encoding="utf-8")

    result = service.delete(7)

    assert service.channel_numbers == (12,)
    assert not deleted_record.path.exists()
    assert result.backup_path.is_file()
    assert result.backup_path.read_text(encoding="utf-8") == original
    assert result.backup_path.name.startswith(
        "channel-0007.yaml.deleted-"
    )
    assert result.backup_path.name.endswith(".bak")
    assert result.replacement_channel_number == 12

    service.restore_deleted(result)

    assert service.channel_numbers == (7, 12)
    assert deleted_record.path.is_file()
    assert deleted_record.path.read_text(encoding="utf-8") == original
    assert not result.backup_path.exists()


def test_delete_refuses_to_remove_the_only_channel(tmp_path: Path) -> None:
    library, source = make_library(tmp_path)
    service = BroadcasterService((), tmp_path / "channels", library)
    created = service.create(editor(7, source)).record

    with pytest.raises(BroadcasterError, match="at least one active channel"):
        service.delete(7)

    assert created.path.is_file()
    assert service.channel_numbers == (7,)


def test_delete_refuses_external_channel_definition(tmp_path: Path) -> None:
    library, source = make_library(tmp_path)
    managed = tmp_path / "channels"
    managed.mkdir()
    external = tmp_path / "external-channel.yaml"
    external.write_text(
        serialize_channel(definition_from_editor(editor(7, source))),
        encoding="utf-8",
    )
    service = BroadcasterService((external,), managed, library)
    service.create(editor(12, source))

    with pytest.raises(BroadcasterError, match="external definition"):
        service.delete(7)

    assert external.is_file()
    assert service.channel_numbers == (7, 12)


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


def test_studio_auto_fill_returns_editable_gapless_blocks(tmp_path: Path) -> None:
    library, source = make_library(tmp_path)
    service = BroadcasterService((), tmp_path / "channels", library)
    raw = editor(32, source, name="Studio TV")
    raw["fillerMode"] = "sequential"
    start = datetime(2026, 9, 7, tzinfo=timezone.utc)
    end = start + timedelta(minutes=3)

    result = service.auto_fill_studio(raw, start.isoformat(), end.isoformat())

    assert result["ok"] is True
    assert len(result["blocks"]) == 6
    assert result["blocks"][0]["startUtc"] == start.isoformat()
    for left, right in zip(result["blocks"], result["blocks"][1:]):
        assert left["endUtc"] == right["startUtc"]


def test_studio_auto_fill_reports_progress_and_can_cancel_safely(
    tmp_path: Path,
) -> None:
    library, source = make_library(tmp_path)
    service = BroadcasterService((), tmp_path / "channels", library)
    raw = editor(32, source, name="Studio TV")
    start = datetime(2026, 9, 7, tzinfo=timezone.utc)
    updates: list[tuple[int, int, str]] = []
    cancel_requested = False

    def publish(current: int, total: int, message: str) -> None:
        nonlocal cancel_requested
        updates.append((current, total, message))
        if current > 0:
            cancel_requested = True

    with pytest.raises(StudioAutoFillCancelled):
        service.auto_fill_studio(
            raw,
            start.isoformat(),
            (start + timedelta(minutes=3)).isoformat(),
            on_progress=publish,
            should_cancel=lambda: cancel_requested,
        )

    assert any(total == 0 for _, total, _ in updates)
    assert any(current > 0 and total > 0 for current, total, _ in updates)


def test_studio_auto_fill_progress_reaches_complete(tmp_path: Path) -> None:
    library, source = make_library(tmp_path)
    service = BroadcasterService((), tmp_path / "channels", library)
    raw = editor(32, source, name="Studio TV")
    start = datetime(2026, 9, 7, tzinfo=timezone.utc)
    updates: list[tuple[int, int, str]] = []

    service.auto_fill_studio(
        raw,
        start.isoformat(),
        (start + timedelta(minutes=3)).isoformat(),
        on_progress=lambda current, total, message: updates.append(
            (current, total, message)
        ),
    )

    assert updates[-1][0] == updates[-1][1]
    assert updates[-1][2] == "Auto Fill schedule ready"


def test_studio_calendar_roundtrip_and_preview_use_stable_asset_ids(tmp_path: Path) -> None:
    library, source = make_library(tmp_path)
    managed = tmp_path / "channels"
    service = BroadcasterService((), managed, library)
    media = service.studio_media()
    start = datetime(2026, 9, 7, tzinfo=timezone.utc)
    raw = editor(44, source, name="Prime Time")
    raw.update(
        {
            "mode": "calendar",
            "fillerMode": "shuffle",
            "calendarBlocks": [
                {
                    "assetId": media[0]["assetId"],
                    "startUtc": start.isoformat(),
                },
                {
                    "assetId": media[1]["assetId"],
                    "startUtc": (start + timedelta(seconds=30)).isoformat(),
                },
            ],
        }
    )

    preview = service.preview(raw)
    created = service.create(raw)
    loaded = load_channel(created.record.path)
    draft = service.studio_draft(44)

    assert preview["mode"] == "calendar"
    assert preview["items"][0]["assetId"] == media[0]["assetId"]
    assert loaded.schema_version == "0.2"
    assert loaded.programming.mode == "calendar"
    assert loaded.programming.filler_mode == "shuffle"
    assert [block.asset_id for block in loaded.programming.calendar] == [
        media[0]["assetId"],
        media[1]["assetId"],
    ]
    assert draft["editingChannelNumber"] == 44
    assert draft["calendarBlocks"][0]["title"] == "01-alpha"


def test_studio_auto_fill_leaves_short_range_remainder_to_filler(tmp_path: Path) -> None:
    library, source = make_library(tmp_path)
    service = BroadcasterService((), tmp_path / "channels", library)
    raw = editor(32, source)
    start = datetime(2026, 9, 7, tzinfo=timezone.utc)

    result = service.auto_fill_studio(
        raw,
        start.isoformat(),
        (start + timedelta(seconds=75)).isoformat(),
    )

    assert len(result["blocks"]) == 2
    assert result["blocks"][-1]["endUtc"] == (
        start + timedelta(seconds=60)
    ).isoformat()
    assert "filler covers any short remainder" in result["message"]
