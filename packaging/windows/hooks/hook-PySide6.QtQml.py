"""Collect only the QML modules ChannelOS imports.

PyInstaller's general QtQml hook intentionally collects the entire QML tree.
That includes large unrelated modules such as WebEngine and Quick3D. ChannelOS
uses QtQuick, Controls, and Layouts, so the pinned package build narrows the
payload to those module trees and their native dependencies.
"""

from pathlib import Path, PurePath

from PyInstaller.utils.hooks.qt import add_qt6_dependencies, pyside6_library_info


hiddenimports, binaries, datas = add_qt6_dependencies(__file__)

qml_source = Path(pyside6_library_info.location["QmlImportsPath"]).resolve()
qml_destination = PurePath(pyside6_library_info.qt_rel_dir) / "qml"
module_roots = (
    qml_source / "QtQml",
    qml_source / "QtQuick" / "Controls",
    qml_source / "QtQuick" / "Layouts",
    qml_source / "QtQuick" / "Templates",
    qml_source / "QtQuick" / "Window",
)
module_files = (qml_source / "QtQuick" / "qmldir",)


def destination(source: Path) -> str:
    relative = source.relative_to(qml_source)
    if source.is_file():
        relative = relative.parent
    return str(qml_destination / relative)


qmldir_files = list(module_files)
for module_root in module_roots:
    qmldir_files.extend(module_root.rglob("qmldir"))

for qmldir in sorted(set(qmldir_files)):
    plugin_binaries, plugin_datas = pyside6_library_info._process_qml_plugin(qmldir)
    binaries += [(str(source), destination(source)) for source in plugin_binaries]
    datas += [(str(source), destination(source)) for source in plugin_datas]
