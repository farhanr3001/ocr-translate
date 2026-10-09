import pytest
from arabic_lens.window_frame import resize_hit_test


@pytest.mark.parametrize('x,y,expected', [
    (0, 0, 13), (1199, 0, 14), (0, 799, 16), (1199, 799, 17),
    (600, 0, 12), (600, 799, 15), (0, 400, 10), (1199, 400, 11),
    (600, 24, None), (1160, 24, None), (600, 400, None),
    (-1, 10, None), (1200, 10, None),
])
def test_all_edges_and_corners_leave_title_controls_and_content_alone(x, y, expected):
    assert resize_hit_test(x, y, 1200, 800) == expected


def test_maximized_and_scaled_resize_border():
    assert resize_hit_test(0, 0, 1200, 800, maximized=True) is None
    assert resize_hit_test(10, 10, 1800, 1200, border=12) == 13
    assert resize_hit_test(12, 12, 1800, 1200, border=12) is None

def test_real_windows_native_hit_testing(tmp_path):
    import ctypes
    from ctypes import wintypes
    from PySide6.QtWidgets import QApplication
    from arabic_lens.config import Settings
    from arabic_lens.localization import LocalizationService
    from arabic_lens.storage import TranslationStore
    from arabic_lens.ui import SettingsWindow
    qt = QApplication.instance() or QApplication([])
    settings = Settings()
    store = TranslationStore(tmp_path / 'frame.db', settings)
    window = SettingsWindow(settings, LocalizationService(settings), store)
    window.show()
    qt.processEvents()
    hwnd = wintypes.HWND(int(window.winId()))
    rect = wintypes.RECT()
    user32 = ctypes.windll.user32
    assert user32.GetWindowLongW(hwnd, -16) & 0x00040000
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    try:
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width, height = rect.right - rect.left, rect.bottom - rect.top
        for x, y, expected in [(1,1,13),(width-2,1,14),(width//2,1,12),
                                (1,height//2,10),(width-2,height//2,11),
                                (1,height-2,16),(width-2,height-2,17),(width//2,height-2,15)]:
            param = ((rect.top+y) & 0xffff) << 16 | ((rect.left+x) & 0xffff)
            assert user32.SendMessageW(hwnd, 0x84, 0, param) == expected
        window.showMaximized()
        qt.processEvents()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        param = ((rect.top+1) & 0xffff) << 16 | ((rect.left+1) & 0xffff)
        assert user32.SendMessageW(hwnd, 0x84, 0, param) not in range(10,18)
    finally:
        window.hide()
        window.deleteLater()
        qt.processEvents()
        store.close()
