"""Read-only source preflight, before any index mutation is authorized."""
from pathlib import Path
from PySide6.QtCore import QObject, Signal, Slot
from .scanner import MediaScanner, ScanCancelled
from .probe import NullMediaProbe


class SourcePreflightWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    finished = Signal()

    def __init__(self, library, source, cancellation):
        super().__init__()
        self.library, self.source, self.cancellation = library, source, cancellation

    @Slot()
    def run(self):
        try:
            source = Path(self.source).expanduser().resolve(strict=False)
            paths = MediaScanner(self.library, NullMediaProbe()).discover(source, should_cancel=self.cancellation.is_set)
            _, key = self.library.storage_path(source)
            already = any(item.source_root_key == key for item in self.library.list_sources())
            if self.cancellation.is_set():
                raise ScanCancelled('Source check cancelled')
            self.completed.emit({'ok':True,'path':str(source),'name':source.name or str(source),
                'supportedCount':len(paths),'alreadyIndexed':already,
                'message':f'Found {len(paths)} supported media file(s) in {source}'})
        except ScanCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()
