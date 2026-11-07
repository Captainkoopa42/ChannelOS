"""Video settings: Settings screen -> saved preferences -> both playback owners."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")


def test_video_settings_cycle_persist_and_reach_playback(tmp_path: Path) -> None:
    from test_performance_operations import controller_fixture
    app, controller, _root = controller_fixture(tmp_path)
    try:
        result = controller.adjustSetting("videoAspectRatio", 1)
        assert result["ok"] and result["message"] == "Aspect ratio: 16:9"
        assert controller.settings["videoAspectRatio"] == "16:9"
        assert controller.adjustSetting("videoAspectRatio", -1)["message"] == "Aspect ratio: Auto"
        assert controller.adjustSetting("videoAspectRatio", -1)["message"] == "Aspect ratio: 1:1"

        assert controller.adjustSetting("videoFit", 1)["message"] == "Picture fit: Fill (crop edges)"
        assert controller.adjustSetting("videoOverscan", 1)["message"] == "Overscan trim: 2%"
        assert "next program" in controller.adjustSetting("videoDeinterlace", 1)["message"]
        assert controller.adjustSetting("videoBrightness", 1)["message"] == "Brightness: 110%"
        assert controller.adjustSetting("theme", 1)["message"] == "Theme: ChromeSpace"

        video = controller._settings.video
        assert (video.aspect_ratio, video.fit, video.overscan_percent, video.deinterlace, video.brightness) == \
            ("1:1", "fill", 2, "off", 110)
        # Both playback owners hold the new picture for their next backend.
        assert controller._actions._video_settings == video
        assert controller._on_demand._video_settings == video
        controller.setVideoSurfaceSize(1280, 720)
        assert controller._actions._surface_size == (1280, 720)

        # Saved to disk and restored by Reset.
        saved = controller._settings_store.load()
        assert saved.video == video and saved.theme == "chromespace"
        controller.resetSettings()
        assert controller._settings.video.aspect_ratio == "auto"
        assert controller._actions._video_settings.aspect_ratio == "auto"
    finally:
        controller.stop()
