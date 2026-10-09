"""Translations stay until their own source is lost or the user dismisses them."""
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from arabic_lens.config import Settings
from arabic_lens.models import Rect, Translation
from arabic_lens.overlay import OverlayInteraction, OverlayManager


def _manager(monkeypatch):
    import arabic_lens.overlay as overlay_module

    qt = QApplication.instance() or QApplication([])
    monkeypatch.setattr(overlay_module, 'exclude_capture', lambda widget: True)
    settings = Settings()
    settings.overlay.fade_ms = 0
    settings.overlay.duration = 1  # The former timeout made translations vanish.
    manager = OverlayManager(settings, lambda message: None)
    return qt, manager


def test_quick_and_watch_translations_survive_former_timeout(monkeypatch):
    qt, manager = _manager(monkeypatch)
    try:
        for key, y in [('manual', 100), ('watch-0-1', 250)]:
            manager.show(Translation(key, 'This stays on screen.', 'يبقى هذا على الشاشة.', Rect(100, y, 300, 50)))
        qt.processEvents()
        assert set(manager.windows) == {'manual', 'watch-0-1'}
        assert all(not overlay.timer.isActive() for overlay in manager.windows.values())
        QTest.qWait(1200)
        qt.processEvents()
        assert all(overlay.isVisible() and not overlay.closing for overlay in manager.windows.values())

        # Losing one watched source does not retire an unrelated translation.
        manager.remove_group('watch-0-1')
        assert 'watch-0-1' not in manager.windows
        assert 'manual' in manager.windows
    finally:
        manager.clear(immediate=True)
        qt.processEvents()


def test_status_notice_still_expires(monkeypatch):
    qt, manager = _manager(monkeypatch)
    try:
        manager.show(Translation('manual-notice', '', 'No text found.', Rect(100, 100, 200, 40), notice=True))
        overlay = manager.windows['manual-notice']
        assert overlay.notice and overlay.timer.isActive()
        assert overlay.timer.interval() == 4000
    finally:
        manager.clear(immediate=True)
        qt.processEvents()


def test_only_held_shortcut_may_operate_overlay_controls(monkeypatch):
    qt, manager = _manager(monkeypatch)
    closed = []
    try:
        manager.show(Translation('manual', 'Source', 'الترجمة', Rect(100, 100, 240, 45)))
        overlay = manager.windows['manual']
        assert overlay.windowFlags() & Qt.WindowTransparentForInput
        assert overlay.testAttribute(Qt.WA_TransparentForMouseEvents)
        control = OverlayInteraction(overlay, lambda: closed.append(True))
        control.follow_overlay()
        monkeypatch.setattr('arabic_lens.windows.modifiers_held', lambda shortcut: False)
        control.show()
        qt.processEvents()
        QTest.mouseClick(control, Qt.LeftButton, pos=control.button_rects()[0].center())
        assert not closed and not control.dragging
        assert overlay.isVisible() and not overlay.closing

        held = [True]
        monkeypatch.setattr('arabic_lens.windows.modifiers_held', lambda shortcut: held[0])
        control.show()
        qt.processEvents()
        original_position = overlay.pos()
        QTest.mousePress(control, Qt.LeftButton, pos=control.rect().bottomLeft())
        held[0] = False
        QTest.mouseMove(control, control.rect().center())
        QTest.mouseRelease(control, Qt.LeftButton)
        assert overlay.pos() == original_position and not control.dragging
        held[0] = True
        control.show()
        qt.processEvents()
        QTest.mouseClick(control, Qt.LeftButton, pos=control.button_rects()[0].center())
        assert closed == [True]
        control.close()
        control.deleteLater()
    finally:
        manager.clear(immediate=True)
        qt.processEvents()
