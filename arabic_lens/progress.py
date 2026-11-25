"""Optional capture-excluded, non-interactive translation coverage display."""
from PySide6.QtCore import Qt, QRect, QTimer
from PySide6.QtGui import QPainter, QColor, QFont, QPen
from PySide6.QtWidgets import QWidget
from .overlay import physical_to_logical
from .windows import exclude_capture, source_window_current


class ProgressSurface(QWidget):
    def __init__(self, screen):
        super().__init__()
        self.items = []
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                            Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setGeometry(screen.geometry())
        exclude_capture(self)

    def paintEvent(self, event):
        p = QPainter(self)
        font = QFont('Segoe UI'); font.setPixelSize(11); p.setFont(font)
        for area, percent, stage in self.items:
            failed = stage in ('Retrying','Unavailable','إعادة المحاولة','تعذرت الترجمة')
            color = QColor('#f0b768' if failed else '#63d6b0' if percent == 100 else '#41d9e8')
            rect = QRect(area.x-self.x(),area.y-self.y(),area.w,area.h)
            p.setPen(QPen(color, 1.5)); p.setBrush(Qt.NoBrush)
            p.drawRect(rect)
            # Keep badges short enough for adjacent menu labels. The Settings
            # legend explains stages; no broad label obscures neighbouring text.
            label = ('! ' if failed else '') + f'{percent}%'
            width = p.fontMetrics().horizontalAdvance(label)+12
            badge = QRect(max(0,min(rect.x(),self.width()-width)),max(0,rect.y()-19),width,18)
            p.fillRect(badge,QColor('#142b29')); p.setPen(color)
            p.drawText(badge,Qt.AlignCenter,label)


class TranslationProgress:
    def __init__(self, settings, localization):
        self.settings, self.localization = settings, localization
        self.entries, self.windows = {}, {}
        # Coalesce bursts from dense OCR into one paint without blocking input.
        self.timer = QTimer(); self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.render)
        self.source_timer = QTimer(); self.source_timer.setInterval(200)
        self.source_timer.timeout.connect(self.check_sources)

    def update(self, info):
        if not self.settings.show_translation_boxes:
            self.clear(); return
        key = info['id']
        if info.get('removed'):
            self.remove(key); return
        self.entries[key] = info
        if not self.source_timer.isActive(): self.source_timer.start()
        self.schedule()

    def schedule(self):
        if not self.timer.isActive(): self.timer.start(30)

    def remove(self, key):
        for existing in list(self.entries):
            if existing == key or existing.startswith(key+':'):
                self.entries.pop(existing, None)
        self.schedule()

    def move(self, key, rect):
        if key in self.entries:
            self.entries[key] = {**self.entries[key], 'rect':rect}
            self.schedule()

    def complete(self, result):
        if not result.notice:
            self.update({'id':result.id,'rect':result.rect,'percent':100,'stage':'Ready','source_window':result.source_window})

    def check_sources(self):
        sources = {entry.get('source_window') for entry in self.entries.values() if entry.get('source_window')}
        invalid = {source for source in sources if not source_window_current(source)}
        for key, entry in list(self.entries.items()):
            if entry.get('source_window') in invalid:
                self.remove(key)
        if not self.entries: self.source_timer.stop()

    def clear(self):
        self.timer.stop(); self.source_timer.stop(); self.entries.clear()
        for window in self.windows.values():
            window.close(); window.deleteLater()
        self.windows.clear()

    def render(self):
        if not self.settings.show_translation_boxes:
            self.clear(); return
        grouped = {}
        for entry in self.entries.values():
            screen, logical = physical_to_logical(entry['rect'])
            grouped.setdefault(screen, []).append((logical,entry['percent'],self.localization.t(entry['stage'])))
        for screen in list(self.windows):
            if screen not in grouped:
                window = self.windows.pop(screen); window.close(); window.deleteLater()
        for screen, items in grouped.items():
            if screen not in self.windows:
                self.windows[screen] = ProgressSurface(screen)
            window = self.windows[screen]; window.items = items
            window.show(); window.update()
