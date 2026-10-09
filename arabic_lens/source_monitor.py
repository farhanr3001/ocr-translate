"""Cheap source-window checks, independent of screenshot/OCR work."""
from PySide6.QtCore import QObject, QTimer, Signal
from .windows import source_window_current


class SourceWindowMonitor(QObject):
    invalidated = Signal(object)
    invalidated_keys = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sources = {}
        self.timer = QTimer(self)
        self.timer.setInterval(75)
        self.timer.timeout.connect(self.check)

    def accept(self, result):
        if not source_window_current(result.source_window):
            return False
        if result.source_window:
            self.sources[result.id] = result.source_window
            self.timer.start()
        return True

    def check(self):
        # Check each window once, even when it has dozens of translated cells.
        for identity in set(self.sources.values()):
            if not source_window_current(identity):
                affected = tuple(key for key, source in self.sources.items() if source == identity)
                self.sources = {k: v for k, v in self.sources.items() if v != identity}
                self.invalidated_keys.emit((identity, affected))
                self.invalidated.emit(identity)
        if not self.sources:
            self.timer.stop()

    def forget(self, key):
        self.sources = {k: v for k, v in self.sources.items() if k != key and not k.startswith(key + ':')}
        if not self.sources:
            self.timer.stop()

    def forget_exact(self, key):
        self.sources.pop(key, None)
        if not self.sources:
            self.timer.stop()

    def clear(self):
        self.sources.clear()
        self.timer.stop()
