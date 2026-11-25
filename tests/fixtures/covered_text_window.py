"""Separate-process window whose English line is changed by trigger files.

Usage: covered_text_window.py DIR
Writes DIR/ready.json with the physical rectangle of the text panel. Touch
DIR/clear to remove the text, DIR/second to show a different line and
DIR/quit to exit.
"""
import json
import sys
from pathlib import Path
from arabic_lens.windows import enable_dpi
enable_dpi()
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel
from arabic_lens.models import Rect
from arabic_lens.overlay import logical_to_physical

directory = Path(sys.argv[1])
qt = QApplication([])
area = qt.primaryScreen().availableGeometry()
label = QLabel('Meet me at the old bridge tonight.')
label.setWindowTitle('Arabic Lens covered text fixture')
label.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
label.setFont(QFont('Segoe UI', 16))
label.setStyleSheet('QLabel { background: #f3efe6; color: #1d2a24; padding: 24px; }')
label.setGeometry(area.x() + 120, area.y() + 120, 640, 120)
label.show()
qt.processEvents()
rect = logical_to_physical(label.screen(), Rect(label.x(), label.y(), label.width(), label.height()))
(directory / 'ready.json').write_text(json.dumps(dict(hwnd=int(label.winId()), rect=[rect.x, rect.y, rect.w, rect.h])))
state = {'clear': False, 'second': False}


def poll():
    if (directory / 'quit').exists():
        qt.quit(); return
    if (directory / 'second').exists() and not state['second']:
        state['second'] = True; label.setText('The library closes at noon.')
    elif (directory / 'clear').exists() and not state['clear'] and not state['second']:
        state['clear'] = True; label.setText('')
    QTimer.singleShot(50, poll)


poll()
qt.exec()
