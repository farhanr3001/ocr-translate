"""Exercise production OCR on a supplied screenshot; no desktop interaction."""
import asyncio
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
from arabic_lens.config import Settings
from arabic_lens.engine import whole_screen_tiles, contained_text
from arabic_lens.models import Rect
from arabic_lens.ocr import OcrService, WindowsOcrProvider
from arabic_lens.text import TextFilterService

async def main():
    source = Path(sys.argv[1])
    output = Path(sys.argv[2]); output.mkdir(parents=True, exist_ok=True)
    image = cv2.imread(str(source)); h, w = image.shape[:2]
    settings = Settings()
    ocr = OcrService(WindowsOcrProvider(), TextFilterService(settings))
    report = {}
    for mode in ('selection', 'fullscreen'):
        start = time.perf_counter(); blocks = []
        if mode == 'selection':
            blocks = await ocr.read(image, manual=True)
        else:
            for core, bounds, _ in whole_screen_tiles(Rect(0,0,w,h), (180,320)):
                found = await ocr.read(image[bounds.y:bounds.bottom,bounds.x:bounds.right])
                for block in found:
                    r = block.rect
                    block.rect = Rect(r.x+bounds.x,r.y+bounds.y,r.w,r.h)
                    x,y = block.rect.x+r.w//2, block.rect.y+r.h//2
                    if core.x <= x < core.right and core.y <= y < core.bottom:
                        blocks.append(block)
        blocks = [b for b in blocks if not any(other is not b and contained_text(b.text,b.rect,other.text,other.rect) for other in blocks)]
        report[mode] = {'seconds':round(time.perf_counter()-start,3), 'blocks':[asdict(b) for b in blocks]}
        rendered = image.copy()
        for index, block in enumerate(blocks):
            r=block.rect
            cv2.rectangle(rendered,(r.x,r.y),(r.right,r.bottom),(180,230,20),1)
            cv2.putText(rendered,str(index),(r.x,max(12,r.y-3)),cv2.FONT_HERSHEY_SIMPLEX,.4,(180,230,20),1)
        cv2.imwrite(str(output / (mode+'.png')),rendered)
    (output/'coverage.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({mode:{'seconds':data['seconds'],'blocks':len(data['blocks'])} for mode,data in report.items()}))

if __name__=='__main__': asyncio.run(main())
