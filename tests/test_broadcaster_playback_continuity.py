from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtGui", exc_type=ImportError)

from channelos import broadcaster_qt
from channelos.broadcaster import BroadcasterService
from channelos.guide import GuideService
from channelos.library import MediaLibrary
from channelos.playback import NativeVideoSurface
from channelos.probe import MediaProbeResult
from channelos.resolve import resolve_channel
from channelos.runtime import ChannelRuntime, RuntimeStore, TelevisionRuntime
from channelos.scanner import MediaScanner


class FixedProbe:
    def probe(self, path: Path) -> MediaProbeResult:
        return MediaProbeResult(
            duration_seconds=30.0,
            container_format=path.suffix.lstrip(".") or "mp4",
        )


class FakeReloadActions:
    created: list["FakeReloadActions"] = []

    def __init__(self, service: GuideService, runtime: TelevisionRuntime) -> None:
        self.service = service
        self.runtime = runtime
        self.stopped = False
        self.restored_channel: int | None = None
        self._paused = False
        self._last_decision = None
        self.created.append(self)

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def last_decision(self):
        return self._last_decision

    def set_audio_output_device(self, device_id: str | None) -> None:
        return None

    def attach_video_surface(self, surface: NativeVideoSurface) -> None:
        return None

    def restore_after_lineup_change(
        self,
        channel_number: int,
        *,
        paused: bool,
    ):
        self.restored_channel = int(channel_number)
        self._last_decision = self.runtime.tune(
            self.restored_channel,
            return_behavior="live",
        )
        self._paused = bool(paused)
        return self._last_decision

    def set_volume(self, percent: int) -> int:
        return int(percent)

    def set_muted(self, muted: bool) -> bool:
        return bool(muted)

    def stop(self) -> None:
        self.stopped = True


def _editor(channel: int, source: Path) -> dict[str, object]:
    return {
        "channel": channel,
        "name": f"Channel {channel}",
        "description": "Playback continuity test",
        "sources": [str(source)],
        "mode": "sequential",
        "preserveEpisodeOrder": False,
        "avoidRepeatDays": 0,
        "numberWidth": 3,
    }


def test_deleting_playing_channel_starts_surviving_replacement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    (media_root / "movie.mp4").write_bytes(b"owned-media")
    library = MediaLibrary(tmp_path / "library.db")
    MediaScanner(library, FixedProbe()).scan(media_root)

    broadcaster = BroadcasterService((), tmp_path / "channels", library)
    broadcaster.create(_editor(7, media_root))
    broadcaster.create(_editor(12, media_root))

    store = RuntimeStore(tmp_path / "runtime.db")
    runtimes = tuple(
        ChannelRuntime.open(
            resolve_channel(record.definition, library),
            store,
        )
        for record in broadcaster.records
    )
    service = GuideService(runtimes)
    television = TelevisionRuntime(runtimes, store)
    television.tune(7, return_behavior="live")

    controller = broadcaster_qt.BroadcasterCouchController(
        service,
        television,
        library,
        broadcaster,
        store,
    )
    previous_actions = FakeReloadActions(service, television)
    controller._actions = previous_actions
    controller._playback = {
        "active": True,
        "channelNumber": 7,
        "paused": False,
    }
    FakeReloadActions.created.clear()
    monkeypatch.setattr(broadcaster_qt, "CouchActions", FakeReloadActions)

    result = controller.deleteChannel(7)

    assert result["ok"] is True
    assert previous_actions.stopped
    assert FakeReloadActions.created[-1].restored_channel == 12
    assert controller.playback["active"] is True
    assert controller.playback["channelNumber"] == 12
    assert store.get_tuning()[0] == 12
    assert broadcaster.channel_numbers == (12,)
