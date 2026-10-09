"""Render the real progress widget over the clean OCR test fixture, offscreen."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt,QRect
from PySide6.QtGui import QImage,QPainter
from PySide6.QtWidgets import QApplication
from arabic_lens.models import Rect
from arabic_lens.progress import ProgressSurface

root=Path('artifacts/desktop-clean-coverage')
app=QApplication([])
background=QImage(str(root/'source.png'))
surface=ProgressSurface(SimpleNamespace(geometry=lambda:QRect(0,0,background.width(),background.height())))
surface.setAttribute(Qt.WA_DontShowOnScreen)
data=json.loads((root/'coverage.json').read_text(encoding='utf8'))['fullscreen']['blocks']
surface.items=[(Rect(**b['rect']),25,'Detected') for b in data]
surface.show();app.processEvents()
paint=QPainter(background);paint.drawPixmap(0,0,surface.grab());paint.end()
background.save(str(root/'translation-boxes.png'))
surface.close()
