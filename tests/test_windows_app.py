from pathlib import Path

from channelos import windows_app
from channelos.first_run import FIRST_RUN_CANCELLED


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


def test_ordinary_first_run_candidate_is_only_normal_launch_or_windowed() -> None:
    assert windows_app._ordinary_first_run_candidate([]) is True
    assert windows_app._ordinary_first_run_candidate(["--windowed"]) is True
    assert windows_app._ordinary_first_run_candidate(["--help"]) is False
    assert windows_app._ordinary_first_run_candidate(["channel.yaml"]) is False


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


def test_frozen_first_run_cancel_exits_without_starting_couch(
    monkeypatch,
    tmp_path: Path,
) -> None:
    couch_calls: list[list[str]] = []
    monkeypatch.setenv("CHANNELOS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(windows_app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(windows_app, "first_run_required", lambda _path: True)
    monkeypatch.setattr(
        windows_app,
        "_run_first_run_helper",
        lambda _path: FIRST_RUN_CANCELLED,
    )
    monkeypatch.setattr(
        windows_app.couch,
        "main",
        lambda argv: couch_calls.append(list(argv)) or 0,
    )

    assert windows_app.main([]) == 0
    assert couch_calls == []


def test_frozen_first_run_success_continues_into_couch(
    monkeypatch,
    tmp_path: Path,
) -> None:
    couch_calls: list[list[str]] = []
    monkeypatch.setenv("CHANNELOS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(windows_app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(windows_app, "first_run_required", lambda _path: True)
    monkeypatch.setattr(windows_app, "_run_first_run_helper", lambda _path: 0)
    monkeypatch.setattr(
        windows_app.couch,
        "main",
        lambda argv: couch_calls.append(list(argv)) or 0,
    )

    assert windows_app.main([]) == 0
    assert len(couch_calls) == 1
    assert couch_calls[0][:2] == ["--db", str(tmp_path / "library.db")]
