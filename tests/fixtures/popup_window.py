"""Separate-process game-style instruction popup for live Watch/Quick checks.

Usage: popup_window.py DIR SCRIPT_JSON
SCRIPT_JSON is a list of steps:
  {"type": "show", "title": "...", "lines": ["...", ...]}   show/replace the panel
  {"type": "hide"}                                         popup disappears
  {"type": "wait", "ms": 1000}
Each instruction is its own paragraph; long ones word-wrap inside the panel,
like a real game tutorial box. Writes DIR/ready.json with the physical panel
area (the whole window, which stays where it is), and DIR/done.json at the end.
"""
import json
import sys
from pathlib import Path
from arabic_lens.windows import enable_dpi
enable_dpi()
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout, QWidget
from arabic_lens.models import Rect
from arabic_lens.overlay import logical_to_physical

directory = Path(sys.argv[1])
steps = json.loads(Path(sys.argv[2]).read_text())
qt = QApplication([])
area = qt.primaryScreen().availableGeometry()
window = QWidget()
window.setWindowTitle('Arabic Lens game popup fixture')
window.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
window.setStyleSheet('background: #1b2a22;')  # The game scene behind the popup.
window.setGeometry(area.x() + 60, area.y() + 60, min(820, area.width() - 120), min(560, area.height() - 120))
panel = QFrame(window)
panel.setStyleSheet('QFrame { background: #2d2418; border: 3px solid #c9a45c; border-radius: 10px; }'
                    'QLabel { border: none; color: #f4ead2; background: transparent; }')
panel.setGeometry(70, 50, 560, 440)
layout = QVBoxLayout(panel)
layout.setContentsMargins(26, 20, 26, 20)
layout.setSpacing(14)
title = QLabel()
title.setFont(QFont('Segoe UI', 17, QFont.Bold))
layout.addWidget(title)
labels = []
for _ in range(6):
    label = QLabel()
    label.setWordWrap(True)
    label.setFont(QFont('Segoe UI', 13))
    layout.addWidget(label)
    labels.append(label)
layout.addStretch()
panel.hide()
window.show()
qt.processEvents()
point = window.mapToGlobal(window.rect().topLeft())
rect = logical_to_physical(window.screen(), Rect(point.x(), point.y(), window.width(), window.height()))
(directory / 'ready.json').write_text(json.dumps(dict(hwnd=int(window.winId()), rect=[rect.x, rect.y, rect.w, rect.h])))


def run_next():
    if (directory / 'quit').exists():
        qt.quit(); return
    if not steps:
        (directory / 'done.json').write_text('{}')
        QTimer.singleShot(100, run_next)
        return
    step = steps.pop(0)
    delay = 10
    if step['type'] == 'show':
        title.setText(step.get('title', ''))
        title.setVisible(bool(step.get('title')))
        for index, label in enumerate(labels):
            text = step['lines'][index] if index < len(step['lines']) else ''
            label.setText(text)
            label.setVisible(bool(text))
        panel.show()
    elif step['type'] == 'hide':
        panel.hide()
    elif step['type'] == 'wait':
        delay = step['ms']
    QTimer.singleShot(delay, run_next)


QTimer.singleShot(300, run_next)
qt.exec()
