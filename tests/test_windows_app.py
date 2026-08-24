from pathlib import Path

from channelos import windows_app


def test_packaged_defaults_use_per_user_data_directory(tmp_path: Path) -> None:
    arguments = windows_app.couch_arguments(["channel.yaml"], tmp_path)

    assert arguments == [
        "--db",
        str(tmp_path / "library.db"),
        "--state-db",
        str(tmp_path / "runtime.db"),
        "--channels-dir",
        str(tmp_path / "channels"),
        "channel.yaml",
    ]


def test_explicit_storage_paths_are_not_overridden(tmp_path: Path) -> None:
    arguments = windows_app.couch_arguments(
        ["--db", "custom.db", "--state-db", "state.db", "--channels-dir", "mine"],
        tmp_path,
    )

    assert arguments == [
        "--db",
        "custom.db",
        "--state-db",
        "state.db",
        "--channels-dir",
        "mine",
    ]


def test_default_data_directory_honors_override() -> None:
    assert windows_app.default_data_directory(
        {"CHANNELOS_DATA_DIR": "D:/Portable/ChannelOS"}
    ) == Path("D:/Portable/ChannelOS")


def test_packaged_launcher_creates_log_and_surfaces_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    messages: list[str] = []
    received: list[str] = []
    monkeypatch.setenv("CHANNELOS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(windows_app, "_show_error", messages.append)
    monkeypatch.setattr(windows_app.couch, "main", lambda argv: received.extend(argv) or 6)

    assert windows_app.main([]) == 6

    assert (tmp_path / "channels").is_dir()
    assert list((tmp_path / "logs").glob("channelos-*.log"))
    assert messages and str(tmp_path / "logs") in messages[0]
    assert received[:2] == ["--db", str(tmp_path / "library.db")]
