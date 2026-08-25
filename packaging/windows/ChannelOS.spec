# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


PROJECT_ROOT = Path(SPECPATH).parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
ICON_PATH = PROJECT_ROOT / "packaging" / "windows" / "ChannelOS.ico"

analysis = Analysis(
    [str(PROJECT_ROOT / "packaging" / "windows" / "entrypoint.py")],
    pathex=[str(SOURCE_ROOT)],
    binaries=[],
    datas=collect_data_files("channelos"),
    hiddenimports=[
        "PySide6.QtOpenGL",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickControls2",
        "PySide6.QtSvg",
        "vlc",
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
