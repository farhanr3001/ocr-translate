from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from arabic_lens.config import Settings
from arabic_lens.models import Translation, Rect
from arabic_lens.overlay import OverlayManager


def test_hold_drag_collapse_expand_and_individual_close(monkeypatch):
    qt = QApplication.instance() or QApplication([])
    settings = Settings()
    settings.overlay.fade_ms = 0
    manager = OverlayManager(settings, lambda error: None)
    one = Translation('watch-1', 'You need the key.', 'عليك العثور على المفتاح.', Rect(100, 100, 360, 60))
    two = Translation('watch-1:1', 'Finish Dress', 'إنهاء الفستان', Rect(100, 300, 180, 30))
    manager.show(one)
    manager.show(two)
    qt.processEvents()
    overlay = manager.windows[one.id]
    assert overlay.geometry().contains(QPoint(100, 100))
    assert overlay.geometry().contains(QPoint(459, 159))
    assert overlay.windowFlags() & Qt.WindowTransparentForInput
    hold = [False]
    monkeypatch.setattr('arabic_lens.windows.modifiers_held', lambda shortcut: hold[0])
    monkeypatch.setattr(QCursor, 'pos', staticmethod(lambda: overlay.geometry().center()))
    manager.update_interaction()
    assert not manager.controls
    hold[0] = True
    manager.update_interaction()
    control = manager.controls[one.id]
    original = overlay.pos()
    QTest.mousePress(control, Qt.LeftButton, pos=QPoint(12, 12))
    QTest.mouseMove(control, QPoint(42, 32))
    QTest.mouseRelease(control, Qt.LeftButton, pos=QPoint(42, 32))
    assert overlay.pos() != original
    full_size = overlay.size()
    QTest.mouseClick(control, Qt.LeftButton, pos=control.button_rects()[1].center())
    assert overlay.collapsed and overlay.width() == 76
    QTest.mouseClick(control, Qt.LeftButton, pos=control.button_rects()[1].center())
    assert not overlay.collapsed and overlay.size() == full_size
    font_size = overlay.document.defaultFont().pixelSize()
    QTest.mouseClick(control, Qt.LeftButton, pos=control.button_rects()[2].center())
    assert overlay.document.defaultFont().pixelSize() == font_size + 2
    QTest.mouseClick(control, Qt.LeftButton, pos=control.button_rects()[3].center())
    assert overlay.document.defaultFont().pixelSize() == font_size
    assert manager.windows[two.id].document.defaultFont().pixelSize() != font_size + 2
    class Clipboard:
        text = ''
        def setText(self, value):
            self.text = value
    clipboard = Clipboard()
    monkeypatch.setattr(QApplication, 'clipboard', staticmethod(lambda: clipboard))
    before_copy = overlay.geometry()
    QTest.mouseClick(control, Qt.LeftButton, pos=control.button_rects()[4].center())
    assert clipboard.text == one.arabic
    assert overlay.geometry() == before_copy and not control.dragging
    assert control.copied and len(manager.windows) == 2
    control.reset_copy_feedback()
    assert not control.copied
    QTest.mouseClick(control, Qt.LeftButton, pos=control.button_rects()[1].center())
    QTest.mouseClick(control, Qt.LeftButton, pos=control.button_rects()[4].center())
    assert overlay.collapsed and clipboard.text == one.arabic
    QTest.mouseClick(control, Qt.LeftButton, pos=control.button_rects()[1].center())
    hold[0] = False
    manager.update_interaction()
    assert not control.isVisible()
    hold[0] = True
    manager.update_interaction()
    QTest.mouseClick(control, Qt.LeftButton, pos=control.button_rects()[0].center())
    assert one.id not in manager.windows and two.id in manager.windows
    manager.show(one)
    assert one.id not in manager.windows  # Stays dismissed until the source changes.
    manager.remove_group('watch-1')
    assert not manager.windows and not manager.dismissed
    manager.clear()
    qt.processEvents()
