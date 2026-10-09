from PyInstaller.utils.hooks import collect_submodules, collect_dynamic_libs, collect_data_files, copy_metadata
from pathlib import Path
import PySide6

notices = []
for package in ('ctranslate2', 'sentencepiece', 'PySide6', 'shiboken6', 'numpy', 'opencv-python-headless', 'httpx', 'httpcore', 'anyio', 'certifi', 'idna', 'h11', 'winrt-runtime', 'winrt-Windows.Foundation', 'winrt-Windows.Foundation.Collections', 'winrt-Windows.Globalization', 'winrt-Windows.Graphics.Imaging', 'winrt-Windows.Media.Ocr', 'winrt-Windows.Storage.Streams'):
    notices += copy_metadata(package)

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=collect_dynamic_libs('winrt'),
    datas=collect_data_files('winrt') + [(str(path), str(path.parent))
        for path in Path('arabic_lens/data').rglob('*') if path.is_file()
        and not {'offline-en-ar', 'translation'}.intersection(path.parts)] + notices,
    hiddenimports=collect_submodules('winrt'),
    hookspath=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtQml', 'PySide6.QtQuick', 'pytest', 'tkinter'],
    noarchive=False,
)
# Python 3.10 and PyWinRT ship older VC runtimes. Qt 6.11 requires the newer
# redistributable supplied with PySide6. Use one compatible version everywhere.
runtime_directory = Path(PySide6.__file__).parent
runtime_names = ['VCRUNTIME140.dll', 'VCRUNTIME140_1.dll', 'MSVCP140.dll', 'MSVCP140_1.dll', 'MSVCP140_2.dll']
a.binaries = [entry for entry in a.binaries if Path(entry[0]).name.casefold() not in {name.casefold() for name in runtime_names}]
a.binaries += [(name, str(runtime_directory / name), 'BINARY') for name in runtime_names]
# Qt uses the unversioned Windows ICU API. An unrelated Poppler ICU on the
# developer PATH exports versioned symbols and must never shadow Windows ICU.
a.binaries = [entry for entry in a.binaries if Path(entry[0]).name.casefold() not in {'icuuc.dll', 'icudt78.dll'}]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ArabicLens', debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False, console=False,
    icon='assets/lens.ico', version='assets/version.txt', manifest='assets/app.manifest')
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='ArabicLens')
