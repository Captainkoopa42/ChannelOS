from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from channelos.library import IndexedMedia, MediaAsset, MediaLocation
from channelos.models import ChannelDefinition
from channelos.playback import PlaybackError
from channelos.resolve import ResolvedChannel
from channelos.runtime import ChannelRuntime, RuntimeStore, TelevisionRuntime
from channelos.television import TelevisionSession

UTC = timezone.utc


class FakeBackend:
    def __init__(self) -> None:
        self.loaded: Path | None = None
        self.position = 0.0
        self.events: list[str] = []
        self.error_message: str | None = None

    def load(self, path):
        self.loaded = Path(path)
        self.events.append("load")

    def play(self):
        self.events.append("play")

    def pause(self):
        self.events.append("pause")

    def stop(self):
        self.events.append("stop")

    def seek(self, seconds):
        self.position = float(seconds)
        self.events.append("seek")

    def get_position(self):
        return self.position

    def set_volume(self, percent):
        return None

    def get_volume(self):
        return 50

    def set_muted(self, muted):
        return None

    def get_muted(self):
        return False

    def set_rate(self, rate):
        return None

    def playback_error(self):
        return self.error_message


def make_resolved(tmp_path: Path, number: int, durations: list[float]) -> ResolvedChannel:
    definition = ChannelDefinition.from_mapping(
        {
            "schema_version": "0.1",
            "channel": number,
            "name": f"Channel {number}",
            "sources": [{"path": str(tmp_path / str(number))}],
            "programming": {"mode": "sequential"},
            "presentation": {"number_width": 3},
        }
    )

    media: list[IndexedMedia] = []
    for index, duration in enumerate(durations):
        path = tmp_path / str(number) / f"{index:02d}.mp4"
        asset = MediaAsset(
            asset_id=f"sha256:{number}-{index}",
            content_sha256=f"{number}-{index}",
            size_bytes=1,
            duration_seconds=duration,
            container_format="mp4",
        )
        location = MediaLocation(
            path=path,
            path_key=str(path),
            asset_id=asset.asset_id,
            source_root=path.parent,
            online=True,
        )
        media.append(IndexedMedia(asset, location))
    return ResolvedChannel(definition, tuple(media))


def make_session(tmp_path: Path, epoch: datetime) -> tuple[TelevisionSession, FakeBackend]:
    store = RuntimeStore(tmp_path / "runtime.db")
    channel_7 = ChannelRuntime.open(
        make_resolved(tmp_path, 7, [30.0, 30.0]),
        store,
        now=epoch,
    )
    channel_12 = ChannelRuntime.open(
        make_resolved(tmp_path, 12, [20.0, 20.0, 20.0]),
        store,
        now=epoch,
    )
    backend = FakeBackend()
    return TelevisionSession(TelevisionRuntime((channel_7, channel_12), store), backend), backend


def test_watch_ahead_loads_future_program_and_go_live_returns_decoder(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, tzinfo=UTC)
    session, backend = make_session(tmp_path, epoch)
    session.tune(7, now=epoch + timedelta(seconds=5))

    ahead = session.skip(30, now=epoch + timedelta(seconds=5))
    assert ahead.ahead_seconds == 30
    assert backend.loaded == tmp_path / "7" / "01.mp4"
    assert backend.position == pytest.approx(5)
    assert "AHEAD" in session.describe(ahead)

    # Crossing another occurrence while ahead still follows the viewer timeline.
    next_program = session.sync(now=epoch + timedelta(seconds=35))
    assert next_program.ahead_seconds == 30
    assert backend.loaded == tmp_path / "7" / "00.mp4"
    assert backend.position == pytest.approx(5)

    session.pause(now=epoch + timedelta(seconds=35))
    session.skip(30, now=epoch + timedelta(seconds=35))
    assert session.paused
    assert backend.events[-1] == "pause"
    assert backend.loaded == tmp_path / "7" / "01.mp4"

    live = session.go_live(now=epoch + timedelta(seconds=40))
    assert live.is_live
    assert not session.paused
    assert backend.loaded == tmp_path / "7" / "01.mp4"
    assert backend.position == pytest.approx(10)


def test_tune_intent_loads_broadcast_asset_and_seeks_to_live_offset(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    session, backend = make_session(tmp_path, epoch)

    result = session.execute("TUNE 007", now=epoch + timedelta(seconds=42))

    assert "Channel 007" in result
    assert backend.loaded == tmp_path / "7" / "01.mp4"
    assert backend.position == pytest.approx(12.0)
    assert backend.events == ["load", "play", "seek"]


def test_sync_surfaces_asynchronous_decoder_failure_and_allows_reload(
    tmp_path: Path,
) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    session, backend = make_session(tmp_path, epoch)
    session.tune(7, now=epoch)
    backend.error_message = "decoder failed"

    with pytest.raises(PlaybackError, match="decoder failed"):
        session.sync(now=epoch + timedelta(seconds=1))

    assert session.loaded_asset_id is None
    assert session.loaded_program_started_at is None


def test_channel_up_and_previous_follow_independent_broadcast_clocks(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    session, backend = make_session(tmp_path, epoch)

    session.execute("TUNE 007", now=epoch)
    session.execute("CHANNEL_UP", now=epoch + timedelta(seconds=25))

    assert backend.loaded == tmp_path / "12" / "01.mp4"
    assert backend.position == pytest.approx(5.0)

    result = session.execute("PREVIOUS_CHANNEL", now=epoch + timedelta(seconds=50))
    assert "Channel 007" in result
    assert backend.loaded == tmp_path / "7" / "01.mp4"
    assert backend.position == pytest.approx(20.0)


def test_pause_skip_and_go_live_keep_viewer_clock_authoritative(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    session, backend = make_session(tmp_path, epoch)

    session.execute("TUNE 007", now=epoch)
    session.execute("PAUSE", now=epoch + timedelta(seconds=10))
    paused_event_count = len(backend.events)

    session.execute("SKIP_BACK 5", now=epoch + timedelta(seconds=20))
    assert backend.position == pytest.approx(5.0)
    assert backend.events[-1] == "pause"
    assert len(backend.events) > paused_event_count

    result = session.execute("GO_LIVE", now=epoch + timedelta(seconds=50))
    assert "LIVE" in result
    assert backend.loaded == tmp_path / "7" / "01.mp4"
    assert backend.position == pytest.approx(20.0)


def test_resume_tuning_uses_saved_viewer_position(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    session, backend = make_session(tmp_path, epoch)

    session.tune(7, now=epoch)
    session.tune(12, now=epoch + timedelta(seconds=20))
    decision = session.tune(7, now=epoch + timedelta(seconds=50), return_behavior="resume")

    assert decision.lag_seconds == pytest.approx(30.0)
    assert backend.loaded == tmp_path / "7" / "00.mp4"
    assert backend.position == pytest.approx(20.0)


def test_lineup_reload_restores_running_viewer_clock(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    original, _ = make_session(tmp_path, epoch)
    original.tune(7, now=epoch + timedelta(seconds=5))

    restored, backend = make_session(tmp_path, epoch)
    decision = restored.restore_after_lineup_change(
        7,
        paused=False,
        now=epoch + timedelta(seconds=20),
    )

    assert decision.channel_number == 7
    assert decision.viewer_time_utc == epoch + timedelta(seconds=20)
    assert backend.position == pytest.approx(20.0)
    assert backend.events == ["load", "play", "seek"]


def test_lineup_reload_rebuilds_picture_then_restores_pause(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    original, _ = make_session(tmp_path, epoch)
    original.tune(7, now=epoch)
    original.pause(now=epoch + timedelta(seconds=10))

    restored, backend = make_session(tmp_path, epoch)
    decision = restored.restore_after_lineup_change(
        7,
        paused=True,
        now=epoch + timedelta(seconds=30),
    )

    assert decision.viewer_time_utc == epoch + timedelta(seconds=10)
    assert restored.paused
    assert backend.position == pytest.approx(10.0)
    assert backend.events == ["load", "play", "seek", "pause"]


def test_lineup_reload_tunes_survivor_when_current_channel_was_removed(
    tmp_path: Path,
) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    original, _ = make_session(tmp_path, epoch)
    original.tune(7, now=epoch)

    store = original.runtime.store
    surviving = ChannelRuntime.open(
        make_resolved(tmp_path, 12, [20.0, 20.0, 20.0]),
        store,
        now=epoch,
    )
    backend = FakeBackend()
    restored = TelevisionSession(
        TelevisionRuntime((surviving,), store),
        backend,
    )

    decision = restored.restore_after_lineup_change(
        12,
        paused=True,
        now=epoch + timedelta(seconds=25),
    )

    assert decision.channel_number == 12
    assert decision.is_live
    assert restored.runtime.current_channel == 12
    assert not restored.paused
    assert backend.events == ["load", "play", "seek"]


def test_watch_from_beginning_fractional_boundary_keeps_exact_clock_and_correct_asset(
    tmp_path: Path,
) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    store = RuntimeStore(tmp_path / "runtime.db")
    channel_7 = ChannelRuntime.open(
        make_resolved(tmp_path, 7, [15.133, 20.133]),
        store,
        now=epoch,
    )
    backend = FakeBackend()
    session = TelevisionSession(TelevisionRuntime((channel_7,), store), backend)
    program_start = epoch + timedelta(seconds=15.133)
    reference = epoch + timedelta(seconds=40)

    decision = session.watch_from_beginning(7, program_start, now=reference)

    assert decision.viewer_time_utc == program_start
    assert decision.lag_seconds == pytest.approx(24.867)
    assert decision.viewer_selection.program_started_at == program_start
    assert decision.viewer_selection.offset_seconds == pytest.approx(0.0)
    assert backend.loaded == tmp_path / "7" / "01.mp4"
    assert backend.position == pytest.approx(0.0)


def test_ad_playback_interrupts_and_resumes_exact_program_position(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    base = make_resolved(tmp_path, 77, [30.0, 30.0])
    definition = ChannelDefinition.from_mapping(
        {
            "schema_version": "0.4",
            "channel": 77,
            "name": "Ad TV",
            "sources": [{"path": str(source.path)} for source in base.definition.sources],
            "advertising": {
                "enabled": True,
                "sources": [{"path": str(tmp_path / "ads")}],
                "breakpoints_seconds": [10.0],
                "break_duration_seconds": 5.0,
            },
            "programming": {"mode": "sequential"},
        }
    )
    ad_path = tmp_path / "ads" / "spot.mp4"
    ad_asset = MediaAsset(
        asset_id="sha256:tv-ad", content_sha256="tv-ad", size_bytes=1,
        duration_seconds=5.0, container_format="mp4",
    )
    ad = IndexedMedia(
        ad_asset,
        MediaLocation(
            path=ad_path, path_key=str(ad_path), asset_id=ad_asset.asset_id,
            source_root=ad_path.parent, online=True,
        ),
    )
    resolved = ResolvedChannel(definition, base.media, (ad,))
    store = RuntimeStore(tmp_path / "ad-tv-runtime.db")
    runtime = ChannelRuntime.open(resolved, store, now=epoch)
    backend = FakeBackend()
    session = TelevisionSession(TelevisionRuntime((runtime,), store), backend)

    during_ad = session.tune(77, now=epoch + timedelta(seconds=12))
    assert during_ad.viewer_selection.origin == "advertisement"
    assert backend.loaded == ad_path
    assert backend.position == pytest.approx(2.0)

    resumed = session.sync(now=epoch + timedelta(seconds=15))
    assert resumed.viewer_selection.origin != "advertisement"
    assert backend.loaded == tmp_path / "77" / "00.mp4"
    assert backend.position == pytest.approx(10.0)


def test_viewer_ad_completion_requires_actual_decoder_progress(tmp_path: Path):
    from dataclasses import replace
    from channelos.models import AdvertisingDefinition, SourceDefinition

    epoch = datetime(2026, 10, 30, 12, tzinfo=UTC)
    base = make_resolved(tmp_path, 7, [30.0])
    ad_path = tmp_path / "ads" / "spot.mp4"
    ad_asset = MediaAsset(
        asset_id="sha256:viewer-spot", content_sha256="viewer-spot",
        size_bytes=1, duration_seconds=5.0, container_format="mp4",
    )
    ad_item = IndexedMedia(ad_asset, MediaLocation(
        path=ad_path, path_key=str(ad_path), asset_id=ad_asset.asset_id,
        source_root=ad_path.parent, online=True,
    ))
    definition = replace(base.definition, advertising=AdvertisingDefinition(
        enabled=True, sources=(SourceDefinition(ad_path.parent),),
        breakpoints_seconds=(10.0,), break_duration_seconds=5.0,
    ))
    resolved = ResolvedChannel(definition, base.media, (ad_item,))
    store = RuntimeStore(tmp_path / "ad-view.db")
    channel = ChannelRuntime.open(resolved, store, now=epoch)
    backend = FakeBackend()
    session = TelevisionSession(TelevisionRuntime((channel,), store), backend)

    session.tune(7, now=epoch + timedelta(seconds=10))
    assert session.runtime.status(now=epoch + timedelta(seconds=10)).viewer_selection.origin == "advertisement"
    for offset in range(1, 6):
        backend.position = float(offset)
        session.sync(now=epoch + timedelta(seconds=10 + offset))
    assert channel.break_store.viewer_counts(7) == {ad_asset.asset_id: 1}
    assert channel.break_store.diagnostics(7)["completedViewings"] == 1


def test_viewer_does_not_count_seek_over_ad_as_watched(tmp_path: Path):
    from dataclasses import replace
    from channelos.models import AdvertisingDefinition, SourceDefinition

    epoch = datetime(2026, 10, 30, 12, tzinfo=UTC)
    base = make_resolved(tmp_path, 7, [30.0])
    ad_path = tmp_path / "ads" / "spot.mp4"
    ad_asset = MediaAsset(
        asset_id="sha256:skip-spot", content_sha256="skip-spot",
        size_bytes=1, duration_seconds=5.0, container_format="mp4",
    )
    ad_item = IndexedMedia(ad_asset, MediaLocation(
        path=ad_path, path_key=str(ad_path), asset_id=ad_asset.asset_id,
        source_root=ad_path.parent, online=True,
    ))
    definition = replace(base.definition, advertising=AdvertisingDefinition(
        enabled=True, sources=(SourceDefinition(ad_path.parent),),
        breakpoints_seconds=(10.0,), break_duration_seconds=5.0,
    ))
    store = RuntimeStore(tmp_path / "ad-view.db")
    channel = ChannelRuntime.open(ResolvedChannel(definition, base.media, (ad_item,)), store, now=epoch)
    backend = FakeBackend()
    session = TelevisionSession(TelevisionRuntime((channel,), store), backend)
    session.tune(7, now=epoch + timedelta(seconds=10))
    backend.position = 5.0  # seek straight across the full advertisement
    session.sync(now=epoch + timedelta(seconds=15))
    assert channel.break_store.viewer_counts(7) == {}


@pytest.mark.parametrize("watch_ad", [False, True])
def test_future_ad_viewing_uses_observation_time_without_marking_it_aired(tmp_path, watch_ad):
    from dataclasses import replace
    from channelos.models import AdvertisingDefinition, SourceDefinition

    epoch = datetime(2026, 10, 31, 12, tzinfo=UTC)
    base = make_resolved(tmp_path, 7, [30.0])
    ad_path = tmp_path / "ads" / "spot.mp4"
    asset = MediaAsset(
        asset_id="sha256:future-ad", content_sha256="future-ad",
        size_bytes=1, duration_seconds=5.0, container_format="mp4",
    )
    ad = IndexedMedia(asset, MediaLocation(
        path=ad_path, path_key=str(ad_path), asset_id=asset.asset_id,
        source_root=ad_path.parent, online=True,
    ))
    definition = replace(base.definition, advertising=AdvertisingDefinition(
        enabled=True, sources=(SourceDefinition(ad_path.parent),),
        breakpoints_seconds=(10.0,), break_duration_seconds=5.0,
    ))
    store = RuntimeStore(tmp_path / "future-ad.db")
    channel = ChannelRuntime.open(ResolvedChannel(definition, base.media, (ad,)), store, now=epoch)
    backend = FakeBackend()
    session = TelevisionSession(TelevisionRuntime((channel,), store), backend)
    try:
        session.tune(7, now=epoch)
        ahead = session.skip(10, now=epoch)
        assert ahead.is_ahead
        assert backend.loaded == ad_path
        assert channel.break_store.diagnostics(7)["completedAirings"] == 0
        if watch_ad:
            for elapsed in range(1, 6):
                backend.position = float(elapsed)
                session.sync(now=epoch + timedelta(seconds=elapsed))
        else:
            session.skip(5, now=epoch)

        assert channel.break_store.diagnostics(7)["completedAirings"] == 0
        assert channel.break_store.viewer_counts(7) == ({asset.asset_id: 1} if watch_ad else {})
        if watch_ad:
            completed_at = channel.break_store.connection.execute(
                "SELECT completed_at FROM ad_view_history"
            ).fetchone()[0]
            assert datetime.fromisoformat(completed_at) == epoch + timedelta(seconds=5)
    finally:
        channel.break_store.close()
