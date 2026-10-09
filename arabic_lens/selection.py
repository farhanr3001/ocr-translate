from PySide6.QtCore import Qt, QRect, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QCursor
from PySide6.QtWidgets import QWidget, QApplication
from .models import Rect
from .overlay import logical_to_physical, physical_to_logical
from .windows import exclude_capture


class SelectionWindow(QWidget):
    selected = Signal(object)
    cancelled = Signal()
    finished = Signal()

    def __init__(self, screen, localization):
        super().__init__()
        self.screen, self.localization = screen, localization
        self.anchor = self.current = None
        self.multi = False
        self.areas = []
        self.setup_label = ''
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(screen.geometry())
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)
        exclude_capture(self)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.multi and self.done_rect().contains(event.position().toPoint()):
                self.finished.emit(); return
            if self.multi and self.cancel_rect().contains(event.position().toPoint()):
                self.cancelled.emit(); return
            self.anchor = self.current = event.position().toPoint()
            self.grabMouse()
            self.update()
        elif event.button() == Qt.RightButton:
            self.cancelled.emit()

    def mouseMoveEvent(self, event):
        if self.anchor is not None:
            self.current = event.position().toPoint()
            self.update()
        elif self.multi:
            self.update_cursor(event.position().toPoint())

    def update_cursor(self, point):
        over_controls = self.done_rect().contains(point) or self.cancel_rect().contains(point)
        self.setCursor(Qt.PointingHandCursor if over_controls else Qt.CrossCursor)

    def showEvent(self, event):
        super().showEvent(event)
        if self.multi:
            self.update_cursor(self.mapFromGlobal(QCursor.pos()))

    def mouseReleaseEvent(self, event):
        if self.anchor is None or event.button() != Qt.LeftButton:
            return
        self.releaseMouse()
        selection = QRect(self.anchor, event.position().toPoint()).normalized().intersected(self.rect())
        if selection.width() < 8 or selection.height() < 8:
            if not self.multi:
                self.cancelled.emit()
            return
        global_pos = self.mapToGlobal(selection.topLeft())
        self.anchor = self.current = None
        self.selected.emit(logical_to_physical(self.screen, Rect(global_pos.x(), global_pos.y(), selection.width(), selection.height())))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.cancelled.emit()
        elif self.multi and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.finished.emit()

    def done_rect(self):
        return QRect(self.width() // 2 - 40, 17, 36, 36)

    def cancel_rect(self):
        return QRect(self.width() // 2 + 4, 17, 36, 36)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(6, 12, 19, 92))
        if self.multi:
            for index, area in enumerate(self.areas, 1):
                screen, logical = physical_to_logical(area)
                if screen is not self.screen:
                    continue
                box = QRect(logical.x - self.x(), logical.y - self.y(), logical.w, logical.h)
                p.setCompositionMode(QPainter.CompositionMode_Clear)
                p.fillRect(box, Qt.transparent)
                p.setCompositionMode(QPainter.CompositionMode_SourceOver)
                p.setPen(QPen(QColor('#9cedb5'), 2))
                p.drawRoundedRect(box, 5, 5)
                p.setBrush(QColor('#246447'))
                p.drawRoundedRect(QRect(box.x(), box.y(), 28, 25), 5, 5)
                p.setPen(QColor('white'))
                p.drawText(QRect(box.x(), box.y(), 28, 25), Qt.AlignCenter, str(index))
                p.setBrush(Qt.NoBrush)
        if self.anchor is not None:
            r = QRect(self.anchor, self.current).normalized()
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.fillRect(r, Qt.transparent)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            p.setPen(QPen(QColor("#6ce5c5"), 1.5))
            p.drawRect(r)
        p.setPen(QColor("#eef8f5"))
        p.setFont(QFont("Segoe UI", 12))
        if self.multi:
            p.setPen(QPen(QColor('#91a99a'), 1))
            p.setBrush(QColor(232, 243, 231, 235))
            p.drawRoundedRect(QRect(self.width() // 2 - 48, 9, 96, 52), 15, 15)
            for rect, symbol, color in ((self.done_rect(), '✓', '#317e59'), (self.cancel_rect(), '×', '#a54d48')):
                p.setBrush(QColor(color)); p.setPen(Qt.NoPen); p.drawEllipse(rect)
                p.setPen(QColor('white')); p.setFont(QFont('Segoe UI', 20, QFont.Bold))
                p.drawText(rect, Qt.AlignCenter, symbol)
        else:
            p.drawText(QRect(0, 36, self.width(), 40), Qt.AlignCenter, self.localization.t("Drag around English text · Esc to cancel"))


class SelectionManager:
    def __init__(self, localization, callback, before_finish=None, on_cancel=None):
        self.localization, self.callback = localization, callback
        self.before_finish = before_finish
        self.on_cancel = on_cancel
        self.windows = []
        self.mode = 'single'
        self.areas = []
        self.multi_finished = None
        self.multi_cancelled = None

    def begin(self):
        if self.windows:
            self.cancel()
            return
        for screen in QApplication.screens():
            window = SelectionWindow(screen, self.localization)
            window.multi = self.mode == 'multi'
            window.areas = self.areas
            window.setup_label = getattr(self, 'setup_label', '')
            window.selected.connect(self.add_area if window.multi else self.finish)
            window.cancelled.connect(self.cancel)
            window.finished.connect(self.finish_multi)
            self.windows.append(window)
            window.show()
        if self.windows:
            from PySide6.QtGui import QCursor
            focused = next((w for w in self.windows if w.geometry().contains(QCursor.pos())), self.windows[0])
            focused.activateWindow()
            focused.setFocus()

    def cancel(self, cancelled=True):
        for window in self.windows:
            window.releaseMouse()
            window.hide()
            window.close()
            window.deleteLater()
        self.windows.clear()
        if cancelled:
            if self.mode == 'multi' and self.multi_cancelled:
                self.multi_cancelled()
            elif self.on_cancel:
                self.on_cancel()
        self.mode = 'single'

    def begin_multi(self, areas, on_finish, on_cancel, label='Watch area setup'):
        if self.windows:
            return
        self.mode = 'multi'
        self.areas = list(areas)
        self.multi_finished = on_finish
        self.multi_cancelled = on_cancel
        self.setup_label = label
        self.begin()

    def add_area(self, area):
        if any(existing.overlap(area) > .8 for existing in self.areas):
            return
        if len(self.areas) >= 12:
            return
        self.areas.append(area)
        for window in self.windows:
            window.update()

    def finish_multi(self):
        if not self.areas:
            return
        if self.before_finish:
            self.before_finish()
        result = self.areas.copy()
        callback = self.multi_finished
        self.cancel(False)
        callback(result)

    def finish(self, rect):
        if self.before_finish:
            self.before_finish()
        self.cancel(False)
        self.callback(rect)
