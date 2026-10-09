from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from arabic_lens.ui import lens_icon
from PIL import Image

app = QApplication([])
Path('assets').mkdir(exist_ok=True)
lens_icon(256, True).pixmap(256, 256).save('assets/lens.png')
Image.open('assets/lens.png').save('assets/lens.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
