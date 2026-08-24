from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from xml.etree import ElementTree


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGING_ROOT = PROJECT_ROOT / "packaging" / "windows"
RUNTIME_LOCK_PATH = PACKAGING_ROOT / "runtime-lock.json"
SPEC_PATH = PACKAGING_ROOT / "ChannelOS.spec"
REQUIRED_VLC_FILES = ("libvlc.dll", "libvlccore.dll")
PACKAGE_LICENSE_DOCUMENTS = (
    "LICENSE.md",
    "THIRD_PARTY_NOTICES.md",
    "ACKNOWLEDGMENTS.md",
    "docs/DISTRIBUTION.md",
)
PYTHON_COMPONENTS = (
    "channelos",
    "PyInstaller",
    "PySide6",
    "PySide6_Essentials",
    "PySide6_Addons",
    "shiboken6",
    "PyYAML",
    "python-vlc",
)
EFFECTIVE_LICENSES = {
    "channelos": "MPL-2.0",
    "pyinstaller": "GPL-2.0-or-later WITH PyInstaller-Bootloader-exception",
    "pyside6": "LGPL-3.0-only",
    "pyside6_essentials": "LGPL-3.0-only",
    "pyside6_addons": "LGPL-3.0-only",
    "shiboken6": "LGPL-3.0-only",
    "pyyaml": "MIT",
    "python-vlc": "LGPL-2.1-or-later",
}
PROJECT_URLS = {
    "channelos": "https://github.com/Captainkoopa42/ChannelOS",
    "pyinstaller": "https://pyinstaller.org/",
    "pyside6": "https://www.qt.io/qt-for-python",
    "pyside6_essentials": "https://www.qt.io/qt-for-python",
    "pyside6_addons": "https://www.qt.io/qt-for-python",
    "shiboken6": "https://www.qt.io/qt-for-python",
    "pyyaml": "https://pyyaml.org/",
    "python-vlc": "https://wiki.videolan.org/PythonBinding",
}


class PackageError(RuntimeError):
    """Raised when a Windows package cannot be built or audited safely."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_runtime_lock(path: Path = RUNTIME_LOCK_PATH) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "component",
        "version",
        "architecture",
        "source_prefix",
        "download_url",
        "sha256",
        "license",
        "project_url",
        "corresponding_source",
    }
    missing = sorted(required - set(data))
    if missing:
        raise PackageError(f"runtime lock is missing: {', '.join(missing)}")
    if data["component"] != "VideoLAN.LibVLC.Windows":
        raise PackageError("only the audited LGPL VideoLAN.LibVLC.Windows package is allowed")
    if data["license"] != "LGPL-2.1-or-later":
        raise PackageError("the locked libVLC package must be LGPL-2.1-or-later")
    if "gpl" in data["download_url"].lower():
        raise PackageError("the GPL companion libVLC package is forbidden")
    return data


def download_locked_runtime(lock: dict[str, Any], cache_directory: Path) -> Path:
    cache_directory.mkdir(parents=True, exist_ok=True)
    destination = cache_directory / (
        f"{lock['component']}.{lock['version']}.nupkg"
    )
    if destination.is_file() and sha256_file(destination) == lock["sha256"]:
        return destination

    temporary = destination.with_suffix(".download")
    temporary.unlink(missing_ok=True)
    try:
        with urllib.request.urlopen(lock["download_url"], timeout=120) as response:
            with temporary.open("wb") as output:
                shutil.copyfileobj(response, output)
        actual = sha256_file(temporary)
        if actual != lock["sha256"]:
            raise PackageError(
                "libVLC download hash mismatch: "
                f"expected {lock['sha256']}, received {actual}"
            )
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _safe_member(name: str) -> PurePosixPath:
    member = PurePosixPath(name)
    if member.is_absolute() or ".." in member.parts:
        raise PackageError(f"unsafe path in runtime package: {name}")
    return member


def _nuspec_metadata(archive: zipfile.ZipFile) -> tuple[str, str, str]:
    names = [name for name in archive.namelist() if name.lower().endswith(".nuspec")]
    if len(names) != 1:
        raise PackageError("libVLC package must contain exactly one NuSpec file")
    root = ElementTree.fromstring(archive.read(names[0]))
    namespace = {"n": "http://schemas.microsoft.com/packaging/2011/08/nuspec.xsd"}

    def value(tag: str) -> str:
        element = root.find(f".//n:{tag}", namespace)
        return "" if element is None or element.text is None else element.text.strip()

    return value("id"), value("version"), value("license")


def stage_vlc_runtime(nupkg: Path, destination: Path, lock: dict[str, Any]) -> list[str]:
    actual_hash = sha256_file(nupkg)
    if actual_hash != lock["sha256"]:
        raise PackageError(
            f"runtime archive hash mismatch: expected {lock['sha256']}, received {actual_hash}"
        )

    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    prefix = str(lock["source_prefix"])
    copied: list[str] = []
    with zipfile.ZipFile(nupkg) as archive:
        package_id, version, license_expression = _nuspec_metadata(archive)
        if (package_id, version, license_expression) != (
            lock["component"],
            lock["version"],
            lock["license"],
        ):
            raise PackageError(
                "runtime NuSpec does not match the approved component, version, and license"
            )

        for raw_name in archive.namelist():
            member = _safe_member(raw_name)
            name = member.as_posix()
            if not name.startswith(prefix) or name.endswith("/"):
                continue
            relative = PurePosixPath(name[len(prefix) :])
            allowed = (
                len(relative.parts) == 1 and relative.name in REQUIRED_VLC_FILES
            ) or (relative.parts and relative.parts[0] == "plugins")
            if not allowed:
                continue
            if relative.suffix.lower() in {".lib", ".exp", ".pdb"}:
                continue

            output = destination.joinpath(*relative.parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(raw_name) as source, output.open("wb") as target:
                shutil.copyfileobj(source, target)
            copied.append(relative.as_posix())

    for filename in REQUIRED_VLC_FILES:
        if not (destination / filename).is_file():
            raise PackageError(f"approved runtime did not contain {filename}")
    if len([name for name in copied if name.startswith("plugins/")]) < 100:
        raise PackageError("approved runtime contains an unexpectedly small plugin inventory")
    return sorted(copied)


def _distribution_record(name: str) -> dict[str, Any]:
    distribution = importlib.metadata.distribution(name)
    metadata = distribution.metadata
    normalized = name.lower()
    return {
        "name": metadata.get("Name", name),
        "version": distribution.version,
        "declared_license": metadata.get("License-Expression") or metadata.get("License") or "SEE-LICENSE-FILES",
        "effective_package_license": EFFECTIVE_LICENSES[normalized],
        "project_url": metadata.get("Home-page") or PROJECT_URLS[normalized],
    }


def collect_python_licenses(destination: Path) -> list[str]:
    """Copy license material shipped in the exact build environment."""

    copied: list[str] = []
    for name in PYTHON_COMPONENTS:
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise PackageError(f"required build distribution is missing: {name}") from exc

        component_dir = destination / name
        for relative in distribution.files or ():
            lowered = str(relative).lower()
            if not any(token in lowered for token in ("license", "copying", "notice")):
                continue
            source = Path(distribution.locate_file(relative))
            if not source.is_file():
                continue
            output = component_dir / Path(str(relative)).name
            output.parent.mkdir(parents=True, exist_ok=True)
            if output.exists() and sha256_file(output) == sha256_file(source):
                continue
            shutil.copy2(source, output)
            copied.append(output.relative_to(destination).as_posix())
    return sorted(set(copied))


def copy_release_documents(package_root: Path) -> None:
    licenses = package_root / "licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    for relative in PACKAGE_LICENSE_DOCUMENTS:
        source = PROJECT_ROOT / relative
        output = licenses / Path(relative).name
        shutil.copy2(source, output)

    for filename in ("LGPL-2.1.txt", "LGPL-3.0.txt", "PYTHON.txt"):
        shutil.copy2(PACKAGING_ROOT / "licenses" / filename, licenses / filename)
    shutil.copy2(PACKAGING_ROOT / "README-WINDOWS.txt", package_root / "README-WINDOWS.txt")
    shutil.copy2(
        PACKAGING_ROOT / "REPLACING-LGPL-LIBRARIES.md",
        licenses / "REPLACING-LGPL-LIBRARIES.md",
    )


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def file_inventory(package_root: Path, *, excluded: Iterable[str] = ()) -> list[dict[str, Any]]:
    excluded_set = set(excluded)
    inventory: list[dict[str, Any]] = []
    for path in sorted(item for item in package_root.rglob("*") if item.is_file()):
        relative = path.relative_to(package_root).as_posix()
        if relative in excluded_set:
            continue
        inventory.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return inventory


def write_bom(
    package_root: Path,
    lock: dict[str, Any],
    nupkg: Path,
    vlc_inventory: list[str],
) -> Path:
    component_records = []
    for name in PYTHON_COMPONENTS:
        try:
            component_records.append(_distribution_record(name))
        except importlib.metadata.PackageNotFoundError as exc:
            raise PackageError(f"cannot freeze missing component in BOM: {name}") from exc

    bom_path = package_root / "PACKAGE-BOM.json"
    payload = {
        "schema_version": 1,
        "product": {
            "name": "ChannelOS",
            "version": importlib.metadata.version("channelos"),
            "git_commit": _git_commit(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "architecture": platform.machine(),
            "built_at_utc": datetime.now(UTC).isoformat(),
            "license": "MPL-2.0",
        },
        "downloaded_artifacts": [
            {
                **lock,
                "filename": nupkg.name,
                "verified_sha256": sha256_file(nupkg),
            }
        ],
        "python_distributions": component_records,
        "python_runtime": {
            "version": platform.python_version(),
            "license": "PSF-2.0",
            "source": "https://www.python.org/downloads/source/",
        },
        "vlc_runtime_files": vlc_inventory,
        "inventory_excludes": ["PACKAGE-BOM.json"],
        "files": file_inventory(package_root, excluded=("PACKAGE-BOM.json",)),
    }
    bom_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return bom_path


def validate_package_root(package_root: Path) -> None:
    required = (
        package_root / "ChannelOS.exe",
        package_root / "runtime" / "vlc" / "libvlc.dll",
        package_root / "runtime" / "vlc" / "libvlccore.dll",
        package_root / "runtime" / "vlc" / "plugins",
        package_root / "licenses" / "LICENSE.md",
        package_root / "licenses" / "THIRD_PARTY_NOTICES.md",
        package_root / "licenses" / "DISTRIBUTION.md",
        package_root / "licenses" / "LGPL-2.1.txt",
        package_root / "licenses" / "LGPL-3.0.txt",
        package_root / "licenses" / "PYTHON.txt",
        package_root / "licenses" / "REPLACING-LGPL-LIBRARIES.md",
        package_root / "PACKAGE-BOM.json",
    )
    missing = [str(path.relative_to(package_root)) for path in required if not path.exists()]
    if missing:
        raise PackageError(f"package is incomplete: {', '.join(missing)}")

    forbidden = [
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("*")
        if path.is_file()
        and (
            path.suffix.lower() in {".lib", ".exp"}
            or "libvlc.windows.gpl" in path.name.lower()
        )
    ]
    if forbidden:
        raise PackageError(f"forbidden package files found: {', '.join(forbidden)}")

    bom = json.loads((package_root / "PACKAGE-BOM.json").read_text(encoding="utf-8"))
    expected = {item["path"]: item for item in bom["files"]}
    actual = {
        item["path"]: item
        for item in file_inventory(package_root, excluded=("PACKAGE-BOM.json",))
    }
    if expected != actual:
        raise PackageError("package files do not match the frozen BOM")


def run_pyinstaller(output_directory: Path, work_directory: Path) -> Path:
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(output_directory),
        "--workpath",
        str(work_directory),
        str(SPEC_PATH),
    ]
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)
    built = output_directory / "ChannelOS"
    if not (built / "ChannelOS.exe").is_file():
        raise PackageError("PyInstaller did not produce ChannelOS.exe")
    return built


def run_packaged_qml_smoke_test(package_root: Path, build_root: Path) -> None:
    smoke_data = build_root / "smoke-data"
    if smoke_data.exists():
        shutil.rmtree(smoke_data)
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["CHANNELOS_DATA_DIR"] = str(smoke_data)
    try:
        subprocess.run(
            [str(package_root / "ChannelOS.exe"), "--package-smoke-test"],
            cwd=package_root,
            env=environment,
            timeout=60,
            check=True,
        )
    finally:
        if smoke_data.exists():
            shutil.rmtree(smoke_data)


def build_package(output_directory: Path, supplied_nupkg: Path | None = None) -> Path:
    if os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise PackageError("the Windows x64 package must be built on 64-bit Windows")

    lock = load_runtime_lock()
    build_root = PROJECT_ROOT / "build" / "windows"
    pyinstaller_dist = build_root / "pyinstaller-dist"
    pyinstaller_work = build_root / "pyinstaller-work"
    cache = build_root / "cache"
    package_root = output_directory / "ChannelOS"

    output_directory.mkdir(parents=True, exist_ok=True)
    if pyinstaller_dist.exists():
        shutil.rmtree(pyinstaller_dist)
    if pyinstaller_work.exists():
        shutil.rmtree(pyinstaller_work)
    if package_root.exists():
        shutil.rmtree(package_root)

    nupkg = supplied_nupkg or download_locked_runtime(lock, cache)
    built = run_pyinstaller(pyinstaller_dist, pyinstaller_work)
    shutil.copytree(built, package_root)

    vlc_inventory = stage_vlc_runtime(
        nupkg,
        package_root / "runtime" / "vlc",
        lock,
    )
    run_packaged_qml_smoke_test(package_root, build_root)
    copy_release_documents(package_root)
    collect_python_licenses(package_root / "licenses" / "python")
    write_bom(package_root, lock, nupkg, vlc_inventory)
    validate_package_root(package_root)

    archive_base = output_directory / "ChannelOS-0.0.2-windows-x64"
    archive = Path(shutil.make_archive(str(archive_base), "zip", output_directory, "ChannelOS"))
    return archive


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and audit the ChannelOS Windows x64 package.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "dist" / "windows",
        help="directory for the staged package and ZIP archive",
    )
    parser.add_argument(
        "--vlc-nupkg",
        type=Path,
        help="optional pre-downloaded locked VideoLAN.LibVLC.Windows package",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        archive = build_package(args.output_dir.resolve(), args.vlc_nupkg)
    except (PackageError, OSError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Windows package ready: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
