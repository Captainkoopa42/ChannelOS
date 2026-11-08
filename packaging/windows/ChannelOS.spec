# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


PROJECT_ROOT = Path(SPECPATH).parents[1]


def sdl_binaries():
    """Only SDL2.dll from pysdl2-dll (game controllers), not its image/audio/font libraries."""
    try:
        import sdl2dll
    except ImportError:
        return []
    library = Path(sdl2dll.get_dllpath()) / "SDL2.dll"
    return [(str(library), "sdl2dll/dll")] if library.is_file() else []
SOURCE_ROOT = PROJECT_ROOT / "src"
ICON_PATH = PROJECT_ROOT / "packaging" / "windows" / "ChannelOS.ico"

analysis = Analysis(
    [str(PROJECT_ROOT / "packaging" / "windows" / "entrypoint.py")],
    pathex=[str(SOURCE_ROOT)],
    binaries=sdl_binaries(),
    datas=collect_data_files("channelos") + collect_data_files("tzdata"),
    hiddenimports=[
        "PySide6.QtOpenGL",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickControls2",
        "PySide6.QtSvg",
        "vlc",
        "sdl2",
        "sdl2dll",
        "tzdata.zoneinfo",
    ],
    hookspath=[str(PROJECT_ROOT / "packaging" / "windows" / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="ChannelOS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    contents_directory="_internal",
    icon=str(ICON_PATH),
)

bundle = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ChannelOS",
)
