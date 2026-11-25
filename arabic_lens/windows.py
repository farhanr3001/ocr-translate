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
