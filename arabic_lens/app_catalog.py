"""Read-only desktop app inventory and executable-based Watch exclusions."""
import ctypes as C
from ctypes import wintypes as W
import json
import ntpath
import os
import subprocess
import threading
import time
import winreg
from .windows import user32


def path_key(path):
    return ntpath.normpath(os.path.expandvars(path.strip().strip('"'))).casefold()


def clean_apps(apps):
    result, seen = [], set()
    for app in apps if isinstance(apps, list) else []:
        if not isinstance(app, dict) or not isinstance(app.get('path'), str):
            continue
        path = app['path'].strip()
        if not ntpath.isabs(path) or not path.lower().endswith('.exe'):
            continue
        key = path_key(path)
        if key not in seen:
            seen.add(key)
            name = app.get('name')
            result.append({'name': name if isinstance(name, str) and name else ntpath.basename(path), 'path': path})
    return sorted(result, key=lambda app: app['name'].casefold())


kernel32 = C.WinDLL('kernel32', use_last_error=True)
kernel32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
kernel32.OpenProcess.restype = W.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
kernel32.CloseHandle.argtypes = [W.HANDLE]


def executable_for_window(hwnd):
    pid = W.DWORD()
    user32.GetWindowThreadProcessId(hwnd, C.byref(pid))
    # This permission reads only the executable's identity, never process memory.
    handle = kernel32.OpenProcess(0x1000, False, pid.value)
    if not handle:
        return ''
    try:
        size = W.DWORD(32768)
        buffer = C.create_unicode_buffer(size.value)
        return buffer.value if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, C.byref(size)) else ''
    finally:
        kernel32.CloseHandle(handle)


class AppBlockService:
    def __init__(self, settings, resolver=None):
        self.settings = settings
        self.resolver = resolver or executable_for_window
        self.cache = {}
        self.lock = threading.Lock()

    def blocked(self, hwnd):
        apps = self.settings.blocked_apps
        if not apps or not hwnd:
            return False
        pid = W.DWORD()
        user32.GetWindowThreadProcessId(hwnd, C.byref(pid))
        identity = (int(hwnd), pid.value)
        now = time.monotonic()
        with self.lock:
            cached = self.cache.get(identity)
            if cached is None or now - cached[0] > 2:
                cached = (now, path_key(self.resolver(hwnd)))
                if len(self.cache) >= 128:
                    self.cache.clear()
                self.cache[identity] = cached
        return any(cached[1] == path_key(app['path']) for app in apps)


def open_apps():
    apps = []
    callback_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    def visit(hwnd, unused):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = W.DWORD()
        user32.GetWindowThreadProcessId(hwnd, C.byref(pid))
        if pid.value == os.getpid():
            return True
        title = C.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title, 512)
        if title.value:
            path = executable_for_window(hwnd)
            if ntpath.basename(path).casefold() not in {'applicationframehost.exe', 'shellexperiencehost.exe'}:
                apps.append({'name': title.value, 'path': path})
        return True
    callback = callback_type(visit)
    user32.EnumWindows.argtypes = [callback_type, W.LPARAM]
    user32.EnumWindows(callback, 0)
    return clean_apps(apps)


def open_windows():
    """Visible user windows for choosing a Watch preset target."""
    results = []
    callback_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    def visit(hwnd, unused):
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        pid = W.DWORD()
        user32.GetWindowThreadProcessId(hwnd, C.byref(pid))
        if pid.value == os.getpid():
            return True
        title = C.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title, 512)
        if title.value.strip():
            rect = W.RECT()
            if user32.GetWindowRect(hwnd, C.byref(rect)) and rect.right-rect.left > 100 and rect.bottom-rect.top > 80:
                path = executable_for_window(hwnd)
                if ntpath.basename(path).casefold() not in {'shellexperiencehost.exe'}:
                    results.append({'hwnd': int(hwnd), 'title': title.value, 'path': path})
        return True
    callback = callback_type(visit)
    user32.EnumWindows.argtypes = [callback_type, W.LPARAM]
    user32.EnumWindows(callback, 0)
    return results


def installed_apps():
    apps = []
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(root, r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths', 0, winreg.KEY_READ | view) as key:
                    for index in range(winreg.QueryInfoKey(key)[0]):
                        name = winreg.EnumKey(key, index)
                        try:
                            with winreg.OpenKey(key, name) as child:
                                path = os.path.expandvars(winreg.QueryValue(child, '').strip('"'))
                                if os.path.isfile(path):
                                    apps.append({'name': ntpath.splitext(name)[0], 'path': path})
                        except OSError:
                            pass
            except OSError:
                pass
    # Resolve Start menu shortcuts without launching the apps. Runs only on demand,
    # off the UI thread, with no console window or recurring background inventory.
    script = r"""
    [Console]::OutputEncoding=[System.Text.Encoding]::UTF8
    $ErrorActionPreference='SilentlyContinue'
    $shell=New-Object -ComObject WScript.Shell
    $folders=@([Environment]::GetFolderPath('StartMenu'),[Environment]::GetFolderPath('CommonStartMenu'))
    $items=@(foreach($folder in $folders){
      Get-ChildItem -LiteralPath $folder -Filter *.lnk -Recurse | ForEach-Object {
        $target=$shell.CreateShortcut($_.FullName).TargetPath
        if($target -and $target.EndsWith('.exe',[StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $target)){
          if($_.BaseName -notmatch '(?i)uninstall|remove'){
            @{name=$_.BaseName;path=$target}
          }
        }
      }
    })
    ConvertTo-Json -InputObject $items -Compress
    """
    import base64
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    executable = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
    try:
        completed = subprocess.run([executable, '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                                   capture_output=True, timeout=25, creationflags=subprocess.CREATE_NO_WINDOW)
        data = json.loads(completed.stdout.decode('utf-8-sig', errors='replace'))
        apps.extend(data if isinstance(data, list) else [])
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return clean_apps(apps)
