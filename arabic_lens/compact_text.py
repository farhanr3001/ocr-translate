"""Recover short, high-contrast labels bounded by a contrasting backing."""
import cv2
import numpy as np

from .models import Rect
from .small_text import _language


def has_dark_backing(image, rect):
    """Tell a transient bright label on a dark card from ordinary typed text."""
    h, w = image.shape[:2]
    if rect.y < 5 or rect.bottom + 5 > h or not 9 <= rect.h <= 34 or rect.w < 28:
        return False
    top, bottom = max(0, rect.y - 22), min(h, rect.bottom + 22)
    x0, x1 = max(0, rect.x - 22), min(w, rect.right + 22)
    crop = image[top:bottom, x0:x1]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGRA2GRAY if crop.shape[2] == 4 else cv2.COLOR_BGR2GRAY)
    y, end = rect.y - top, rect.bottom - top
    left, right = rect.x - x0, rect.right - x0
    above = gray[y - 3:y, left:right]
    below = gray[end:end + 3, left:right]
    text = gray[y:end, left:right]
    base = max(float(np.median(above)), float(np.median(below)))
    if base > 98 or not .07 <= (text >= 172).mean() <= .55:
        return False
    outside = (gray[:max(0, y - 7), left:right], gray[end + 7:, left:right],
               gray[y:end, :max(0, left - 7)], gray[y:end, right + 7:])
    return any(band.size and (band > base + 20).mean() >= .42 for band in outside)


def label_regions(gray):
    dark = (gray < 88).astype(np.float32)
    background = cv2.boxFilter(dark, -1, (25, 17))
    mask = ((gray >= 165) & (background > .42)).astype(np.uint8)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    _, _, widths, heights, sizes = stats.T
    glyph = ((heights >= 6) & (heights <= 31) & (widths <= 31)
             & (sizes >= 7) & (sizes <= widths * heights * .92))
    glyph[0] = False
    ink = glyph[labels].astype(np.uint8)
    joined = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((3, 22), np.uint8))
    contours, _ = cv2.findContours(cv2.dilate(joined, np.ones((3, 4), np.uint8)),
                                  cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if not (32 <= w <= 520 and 8 <= h <= 34 and w > 2 * h):
            continue
        below = gray[y + h:y + h + 4, x:x + w]
        if not below.size or (below < 88).mean() < .65 or not .06 < ink[y:y + h, x:x + w].mean() < .58:
            continue
        base = float(np.median(below))
        # Avoid pulling words out of ordinary dark-background paragraphs.
        bands = (gray[top:top + 3, max(0, x - 4):x + w + 4]
                 for top in (y - 9, y - 5, y + h + 3, y + h + 7, y + h + 11)
                 if 0 <= top <= gray.shape[0] - 3)
        if any((band > base + 24).mean() >= .45 for band in bands):
            yield Rect(x, y, w, h)


async def recover_compact_labels(provider, image, lines):
    gray = cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY if image.shape[2] == 4 else cv2.COLOR_BGR2GRAY)
    photo = Rect(0, 0, gray.shape[1], gray.shape[0])
    samples = []
    for label in label_regions(gray):
        matched = [line for line in lines if label.overlap(line.rect) > .5
                   and label.intersect(line.rect).w >= min(label.w, line.rect.w) * .65]
        if (len(matched) == 1 and matched[0].rect.w >= label.w * .86
                and not _language(matched[0].text)[1]):
            continue
        if any(line.rect.w > label.w * 1.22 for line in matched):
            continue
        # Crop out sprites and buttons surrounding the glyphs. Resize with
        # nearest-neighbor to preserve the strokes of bitmap fonts.
        area = Rect(label.x - 4, label.y - 3, label.w + 8, label.h + 6).intersect(photo)
        patch = gray[area.y:area.bottom, area.x:area.right]
        patch = cv2.resize(patch, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
        samples.append((area, patch, matched))
        if len(samples) >= 6:
            break
    if not samples:
        return
    canvas = np.full((sum(patch.shape[0] + 24 for _, patch, _ in samples),
                      max(patch.shape[1] for _, patch, _ in samples) + 24), 28, np.uint8)
    positions = []
    y = 12
    for area, patch, matched in samples:
        h, w = patch.shape
        canvas[y:y + h, 12:12 + w] = patch
        positions.append((y, y + h, area, matched))
        y += h + 24
    for block in await provider.recognize(cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGRA)):
        rect = block.rect
        choice = next((entry for entry in positions if entry[0] <= rect.y < rect.bottom <= entry[1]), None)
        if choice is None:
            continue
        y, _, area, matched = choice
        score, errors = _language(block.text)
        if errors or score <= 0 or (matched and score < max(_language(line.text)[0] for line in matched)):
            continue
        block.rect = Rect(area.x + (rect.x - 12) // 2, area.y + (rect.y - y) // 2,
                          round(rect.w / 2), round(rect.h / 2)).intersect(area)
        if block.rect.w < area.w * .64:
            continue
        block.container = matched[0].container if len(matched) == 1 else None
        block.standalone = True
        lines[:] = [line for line in lines if line not in matched]
        lines.append(block)
