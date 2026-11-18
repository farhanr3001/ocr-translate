"""Separate-process windows for native selection ownership regression testing."""
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
target = QLabel('Find the silver needle before sunset.')
target.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint)
target.setFont(QFont('Segoe UI', 24))
target.setStyleSheet('background: #ffffff; color: #14221e; padding: 12px')
target.setWindowTitle('Selected text fixture')
target.setGeometry(area.x()+40, area.y()+70, min(760, area.width()-80), 150)
target.show()
previous = QLabel('Previous foreground window')
previous.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint)
previous.setWindowTitle('Previous foreground fixture')
previous.setGeometry(area.x()+40, area.y()+280, 320, 100)
previous.show()
qt.processEvents()
point = target.mapToGlobal(target.rect().topLeft())
rect = logical_to_physical(target.screen(), Rect(point.x(), point.y(), target.width(), target.height()))
(directory / 'ready.json').write_text(json.dumps(dict(target=int(target.winId()), previous=int(previous.winId()),
    rect=[rect.x,rect.y,rect.w,rect.h])))
timer = QTimer()
timer.timeout.connect(lambda: previous.close() if (directory/'close-previous').exists() else None)
timer.start(50)
qt.exec()
