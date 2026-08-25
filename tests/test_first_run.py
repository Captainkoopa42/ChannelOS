from __future__ import annotations

from pathlib import Path

from channelos import first_run


def test_first_run_required_for_fresh_data_directory(tmp_path: Path) -> None:
    assert first_run.first_run_required(tmp_path) is True


def test_first_run_ready_when_library_and_channel_exist(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "library.db").write_bytes(b"placeholder")
    channels = tmp_path / "channels"
    channels.mkdir()
    (channels / "channel-0001.yaml").write_text("channel: 1\n", encoding="utf-8")

    class FakeLibrary:
        def list_online_media(self):
            return [object()]

    monkeypatch.setattr(first_run, "MediaLibrary", lambda _path: FakeLibrary())

    assert first_run.first_run_required(tmp_path) is False


def test_first_channel_editor_uses_owned_folder_without_moving_it(tmp_path: Path) -> None:
    source = tmp_path / "Saturday Cartoons"
    source.mkdir()

    editor = first_run.first_channel_editor(source, channel=7)

    assert editor["channel"] == 7
    assert editor["name"] == "Saturday Cartoons"
    assert editor["sources"] == [str(source.resolve())]
    assert editor["mode"] == "sequential"
    assert editor["preserveEpisodeOrder"] is True
    assert editor["numberWidth"] == 3
