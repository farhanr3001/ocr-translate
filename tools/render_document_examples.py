"""Render user-supplied document fixtures using real Windows OCR and CPU MT.

No test window is shown and no hand-written translation replaces model output.
"""
import asyncio
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QWidget
from arabic_lens.config import Settings
from arabic_lens.localization import LocalizationService
from arabic_lens.ocr import WindowsOcrProvider, OcrService
from arabic_lens.text import TextFilterService
from arabic_lens.offline import TranslationProvider
from arabic_lens.translation import TranslationService
from arabic_lens.storage import TranslationStore
from arabic_lens.overlay import ArabicSurface
from arabic_lens.ui import SettingsWindow


class Frame(QWidget):
    def __init__(self, image):
        super().__init__()
        self.frame = QImage(image.data, image.shape[1], image.shape[0], image.strides[0], QImage.Format_BGR888).copy()
        self.resize(self.frame.size())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawImage(0, 0, self.frame)


async def main():
    qt = QApplication([])
    directory = Path('artifacts/document-formatting')
    directory.mkdir(parents=True, exist_ok=True)
    settings = Settings()
    store = TranslationStore(directory/'examples.db', settings)
    provider = TranslationProvider(settings)
    translator = TranslationService(provider, store)
    ocr = OcrService(WindowsOcrProvider(), TextFilterService(settings))
    evidence = []
    try:
        for name in ('paragraphs', 'financial-list'):
            image = cv2.imread(str(Path('tests/fixtures')/(name+'.png')))
            blocks = await ocr.read(image, manual=True)
            frame = Frame(image)
            surfaces = []
            for block in blocks:
                arabic, cached = await translator.translate(block.text)
                surface = ArabicSurface(settings.overlay, arabic)
                surface.setParent(frame)
                surface.fit_to_source(block.rect, max_extra=0 if block.container else 80)
                surface.move(block.rect.x-surface.fit_margin, block.rect.y-surface.fit_margin)
                surface.setAttribute(Qt.WA_DontShowOnScreen, True)
                surface.show()
                surfaces.append(surface)
                evidence.append({'fixture': name, 'source': block.text, 'arabic': arabic,
                                 'source_rect': vars(block.rect), 'cache_hit': cached})
            pixmap = frame.grab()
            pixmap.save(str(directory/(name+'-translated.png')))
            pixmap.scaled(pixmap.width()*2, pixmap.height()*2).save(str(directory/(name+'-translated-2x.png')))
            frame.deleteLater()
        window = SettingsWindow(settings, LocalizationService(settings), store)
        window.setAttribute(Qt.WA_DontShowOnScreen, True)
        window.show()
        for page, name in ((2,'translation'),(3,'watch'),(4,'overlay')):
            window.navigate(page); qt.processEvents()
            window.grab().save(str(directory/(name+'-page.png')))
        window.hide(); window.deleteLater()
        (directory/'examples.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    finally:
        await provider.close()
        store.close()


if __name__ == '__main__':
    asyncio.run(main())
