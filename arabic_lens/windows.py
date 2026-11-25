"""Win32 desktop facilities only: no game handles, hooks, or process memory."""
import ctypes as C
from ctypes import wintypes as W
import os
import sys
import winreg
import numpy as np
from .models import Rect

user32 = C.WinDLL("user32", use_last_error=True)
gdi32 = C.WinDLL("gdi32", use_last_error=True)
user32.GetForegroundWindow.restype = W.HWND
user32.WindowFromPoint.argtypes = [W.POINT]
user32.WindowFromPoint.restype = W.HWND
user32.GetAncestor.argtypes = [W.HWND, W.UINT]
user32.GetAncestor.restype = W.HWND
user32.GetClassNameW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
user32.SetForegroundWindow.argtypes = [W.HWND]
user32.ShowWindow.argtypes = [W.HWND, C.c_int]
user32.ShowWindow.restype = W.BOOL
user32.BringWindowToTop.argtypes = [W.HWND]
for name in ('IsWindow', 'IsWindowVisible', 'IsIconic'):
    getattr(user32, name).argtypes = [W.HWND]
user32.GetDC.argtypes = [W.HWND]
user32.GetDC.restype = W.HDC
user32.ReleaseDC.argtypes = [W.HWND, W.HDC]
user32.GetWindowRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
user32.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
user32.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
user32.MonitorFromWindow.argtypes = [W.HWND, W.DWORD]
user32.MonitorFromWindow.restype = W.HANDLE
user32.GetMonitorInfoW.argtypes = [W.HANDLE, C.c_void_p]
user32.SetWindowDisplayAffinity.argtypes = [W.HWND, W.DWORD]
user32.RegisterHotKey.argtypes = [W.HWND, C.c_int, W.UINT, W.UINT]
user32.UnregisterHotKey.argtypes = [W.HWND, C.c_int]
user32.GetAsyncKeyState.argtypes = [C.c_int]
user32.GetAsyncKeyState.restype = C.c_short


def modifiers_held(combination):
    keys = {'Ctrl': 0x11, 'Alt': 0x12, 'Shift': 0x10}
    parts = combination.split('+')
    return len(parts) >= 2 and all(part in keys and bool(user32.GetAsyncKeyState(keys[part]) & 0x8000) for part in parts)
gdi32.CreateCompatibleDC.argtypes = [W.HDC]
gdi32.CreateCompatibleDC.restype = W.HDC
gdi32.SelectObject.argtypes = [W.HDC, W.HGDIOBJ]
gdi32.SelectObject.restype = W.HGDIOBJ
gdi32.DeleteObject.argtypes = [W.HGDIOBJ]
gdi32.DeleteDC.argtypes = [W.HDC]
gdi32.BitBlt.argtypes = [W.HDC, C.c_int, C.c_int, C.c_int, C.c_int, W.HDC, C.c_int, C.c_int, W.DWORD]
gdi32.StretchBlt.argtypes = [W.HDC, C.c_int, C.c_int, C.c_int, C.c_int, W.HDC, C.c_int, C.c_int, C.c_int, C.c_int, W.DWORD]
gdi32.SetStretchBltMode.argtypes = [W.HDC, C.c_int]
gdi32.SetBrushOrgEx.argtypes = [W.HDC, C.c_int, C.c_int, C.c_void_p]
gdi32.CreateDIBSection.argtypes = [W.HDC, C.c_void_p, W.UINT, C.POINTER(C.c_void_p), W.HANDLE, W.DWORD]
gdi32.CreateDIBSection.restype = W.HBITMAP


def enable_dpi():
    try:
        user32.SetProcessDpiAwarenessContext(C.c_void_p(-4))
    except AttributeError:
        user32.SetProcessDPIAware()


class MonitorInfo(C.Structure):
    _fields_ = [("size", W.DWORD), ("monitor", W.RECT), ("work", W.RECT), ("flags", W.DWORD)]


class MonitorInfoEx(C.Structure):
    _fields_ = MonitorInfo._fields_ + [("device", W.WCHAR * 32)]


def physical_monitors():
    found = {}
    callback_type = C.WINFUNCTYPE(W.BOOL, W.HANDLE, W.HDC, C.POINTER(W.RECT), W.LPARAM)
    def visit(handle, dc, rect, param):
        info = MonitorInfoEx()
        info.size = C.sizeof(info)
        if user32.GetMonitorInfoW(handle, C.byref(info)):
            r = info.monitor
            found[info.device] = Rect(r.left, r.top, r.right-r.left, r.bottom-r.top)
        return True
    callback = callback_type(visit)
    user32.EnumDisplayMonitors(None, None, callback, 0)
    return found


def monitor_rect(hwnd):
    info = MonitorInfo()
    info.size = C.sizeof(info)
    if not user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), C.byref(info)):
        raise OSError("Monitor unavailable")
    r = info.monitor
    return Rect(r.left, r.top, r.right - r.left, r.bottom - r.top)


def active_window(active_only=True):
    hwnd = user32.GetForegroundWindow()
    pid = W.DWORD()
    user32.GetWindowThreadProcessId(hwnd, C.byref(pid))
    if not hwnd or pid.value == os.getpid() or user32.IsIconic(hwnd):
        return None
    title = C.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, title, 512)
    monitor = monitor_rect(hwnd)
    if not active_only:
        return int(hwnd), monitor, title.value
    r = W.RECT()
    if not user32.GetWindowRect(hwnd, C.byref(r)):
        return None
    rect = Rect(r.left, r.top, r.right - r.left, r.bottom - r.top).intersect(monitor)
    return (int(hwnd), rect, title.value) if rect.w > 30 and rect.h > 30 else None


def window_identity(hwnd):
    """Desktop window identity, including PID to guard against reused handles."""
    if not hwnd or not user32.IsWindow(hwnd):
        return None
    pid, rect = W.DWORD(), W.RECT()
    user32.GetWindowThreadProcessId(hwnd, C.byref(pid))
    if not user32.GetWindowRect(hwnd, C.byref(rect)):
        return None
    return (int(hwnd), pid.value, Rect(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top))


def window_at_rect(rect):
    """Resolve the visible app beneath a completed, now-closed selector."""
    point = W.POINT(rect.x + rect.w // 2, rect.y + rect.h // 2)
    hwnd = user32.GetAncestor(user32.WindowFromPoint(point), 2)
    identity = window_identity(hwnd)
    if not identity or identity[1] == os.getpid() or user32.IsIconic(hwnd):
        return None
    class_name = C.create_unicode_buffer(128)
    user32.GetClassNameW(hwnd, class_name, 128)
    if class_name.value in {'Progman', 'WorkerW', 'Shell_TrayWnd'}:
        return None
    return identity


def source_window_current(identity):
    if not identity:
        return True
    hwnd = identity[0]
    return (window_identity(hwnd) == identity and bool(user32.IsWindowVisible(hwnd))
        and not user32.IsIconic(hwnd))


def restore_capture_focus(identity):
    """Return focus after our selector closes, without stealing it from another app."""
    if not identity or window_identity(identity[0]) != identity:
        return False
    foreground = user32.GetForegroundWindow()
    pid = W.DWORD()
    if foreground:
        user32.GetWindowThreadProcessId(foreground, C.byref(pid))
    if not foreground or pid.value == os.getpid():
        user32.SetForegroundWindow(identity[0])
    return source_window_current(identity)


def focus_chosen_window(hwnd):
    """Bring an explicitly selected desktop window forward before area setup."""
    identity = window_identity(hwnd)
    if not identity or identity[1] == os.getpid():
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    if int(user32.GetForegroundWindow() or 0) != hwnd:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    return int(user32.GetForegroundWindow() or 0) == hwnd


def exclude_capture(widget):
    return bool(user32.SetWindowDisplayAffinity(int(widget.winId()), 0x11))


def set_startup(enabled):
    path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as key:
        if enabled:
            command = f'"{sys.executable}" --minimized' if getattr(sys, "frozen", False) else f'"{sys.executable}" "{os.path.abspath("main.py")}" --minimized'
            winreg.SetValueEx(key, "ArabicLens", 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, "ArabicLens")
            except FileNotFoundError:
                pass


class BitmapInfo(C.Structure):
    _fields_ = [("size", W.DWORD), ("width", W.LONG), ("height", W.LONG), ("planes", W.WORD), ("bits", W.WORD), ("compression", W.DWORD), ("image_size", W.DWORD), ("xppm", W.LONG), ("yppm", W.LONG), ("used", W.DWORD), ("important", W.DWORD), ("colors", W.DWORD * 3)]


class CaptureService:
    """Reusable top-down GDI buffer. Access from the processing thread only."""
    def __init__(self):
        self.screen = user32.GetDC(None)
        self.dc = gdi32.CreateCompatibleDC(self.screen)
        self.bitmap = self.old = None
        self.shape = None

    def capture(self, rect):
        if rect.w <= 0 or rect.h <= 0 or rect.w * rect.h > 50_000_000:
            raise ValueError("Invalid screen region")
        if self.shape != (rect.h, rect.w):
            self._release_bitmap()
            info = BitmapInfo()
            info.size, info.width, info.height = 40, rect.w, -rect.h
            info.planes, info.bits = 1, 32
            bits = C.c_void_p()
            self.bitmap = gdi32.CreateDIBSection(self.screen, C.byref(info), 0, C.byref(bits), None, 0)
            if not self.bitmap or not bits.value:
                raise OSError("Screen capture unavailable")
            self.old = gdi32.SelectObject(self.dc, self.bitmap)
            self.buffer = np.ctypeslib.as_array((C.c_ubyte * (rect.w * rect.h * 4)).from_address(bits.value)).reshape(rect.h, rect.w, 4)
            self.shape = (rect.h, rect.w)
        if not gdi32.BitBlt(self.dc, 0, 0, rect.w, rect.h, self.screen, rect.x, rect.y, 0x00CC0020 | 0x40000000):
            raise OSError("Screen capture unavailable")
        gdi32.GdiFlush()  # Complete GDI writes before reading the DIB directly.
        return self.buffer  # Borrowed until next capture; crop/copy before awaiting.



    def _release_bitmap(self):
        if self.bitmap:
            gdi32.SelectObject(self.dc, self.old)
            gdi32.DeleteObject(self.bitmap)
            self.bitmap = None

    def close(self):
        self._release_bitmap()
        gdi32.DeleteDC(self.dc)
        user32.ReleaseDC(None, self.screen)


class PreviewCaptureService(CaptureService):
    """Reuse a 320×180 DIB; never allocate a full desktop frame for idle checks."""
    def __init__(self):
        super().__init__()
        # BLACKONWHITE's bitwise shrink can erase thin white text on dark games.
        # HALFTONE preserves its contribution in the small change preview.
        gdi32.SetStretchBltMode(self.dc, 4)
        gdi32.SetBrushOrgEx(self.dc, 0, 0, None)

    def capture(self, rect):
        super().capture(Rect(rect.x, rect.y, 320, 180))
        if not gdi32.StretchBlt(self.dc, 0, 0, 320, 180, self.screen,
                rect.x, rect.y, rect.w, rect.h, 0x00CC0020 | 0x40000000):
            raise OSError('Screen capture unavailable')
        gdi32.GdiFlush()
        return self.buffer


user32.GetTopWindow.argtypes = [W.HWND]
user32.GetTopWindow.restype = W.HWND
user32.GetWindow.argtypes = [W.HWND, W.UINT]
user32.GetWindow.restype = W.HWND
user32.PrintWindow.argtypes = [W.HWND, W.HDC, W.UINT]
user32.PrintWindow.restype = W.BOOL
user32.GetWindowLongW.argtypes = [W.HWND, C.c_int]
user32.GetWindowLongW.restype = C.c_long
try:
    dwmapi = C.WinDLL("dwmapi")
    dwmapi.DwmGetWindowAttribute.argtypes = [W.HWND, W.DWORD, C.c_void_p, W.DWORD]
except OSError:
    dwmapi = None


def _window_beneath(x, y):
    """Topmost visible window of another process containing a physical point.

    Skips our own windows and click-through (input-transparent) windows, which
    is what lies under one of our capture-visible overlays.
    """
    own = os.getpid()
    hwnd = user32.GetTopWindow(None)
    rect, pid, cloaked = W.RECT(), W.DWORD(), C.c_int()
    for _ in range(4096):
        if not hwnd:
            return None
        if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            user32.GetWindowThreadProcessId(hwnd, C.byref(pid))
            style = user32.GetWindowLongW(hwnd, -20)
            if pid.value != own and not style & 0x20 and user32.GetWindowRect(hwnd, C.byref(rect)) \
                    and rect.left <= x < rect.right and rect.top <= y < rect.bottom:
                cloaked.value = 0
                if dwmapi is not None:
                    dwmapi.DwmGetWindowAttribute(hwnd, 14, C.byref(cloaked), 4)
                if not cloaked.value:
                    return hwnd, Rect(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
        hwnd = user32.GetWindow(hwnd, 2)  # GW_HWNDNEXT
    return None


class WindowBeneathCapture:
    """Pixels of the application window beneath our own overlays.

    Used only where Windows refuses to exclude overlays from screen capture
    (seen on Windows 11 build 22000). The window renders itself without the
    overlays on top (PrintWindow with full content), so text hidden under an
    overlay can still be followed: it updates and disappears normally. One
    render per window is reused briefly. Processing thread only.
    """
    max_age = .2

    def __init__(self):
        self.screen = user32.GetDC(None)
        self.cache = {}

    def pixels(self, rect, depth=0):
        """BGRA pixels for an absolute physical rect, or None when unavailable.

        A rect crossing a window edge is assembled from each window beneath it.
        """
        found = _window_beneath(rect.x + rect.w // 2, rect.y + rect.h // 2)
        if not found:
            return None
        hwnd, frame = found
        inside = rect.intersect(frame)
        if not inside.w or not inside.h:
            return None
        image = self._window_pixels(hwnd, frame)
        if image is None:
            return None
        x, y = inside.x - frame.x, inside.y - frame.y
        part = image[y:y + inside.h, x:x + inside.w]
        if (inside.w, inside.h) == (rect.w, rect.h):
            return part
        if depth >= 3:
            return None
        result = np.zeros((rect.h, rect.w, 4), np.uint8)
        result[inside.y - rect.y:inside.bottom - rect.y, inside.x - rect.x:inside.right - rect.x] = part
        # The parts of rect outside this window: above, below, left, right.
        rest = (Rect(rect.x, rect.y, rect.w, inside.y - rect.y),
                Rect(rect.x, inside.bottom, rect.w, rect.bottom - inside.bottom),
                Rect(rect.x, inside.y, inside.x - rect.x, inside.h),
                Rect(inside.right, inside.y, rect.right - inside.right, inside.h))
        for piece in rest:
            if piece.w > 0 and piece.h > 0:
                pixels = self.pixels(piece, depth + 1)
                if pixels is None:
                    return None
                result[piece.y - rect.y:piece.bottom - rect.y, piece.x - rect.x:piece.right - rect.x] = pixels
        return result

    def _window_pixels(self, hwnd, frame):
        import time
        if frame.w * frame.h > 50_000_000:
            return None
        key = int(hwnd)
        cached = self.cache.get(key)
        now = time.monotonic()
        if not cached or now - cached[0] > self.max_age or cached[1] != frame:
            # GPU-presented windows occasionally render one all-black frame.
            image = self._render(hwnd, frame)
            if image is None:
                image = self._render(hwnd, frame)
            if image is None:
                return None
            if len(self.cache) > 8:
                self.cache.clear()
            cached = self.cache[key] = (now, frame, image)
        return cached[2]

    def _render(self, hwnd, frame):
        dc = gdi32.CreateCompatibleDC(self.screen)
        info = BitmapInfo()
        info.size, info.width, info.height = 40, frame.w, -frame.h
        info.planes, info.bits = 1, 32
        bits = C.c_void_p()
        bitmap = gdi32.CreateDIBSection(self.screen, C.byref(info), 0, C.byref(bits), None, 0)
        try:
            if not dc or not bitmap or not bits.value:
                return None
            old = gdi32.SelectObject(dc, bitmap)
            ok = user32.PrintWindow(hwnd, dc, 2)  # PW_RENDERFULLCONTENT
            gdi32.GdiFlush()
            image = None
            if ok:
                image = np.ctypeslib.as_array((C.c_ubyte * (frame.w * frame.h * 4)).from_address(bits.value)).reshape(frame.h, frame.w, 4).copy()
                if not image[::8, ::8, :3].any():
                    image = None  # Some windows (exclusive/protected video) render black.
            gdi32.SelectObject(dc, old)
            return image
        finally:
            if bitmap:
                gdi32.DeleteObject(bitmap)
            if dc:
                gdi32.DeleteDC(dc)

    def close(self):
        user32.ReleaseDC(None, self.screen)
