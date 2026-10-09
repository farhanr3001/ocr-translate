"""Real OCR + real cache + native overlay renderer on official screenshot fixtures.

No game is launched, no text boxes are supplied manually, and no provider is
mocked. Unknown text is reported and skipped rather than fabricated.
"""
import asyncio
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QWidget
from arabic_lens.config import Settings
from arabic_lens.storage import TranslationStore
from arabic_lens.detection import TextRegionDetector
from arabic_lens.text import TextFilterService, belongs_to_region
from arabic_lens.ocr import OcrService, WindowsOcrProvider
from arabic_lens.overlay import ArabicSurface, OverlayInteraction, place_overlay
from PySide6.QtCore import Qt
from arabic_lens.appearance import effective_appearance, sample_cell_style
from arabic_lens.models import Rect


class ScreenshotFixture(QWidget):
    def __init__(self, image):
        super().__init__()
        self.frame = QImage(image.data, image.shape[1], image.shape[0], image.strides[0], QImage.Format_BGR888).copy()
        self.resize(self.frame.size())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawImage(0, 0, self.frame)


async def run():
    qt = QApplication([])
    directory = Path('artifacts/dressmaker/examples')
    directory.mkdir(parents=True, exist_ok=True)
    settings = Settings()
    store = TranslationStore(directory / 'test-cache.db', settings)
    store.seed_pack(Path('arabic_lens/data/dressmaker.json'))
    ocr = OcrService(WindowsOcrProvider(), TextFilterService(settings))
    detector = TextRegionDetector()
    evidence = []
    for file in ['steam-00.jpg', 'steam-02.jpg', 'steam-05.jpg']:
        image = cv2.imread(str(directory.parent / file))
        started = time.perf_counter()
        detected = []
        candidates = detector.detect(image)
        for region in candidates[:settings.max_regions]:
            offset = Rect(max(0, region.x - 24), max(0, region.y - 64), 0, 0)
            offset = Rect(offset.x, offset.y, min(image.shape[1], region.right + 24) - offset.x,
                min(image.shape[0], region.bottom + 100) - offset.y)
            crop = image[offset.y:offset.bottom, offset.x:offset.right]
            original_blocks = await ocr.read(crop)
            protected = list(ocr.last_lines)
            local_source = Rect(region.x - offset.x, region.y - offset.y, region.w, region.h)
            original_blocks = [b for b in original_blocks if belongs_to_region(b, local_source)]
            blocks = original_blocks
            if not blocks:
                continue
            for block in blocks:
                source, box = block.text, block.rect
                arabic = store.get(source)
                if not arabic:
                    evidence.append({'file': file, 'source': source, 'cache_hit': False})
                    continue
                bounds = Rect(offset.x + box.x, offset.y + box.y, box.w, box.h)
                if any(bounds.overlap(b[0]) > .65 for b in detected):
                    continue
                avoid = [b for b in candidates if b.overlap(region) < .55]
                avoid += [Rect(offset.x + b.rect.x - 8, offset.y + b.rect.y - 8, b.rect.w + 16, b.rect.h + 16)
                    for b in protected if b.rect.overlap(box) < .1]
                detected.append((bounds, arabic, sample_cell_style(crop, block), avoid))
                evidence.append({'file': file, 'source': source, 'arabic': arabic, 'cache_hit': True,
                    'source_rect': vars(bounds), 'elapsed_ms': round((time.perf_counter() - started) * 1000)})
        for matched in ([False, True] if file == 'steam-00.jpg' else [True]):
            settings.overlay.match_game = matched
            fixture = ScreenshotFixture(image)
            occupied = []
            surfaces = []
            for bounds, arabic, hint, avoid in detected[:settings.max_regions]:
                appearance = effective_appearance(settings.overlay, 'Dressmaker', hint)
                surface = ArabicSurface(appearance, arabic)
                surface.setParent(fixture)
                if appearance.position == 'Replace':
                    surface.fit_to_source(bounds)
                    position = Rect(bounds.x - surface.fit_margin, bounds.y - surface.fit_margin, surface.width(), surface.height())
                else:
                    position = place_overlay(bounds, surface.width(), surface.height(),
                        Rect(0, 0, fixture.width(), fixture.height()), occupied + avoid, appearance.position)
                occupied.append(position)
                surface.move(position.x, position.y)
                surface.show()
                surfaces.append(surface)
            name = file.removesuffix('.jpg') + ('-matched.png' if matched else '-default.png')
            fixture.grab().save(str(directory / name))
            if file == 'steam-02.jpg' and matched:
                surface = max(surfaces, key=lambda s: s.width() * s.height())
                surface.collapsed = False
                control = OverlayInteraction(surface, lambda: None)
                control.setParent(fixture)
                control.setWindowFlags(Qt.Widget)
                control.setGeometry(surface.geometry())
                control.show()
                fixture.grab().save(str(directory / 'steam-02-held-controls.png'))
            fixture.close()
    store.close()
    (directory / 'results.json').write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(evidence, ensure_ascii=True))


asyncio.run(run())
