import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

PACKAGE_TOOL = Path(__file__).resolve().parents[1] / "tools" / "windows" / "package_windows.py"
PACKAGE_SPEC = importlib.util.spec_from_file_location("channelos_package_windows", PACKAGE_TOOL)
assert PACKAGE_SPEC is not None and PACKAGE_SPEC.loader is not None
package_windows = importlib.util.module_from_spec(PACKAGE_SPEC)
PACKAGE_SPEC.loader.exec_module(package_windows)


def _fake_runtime_package(path: Path) -> dict[str, object]:
    nuspec = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://schemas.microsoft.com/packaging/2011/08/nuspec.xsd">
  <metadata>
    <id>VideoLAN.LibVLC.Windows</id>
    <version>9.9.9</version>
    <license type="expression">LGPL-2.1-or-later</license>
  </metadata>
</package>
"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("VideoLAN.LibVLC.Windows.nuspec", nuspec)
        archive.writestr("build/x64/libvlc.dll", b"vlc")
        archive.writestr("build/x64/libvlccore.dll", b"core")
        archive.writestr("build/x64/libvlc.lib", b"development-only")
        archive.writestr("build/x64/include/vlc/vlc.h", b"header")
        for index in range(100):
            archive.writestr(
                f"build/x64/plugins/test/plugin-{index:03d}.dll",
                bytes([index]),
            )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "component": "VideoLAN.LibVLC.Windows",
        "version": "9.9.9",
        "architecture": "x64",
        "source_prefix": "build/x64/",
        "download_url": "https://api.nuget.org/example.nupkg",
        "sha256": digest,
        "license": "LGPL-2.1-or-later",
        "project_url": "https://example.invalid",
        "corresponding_source": "https://example.invalid/source",
    }


def test_runtime_lock_pins_current_lgpl_package() -> None:
    lock = package_windows.load_runtime_lock()

    assert lock["component"] == "VideoLAN.LibVLC.Windows"
    assert lock["version"] == "3.0.23.1"
    assert lock["license"] == "LGPL-2.1-or-later"
    assert len(lock["sha256"]) == 64


def test_runtime_staging_copies_only_runtime_files(tmp_path: Path) -> None:
    archive = tmp_path / "runtime.nupkg"
    lock = _fake_runtime_package(archive)

    copied = package_windows.stage_vlc_runtime(archive, tmp_path / "vlc", lock)

    assert "libvlc.dll" in copied
    assert "libvlccore.dll" in copied
    assert len([name for name in copied if name.startswith("plugins/")]) == 100
    assert not (tmp_path / "vlc" / "libvlc.lib").exists()
    assert not (tmp_path / "vlc" / "include").exists()


def test_runtime_staging_rejects_changed_download(tmp_path: Path) -> None:
    archive = tmp_path / "runtime.nupkg"
    lock = _fake_runtime_package(archive)
    archive.write_bytes(archive.read_bytes() + b"changed")

    with pytest.raises(package_windows.PackageError, match="hash mismatch"):
        package_windows.stage_vlc_runtime(archive, tmp_path / "vlc", lock)


def test_package_validation_compares_every_frozen_file(tmp_path: Path) -> None:
    required_files = (
        "ChannelOS.exe",
        "runtime/vlc/libvlc.dll",
        "runtime/vlc/libvlccore.dll",
        "runtime/vlc/plugins/test.dll",
        "licenses/LICENSE.md",
        "licenses/THIRD_PARTY_NOTICES.md",
        "licenses/DISTRIBUTION.md",
        "licenses/LGPL-2.1.txt",
        "licenses/LGPL-3.0.txt",
        "licenses/PYTHON.txt",
        "licenses/REPLACING-LGPL-LIBRARIES.md",
    )
    for relative in required_files:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(relative.encode())

    bom = {
        "files": package_windows.file_inventory(
            tmp_path,
            excluded=("PACKAGE-BOM.json",),
        )
    }
    (tmp_path / "PACKAGE-BOM.json").write_text(json.dumps(bom), encoding="utf-8")
    package_windows.validate_package_root(tmp_path)

    (tmp_path / "unexpected.dll").write_bytes(b"surprise")
    with pytest.raises(package_windows.PackageError, match="frozen BOM"):
        package_windows.validate_package_root(tmp_path)


def test_pyinstaller_spec_is_replaceable_one_folder_layout() -> None:
    spec = package_windows.SPEC_PATH.read_text(encoding="utf-8")

    assert "COLLECT(" in spec
    assert 'contents_directory="_internal"' in spec
    assert "console=False" in spec
    assert "--onefile" not in spec


def test_qml_hook_excludes_unrelated_heavy_modules() -> None:
    hook = (
        package_windows.PACKAGING_ROOT
        / "hooks"
        / "hook-PySide6.QtQml.py"
    ).read_text(encoding="utf-8")

    assert 'qml_source / "QtQuick" / "Controls"' in hook
    assert 'qml_source / "QtQuick" / "Layouts"' in hook
    assert 'qml_source / "QtQuick3D"' not in hook
    assert 'qml_source / "QtWebEngine"' not in hook
