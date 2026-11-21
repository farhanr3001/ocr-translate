"""Separate-process stream-chat fixture: new messages push older ones up.

Usage: chat_window.py DIR SCRIPT_JSON
SCRIPT_JSON: {"interval_ms": 800, "messages": [["name", "#hex", "text"], ...],
              "start_ms": 1500, "timestamps": true, "max_messages": 0,
              "delete": {"after": 6, "position": 2}, "clear_after": 0}
max_messages > 0 drops the oldest messages from the top (a capped chat);
"delete" removes the message at `position` once `after` messages were sent
(a moderator deleting it: the lines below move up); clear_after clears all.
Writes DIR/ready.json (physical chat rectangle), DIR/visible.json after each
message (the messages currently fully visible), DIR/done.json at the end.
"""
import json
import sys
import time
from pathlib import Path
from arabic_lens.windows import enable_dpi
enable_dpi()
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import QApplication, QTextEdit
from arabic_lens.models import Rect
from arabic_lens.overlay import logical_to_physical

directory = Path(sys.argv[1])
script = json.loads(Path(sys.argv[2]).read_text())
qt = QApplication([])
area = qt.primaryScreen().availableGeometry()
chat = QTextEdit()
chat.setReadOnly(True)
chat.setWindowTitle('Arabic Lens chat fixture')
chat.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
chat.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
chat.setFont(QFont('Segoe UI', 12))
chat.setStyleSheet('QTextEdit { background: #18181b; color: #efeff1; border: none; padding: 10px; }')
chat.setGeometry(area.x() + 80, area.y() + 60, 420, min(620, area.height() - 120))
chat.show()
qt.processEvents()
viewport = chat.viewport()
point = viewport.mapToGlobal(viewport.rect().topLeft())
rect = logical_to_physical(chat.screen(), Rect(point.x(), point.y(), viewport.width(), viewport.height()))
(directory / 'ready.json').write_text(json.dumps(dict(hwnd=int(chat.winId()), rect=[rect.x, rect.y, rect.w, rect.h])))
messages = list(script['messages'])
shown = []
sent = [0]
log = []
clock = [23 * 60 + 33]


def emote(color):
    return (f'<span style="background:{color}; color:{color};">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span>')


def add_next():
    if (directory / 'quit').exists():
        qt.quit(); return
    if not messages:
        (directory / 'done.json').write_text('{}')
        QTimer.singleShot(200, add_next)
        return
    name, color, text = messages.pop(0)
    sent[0] += 1
    stamp = f'<span style="color:#adadb8">{clock[0] // 60:02d}:{clock[0] % 60:02d}</span> ' if script.get('timestamps', True) else ''
    body = text.replace('&', '&amp;').replace('<', '&lt;').replace('[emote]', emote('#d9b13b'))
    cursor = chat.textCursor()
    cursor.movePosition(QTextCursor.End)
    if shown:
        cursor.insertBlock()
    cursor.insertHtml(f'{stamp}<b style="color:{color}">{name}</b>: {body}')
    chat.verticalScrollBar().setValue(chat.verticalScrollBar().maximum())
    shown.append([name, text.replace('[emote]', '').strip()])

    def remove_block(position):
        block = chat.document().findBlockByNumber(position)
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        cursor.select(QTextCursor.BlockUnderCursor)
        if position == 0:
            cursor = QTextCursor(block)
            cursor.movePosition(QTextCursor.NextBlock, QTextCursor.KeepAnchor)
        cursor.removeSelectedText()
        log.append({'t': round(time.monotonic(), 3), 'removed': shown.pop(position)})

    limit = script.get('max_messages', 0)
    while limit and len(shown) > limit:
        remove_block(0)
    deletion = script.get('delete')
    if deletion and sent[0] == deletion['after']:
        remove_block(deletion['position'])
    if script.get('clear_after') and sent[0] == script['clear_after']:
        chat.clear()
        log.append({'t': round(time.monotonic(), 3), 'cleared': list(shown)})
        shown.clear()
    (directory / 'removals.json').write_text(json.dumps(log))
    # Messages whose block is fully inside the viewport.
    visible = []
    document = chat.document()
    scroll = chat.verticalScrollBar().value()
    block = document.begin()
    index = 0
    while block.isValid():
        geometry = document.documentLayout().blockBoundingRect(block)
        if geometry.top() - scroll >= 0 and geometry.bottom() - scroll <= viewport.height():
            visible.append(shown[index])
        block = block.next()
        index += 1
    (directory / 'visible.json').write_text(json.dumps(visible))
    QTimer.singleShot(script['interval_ms'], add_next)


QTimer.singleShot(script.get('start_ms', 1500), add_next)
qt.exec()
