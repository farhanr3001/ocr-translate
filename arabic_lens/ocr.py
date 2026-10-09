import asyncio
import math
import re
from typing import Protocol
import cv2
import numpy as np
from .models import Rect, TextBlock
from .text import group_lines


class IOcrProvider(Protocol):
    async def recognize(self, image: np.ndarray) -> list[TextBlock]: ...


class WindowsOcrProvider:
    """Windows OCR supplies word bounds, but does not expose confidence scores."""
    def __init__(self):
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine
        self.engine = OcrEngine.try_create_from_language(Language("en-US"))
        if self.engine is None:
            raise RuntimeError("ocr_language")
        self.max_size = OcrEngine.max_image_dimension

    async def recognize(self, image):
        original_image = image
        from winrt.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat, BitmapAlphaMode
        from winrt.windows.storage.streams import Buffer
        h, w = image.shape[:2]
        scale = min(1.0, self.max_size / max(h, w))
        if scale < 1:
            image = cv2.resize(image, (round(w * scale), round(h * scale)))
        bgra = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA) if image.shape[2] == 3 else image.copy()
        bgra[:, :, 3] = 255
        buf = Buffer(bgra.nbytes)
        buf.length = bgra.nbytes
        memoryview(buf)[:] = bgra.tobytes()
        bitmap = SoftwareBitmap.create_copy_with_alpha_from_buffer(buf, BitmapPixelFormat.BGRA8, bgra.shape[1], bgra.shape[0], BitmapAlphaMode.IGNORE)
        try:
            operation = self.engine.recognize_async(bitmap)
            try:
                result = await operation
            except asyncio.CancelledError:
                operation.cancel()
                raise
            lines = []
            from .layout import TextContainerDetector
            panels = TextContainerDetector().detect(image)
            prose = {'you', 'your', 'i', 'my', 'the', 'a', 'an', 'to', 'before', 'after', 'until', 'then', 'find', 'need', 'have', 'wait', 'collect', 'bring', 'is', 'are'}

            def append_words(words, container=None, standalone=False):
                if not words:
                    return
                boxes = [word.bounding_rect for word in words]
                x, y = min(b.x for b in boxes), min(b.y for b in boxes)
                right = max(b.x + b.width for b in boxes)
                bottom = max(b.y + b.height for b in boxes)
                converted = Rect(*(round(v / scale) for v in (container.x, container.y, container.w, container.h))) if container else None
                from .text import clean_source_text
                lines.append(TextBlock(clean_source_text(' '.join(word.text for word in words)),
                    Rect(round(x / scale), round(y / scale), round((right - x) / scale), round((bottom - y) / scale)),
                    standalone=standalone, container=converted))

            for line in result.lines:
                runs = []
                previous_box = None
                is_prose_line = len(line.words) >= 3 and any(w.text.casefold().strip('.,!?') in prose for w in line.words)
                boxes = [word.bounding_rect for word in line.words]
                line_container = None
                if boxes and is_prose_line:
                    x, y = min(b.x for b in boxes), min(b.y for b in boxes)
                    line_container = TextContainerDetector.containing(panels,
                        Rect(round(x), round(y), round(max(b.x+b.width for b in boxes)-x),
                             round(max(b.y+b.height for b in boxes)-y)))
                for word in line.words:
                    box = word.bounding_rect
                    rect = Rect(round(box.x), round(box.y), round(box.width), round(box.height))
                    container = line_container if is_prose_line else TextContainerDetector.containing(panels, rect)
                    # Sentence grammar must not join different desktop columns.
                    separated = previous_box and box.x - (previous_box.x + previous_box.width) > max(24, box.height * (2.5 if is_prose_line else 1.05))
                    if not runs or container != runs[-1][0] or separated:
                        runs.append((container, []))
                    runs[-1][1].append(word)
                    previous_box = box
                for container, words in runs:
                    numeric_count = sum(bool(re.fullmatch(r'\d+(?:\.\d+)?', w.text)) for w in words)
                    value_sentence = any(re.search(r'[$£€%()]|\d+[.,]\d|\d+x\b', w.text) for w in words) or bool(re.match(r'^\s*[•●▪·*\-–]', ' '.join(w.text for w in words)))
                    if numeric_count and len(words) <= min(4, numeric_count * 3) and not value_sentence and not is_prose_line and not any(w.text.casefold() in prose for w in words):
                        # Values stay in the game, untouched. Each label has its
                        # own bounds and inherits its own cell, never a grid union.
                        label = []
                        for word in words:
                            if re.fullmatch(r'\d+(?:\.\d+)?', word.text):
                                append_words(label, container, standalone=True)
                                label = []
                            else:
                                label.append(word)
                        append_words(label, container, standalone=True)
                    else:
                        compact_label = len(words) <= 2 and not any(w.text.casefold() in prose for w in words) and not re.search(r'[.!?]$', words[-1].text)
                        line_height = max(word.bounding_rect.height for word in words)
                        append_words(words, container, standalone=bool(container and container.h < min(70, line_height * 2.2)) or compact_label)
            from .numeric_ocr import recover_numeric_tails
            await recover_numeric_tails(self, original_image, lines)
            return lines
        finally:
            bitmap.close()

    async def recognize_text(self, image):
        """Small selective retries use raw text, without UI-label/value filtering."""
        from winrt.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat, BitmapAlphaMode
        from winrt.windows.storage.streams import Buffer
        bgra = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA) if image.shape[2] == 3 else image.copy()
        bgra[:, :, 3] = 255
        buf = Buffer(bgra.nbytes); buf.length = bgra.nbytes
        memoryview(buf)[:] = bgra.tobytes()
        bitmap = SoftwareBitmap.create_copy_with_alpha_from_buffer(buf, BitmapPixelFormat.BGRA8, bgra.shape[1], bgra.shape[0], BitmapAlphaMode.IGNORE)
        try:
            return (await self.engine.recognize_async(bitmap)).text
        finally:
            bitmap.close()


class OcrService:
    def __init__(self, provider: IOcrProvider, text_filter):
        self.provider, self.text_filter = provider, text_filter
        self.last_lines = []
        self.last_audit = {}

    async def read(self, image, manual=False):
        self.last_lines = await self.provider.recognize(image)
        blocks = self._group(self.last_lines, manual)
        accepted = [b for b in blocks if not self.text_filter.reason(b, manual)]
        # Audit changed crops even when the first pass found some text. Finding
        # a paragraph says nothing about whether nearby small labels were read.
        # The engine calls this only for new/changed pixels, never idle frames.
        h, w = image.shape[:2]
        if max(h, w) < 1600:
            tiles = [(0, 0, image)]
        else:
            # Whole-screen Quick Capture needs local scale for small HUD
            # and paragraph text. OCR on an unscaled 1920px screenshot can
            # miss a label that is clear in a 1100px subimage.
            columns, rows = math.ceil(w / 1200), math.ceil(h / 1200)
            tiles = []
            for row in range(rows):
                for column in range(columns):
                    x0 = max(0, w * column // columns - 80)
                    y0 = max(0, h * row // rows - 80)
                    x1 = min(w, w * (column + 1) // columns + 80)
                    y1 = min(h, h * (row + 1) // rows + 80)
                    tiles.append((x0, y0, image[y0:y1, x0:x1]))
        for x0, y0, tile in tiles:
            scale = min(2.0, 2400 / max(tile.shape[:2]))
            gray = cv2.cvtColor(tile, cv2.COLOR_BGRA2GRAY if tile.shape[2] == 4 else cv2.COLOR_BGR2GRAY)
            enhanced = cv2.createCLAHE(2.0, (8, 8)).apply(gray)
            enhanced = cv2.resize(enhanced, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            retry_lines = await self.provider.recognize(cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGRA))
            for line in retry_lines:
                r = line.rect
                line.rect = Rect(round(r.x / scale) + x0, round(r.y / scale) + y0,
                                 round(r.w / scale), round(r.h / scale))
                if line.container:
                    c = line.container
                    line.container = Rect(round(c.x / scale) + x0, round(c.y / scale) + y0,
                                          round(c.w / scale), round(c.h / scale))
                # Merge at OCR-line granularity before paragraph grouping.
                # A recovered wrapped line joins its original paragraph;
                # overlapping OCR passes cannot create double overlays.
                merge_recognized_line(self.last_lines, line)
        # Audit remaining text-shaped strokes at local scale. Whole-crop
        # recognition can miss one small label even after finding its peers.
        residual = residual_text_regions(image, self.last_lines)
        recovered = 0
        for area in residual:
            crop = image[area.y:area.bottom, area.x:area.right]
            scale = min(3.0, 2400 / max(crop.shape[:2]))
            enlarged = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            for line in await self.provider.recognize(enlarged):
                r = line.rect
                line.rect = Rect(area.x + round(r.x/scale), area.y + round(r.y/scale), round(r.w/scale), round(r.h/scale))
                line.container = None
                if merge_recognized_line(self.last_lines, line):
                    recovered += 1
        blocks = self._group(self.last_lines, manual)
        accepted = [b for b in blocks if not self.text_filter.reason(b, manual)]
        self.last_audit = {'lines': len(self.last_lines), 'accepted': len(accepted),
            'residual_candidates': len(residual), 'recovered_lines': recovered,
            'filtered': [(b.text, self.text_filter.reason(b, manual)) for b in blocks if self.text_filter.reason(b, manual)]}
        return accepted

    def _group(self, lines, manual):
        # Filter complete reconstructed blocks, not individual wrapped lines.
        from .text import align_list_columns
        return align_list_columns(group_lines(lines))


def residual_text_regions(image, recognized):
    """Find unaccounted line-sized stroke clusters, not full picture regions."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY if image.shape[2] == 4 else cv2.COLOR_BGR2GRAY)
    edges = cv2.convertScaleAbs(cv2.Sobel(gray, cv2.CV_16S, 1, 0, ksize=3))
    mask = (edges > 75).astype(np.uint8) * 255
    h, w = mask.shape
    for line in recognized:
        r = line.rect
        mask[max(0,r.y-3):min(h,r.bottom+3),max(0,r.x-3):min(w,r.right+3)] = 0
    joined = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT,(13,3)))
    _, _, stats, _ = cv2.connectedComponentsWithStats(joined)
    regions = []
    for x,y,rw,rh,pixels in stats[1:]:
        if rw < 25 or not 7 <= rh <= 65 or rw < rh*1.5 or pixels/(rw*rh) < .16:
            continue
        # Require several distinct glyph-like components before trying OCR.
        n, _, glyphs, _ = cv2.connectedComponentsWithStats(mask[y:y+rh,x:x+rw])
        if sum(1 for _,_,gw,gh,area in glyphs[1:] if area >= 3 and gh >= 4 and gw < rh*2) < 3:
            continue
        left, top = max(0,int(x)-8), max(0,int(y)-8)
        regions.append(Rect(left,top,min(w,int(x+rw)+8)-left,min(h,int(y+rh)+8)-top))
    return regions


def merge_recognized_line(lines, candidate):
    """Keep a complementary pass when it recovers the rest of a partial line."""
    from .text import normalize
    overlapping = [line for line in lines if candidate.rect.overlap(line.rect) > .35]
    if not overlapping:
        lines.append(candidate)
        return True
    if len(overlapping) == 1:
        old = overlapping[0]
        previous, improved = normalize(old.text), normalize(candidate.text)
        if (not old.standalone and previous and previous != improved and previous in improved
                and candidate.rect.w > old.rect.w * 1.08
                and candidate.rect.h <= old.rect.h * 1.4
                and abs(candidate.rect.y-old.rect.y) < max(4,old.rect.h*.25)):
            lines[lines.index(old)] = candidate
            return True
    return False
