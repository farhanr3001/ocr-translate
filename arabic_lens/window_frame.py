"""Native resize hit-testing for the themed, frameless settings window."""
import ctypes
import sys
from ctypes import wintypes


def resize_hit_test(x, y, width, height, border=8, maximized=False):
    """Return Windows HT* codes, prioritizing corners over individual edges."""
    if maximized or not (0 <= x < width and 0 <= y < height):
        return None
    left, right = x < border, x >= width - border
    top, bottom = y < border, y >= height - border
    if top:
        return 13 if left else 14 if right else 12
    if bottom:
        return 16 if left else 17 if right else 15
    return 10 if left else 11 if right else None


def native_resize_hit(window, message):
    if sys.platform != 'win32':
        return None
    msg = wintypes.MSG.from_address(int(message))
    if msg.message == 0x0083 and msg.wParam:  # WM_NCCALCSIZE: keep themed client area
        return 0
    if msg.message != 0x0084:  # WM_NCHITTEST
        return None
    rect = wintypes.RECT()
    user32 = ctypes.windll.user32
    if not user32.GetWindowRect(wintypes.HWND(int(window.winId())), ctypes.byref(rect)):
        return None
    # LPARAM coordinates are signed physical screen pixels (including negative monitors).
    x = ctypes.c_short(msg.lParam & 0xffff).value - rect.left
    y = ctypes.c_short((msg.lParam >> 16) & 0xffff).value - rect.top
    border = max(6, round(8 * window.devicePixelRatioF()))
    return resize_hit_test(x, y, rect.right - rect.left, rect.bottom - rect.top,
                           border, window.isMaximized() or window.isFullScreen())


def enable_native_resize(window):
    if sys.platform != 'win32':
        return
    user32 = ctypes.windll.user32
    hwnd = wintypes.HWND(int(window.winId()))
    style = user32.GetWindowLongW(hwnd, -16)
    if not style & 0x00040000:  # WS_THICKFRAME enables Windows' resize loop
        user32.SetWindowLongW(hwnd, -16, style | 0x00040000)
        user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0037)
