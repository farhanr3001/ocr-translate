"""Separate-process editor fixture: a Notepad-like window with a live caret.

Usage: editor_window.py DIR [SCRIPT_JSON]
SCRIPT_JSON (optional) is a list of steps executed in order:
  {"type": "text", "delay_ms": 40}   types characters one at a time
  {"type": "wait", "ms": 500}
  {"type": "clear"}
  {"type": "set", "text": "..."}     replace the whole document
Writes DIR/ready.json with hwnd and the physical text-area rectangle, and
DIR/done.json when the script ends. Touching DIR/quit exits.
"""
import json
import sys
from pathlib import Path
from arabic_lens.windows import enable_dpi
enable_dpi()
from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import QApplication, QPlainTextEdit
from arabic_lens.models import Rect
from arabic_lens.overlay import logical_to_physical

directory = Path(sys.argv[1])
steps = json.loads(Path(sys.argv[2]).read_text()) if len(sys.argv) > 2 else []
initial = ''
if steps and steps[0].get('type') == 'set':
    initial = steps.pop(0)['text']
qt = QApplication([])
area = qt.primaryScreen().availableGeometry()
editor = QPlainTextEdit()
editor.setWindowTitle('Arabic Lens editor fixture')
editor.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
editor.setFont(QFont('Segoe UI', 15))
editor.setStyleSheet('QPlainTextEdit { background: #202020; color: #f2f2f2; border: none; padding: 14px; }')
editor.setPlainText(initial)


class IgnoreKeyboard(QObject):
    """The fixture is driven by its script only; never by the user's typing."""
    def eventFilter(self, watched, event):
        return event.type() in (QEvent.KeyPress, QEvent.KeyRelease, QEvent.InputMethod)


keyboard_guard = IgnoreKeyboard()
editor.installEventFilter(keyboard_guard)
editor.viewport().installEventFilter(keyboard_guard)
editor.moveCursor(QTextCursor.End)
editor.setGeometry(area.x() + 60, area.y() + 60, min(900, area.width() - 120), min(520, area.height() - 120))
editor.show()
editor.activateWindow()
editor.setFocus()
qt.processEvents()
viewport = editor.viewport()
point = viewport.mapToGlobal(viewport.rect().topLeft())
rect = logical_to_physical(editor.screen(), Rect(point.x(), point.y(), viewport.width(), viewport.height()))
(directory / 'ready.json').write_text(json.dumps(dict(hwnd=int(editor.winId()), rect=[rect.x, rect.y, rect.w, rect.h])))

queue = []
for step in steps:
    if step['type'] == 'text':
        for char in step['text']:
            queue.append(('char', char, step.get('delay_ms', 45)))
    elif step['type'] == 'wait':
        queue.append(('wait', None, step['ms']))
    elif step['type'] == 'clear':
        queue.append(('clear', None, step.get('delay_ms', 10)))
    elif step['type'] == 'set':
        queue.append(('set', step['text'], step.get('delay_ms', 10)))
    elif step['type'] == 'backspace':
        for _ in range(step['count']):
            queue.append(('backspace', None, step.get('delay_ms', 45)))


def run_next():
    if (directory / 'quit').exists():
        qt.quit(); return
    if not queue:
        (directory / 'done.json').write_text('{}')
        QTimer.singleShot(100, run_next)
        return
    kind, value, delay = queue.pop(0)
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.End)
    if kind == 'char':
        cursor.insertText(value)
    elif kind == 'backspace':
        cursor.deletePreviousChar()
    elif kind == 'clear':
        editor.clear()
    elif kind == 'set':
        editor.setPlainText(value)
    editor.moveCursor(QTextCursor.End)
    QTimer.singleShot(delay, run_next)


QTimer.singleShot(300, run_next)
qt.exec()
