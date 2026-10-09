import asyncio
import json
import time
import sys
import argparse
from pathlib import Path
from dataclasses import asdict
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
from arabic_lens.ocr import WindowsOcrProvider, OcrService
from arabic_lens.config import Settings
from arabic_lens.detection import TextRegionDetector
from arabic_lens.text import TextFilterService, normalize, belongs_to_region

parser = argparse.ArgumentParser()
parser.add_argument('--directory', default='artifacts/dressmaker')
parser.add_argument('--screenshots-only', action='store_true')
args = parser.parse_args()


async def evaluate():
    directory = Path(args.directory)
    provider = WindowsOcrProvider()
    settings = Settings()
    filter_service = TextFilterService(settings)
    ocr = OcrService(provider, filter_service)
    detector = TextRegionDetector()
    report = []
    files = sorted(directory.glob('steam-*.jpg'))
    if not args.screenshots_only:
        files += sorted((directory / 'trailer').glob('frame-*.jpg'))
    for path in files:
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        started = time.perf_counter()
        full = await provider.recognize(image)
        full_ms = round((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        regions = detector.detect(image, settings.sensitivity)
        detect_ms = round((time.perf_counter() - started) * 1000)
        watch = []
        for rank, region in enumerate(regions[:settings.max_regions]):
            x, y = max(0, region.x - 24), max(0, region.y - 64)
            blocks = await ocr.read(image[y:min(image.shape[0], region.bottom + 100), x:min(image.shape[1], region.right + 24)])
            from arabic_lens.models import Rect
            local = Rect(region.x - x, region.y - y, region.w, region.h)
            blocks = [b for b in blocks if belongs_to_region(b, local)]
            for block in blocks:
                watch.append({'text': block.text, 'rank': rank, 'rect': asdict(region), 'key': normalize(block.text)})
        item = {'file': str(path), 'size': list(image.shape[:2]), 'full_ocr_ms': full_ms, 'detect_ms': detect_ms,
            'full': [{'text': b.text, 'rect': asdict(b.rect), 'filter_reason': filter_service.reason(b)} for b in full],
            'candidates': [asdict(r) for r in regions], 'watch': watch}
        report.append(item)
        print(json.dumps({'file': path.name, 'ocr_ms': full_ms, 'detect_ms': detect_ms, 'watch': [b['text'] for b in watch]}, ensure_ascii=True))
    (directory / 'evaluation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

asyncio.run(evaluate())
