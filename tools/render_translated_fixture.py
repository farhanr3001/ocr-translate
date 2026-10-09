"""Render saved real translation results using production OverlayManager, offscreen."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt,QRect
from PySide6.QtGui import QImage,QPainter
from PySide6.QtWidgets import QApplication
from arabic_lens.config import Settings
from arabic_lens.models import Rect,Translation
import arabic_lens.overlay as overlay_module

root=Path('artifacts/desktop-clean-coverage')
app=QApplication([])
image=QImage(str(root/'source.png'))
screen=SimpleNamespace(availableGeometry=lambda:QRect(0,0,image.width(),image.height()))
# Reproduce the fixture's physical pixels without showing windows on the desktop.
overlay_module.physical_to_logical=lambda rect:(screen,rect)
original=overlay_module.TranslationOverlay
class HiddenOverlay(original):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.setAttribute(Qt.WA_DontShowOnScreen)
overlay_module.TranslationOverlay=HiddenOverlay
settings=Settings()
manager=overlay_module.OverlayManager(settings,print)
results=json.loads((root/'translation-results.json').read_text(encoding='utf8'))['results']
ocr=json.loads((root/'coverage.json').read_text(encoding='utf8'))['fullscreen']['blocks']
for i,result in enumerate(results):
    if result['error'] or result['english']==result['arabic']:continue
    value=Translation(f'fixture-{i}',result['english'],result['arabic'],Rect(**result['rect']),'Google Chrome')
    value.container=Rect(**ocr[i]['container']) if ocr[i].get('container') else None
    manager.show(value)
app.processEvents()
paint=QPainter(image)
geometry=[]
for key,window in manager.windows.items():
    window.animation.setCurrentTime(settings.overlay.fade_ms)
    paint.drawPixmap(window.x(),window.y(),window.grab())
    geometry.append({'id':key,'rect':[window.x(),window.y(),window.width(),window.height()]})
paint.end()
image.save(str(root/'translated-screen.png'))
(root/'overlay-geometry.json').write_text(json.dumps(geometry,indent=2),encoding='utf8')
print(f'Rendered {len(geometry)} actual Arabic overlays; unchanged identifiers remain visible.')
manager.clear(immediate=True)
