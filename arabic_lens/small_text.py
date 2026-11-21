"""Recover fractured or missing rows of small text from the captured pixels."""

import re
from difflib import SequenceMatcher

import cv2
import numpy as np

from .models import Rect
from .text import normalize, plausible_word


def _rows(gray):
    # A horizontal gradient without vertical smoothing keeps adjacent baselines
    # separate, even when only one or two blank pixels divide them.
    edges = cv2.convertScaleAbs(cv2.Sobel(gray, cv2.CV_16S, 1, 0, ksize=1))
    ink = (edges > 40).astype(np.uint8)
    joined = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((1, 13), np.uint8))
    contours, _ = cv2.findContours(joined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rows = []
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        if 5 <= height <= 12 and width >= max(26, height * 3):
            pixels = ink[y:y + height, x:x + width]
            if .10 <= pixels.mean() <= .80:
                rows.append(Rect(x, y, width, height))
    return sorted(rows, key=lambda row: (row.y, row.x))


def _on_row(rect, row):
    common = rect.intersect(row)
    return (abs(rect.y + rect.h / 2 - row.y - row.h / 2) <= row.h * .45
            and common.h >= min(rect.h, row.h) * .5
            and common.w >= min(rect.w, row.w) * .75)


def _covers_row(rect, row):
    # A missing short word can leave almost the whole line's width covered.
    return (rect.intersect(row).w >= row.w * .86
            and rect.x <= row.x + 3 and rect.right >= row.right - 3)


def _language(text):
    words = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?|\d+(?:[:.,/]\d+)*", text)
    errors = sum(not (word[0].isdigit() or plausible_word(word)) for word in words)
    errors += len(re.findall(r"[^A-Za-z0-9\s.,:?!'’\-()/$%]", text))
    errors += bool(re.search(r'[a-zA-Z]\d|\d[a-zA-Z]', text))
    errors += bool(re.search(r'\b[a-z]{2,}[.!?][A-Za-z]\b', text))
    return len(words) - 2 * errors, errors


def _discard_ghosts(lines, rows, replacements):
    """Remove a second read of a row misplaced between the real pixel bands."""
    for line in lines.copy():
        if any(_on_row(line.rect, row) for row in rows):
            continue
        fragment = normalize(line.text)
        for row, block in replacements:
            repaired = normalize(block.text)
            if (fragment and abs(line.rect.y - row.y) <= row.h + 2
                    and line.rect.intersect(row).w >= line.rect.w * .85
                    and (fragment in repaired or SequenceMatcher(None, fragment, repaired).ratio() >= .72)):
                lines.remove(line)
                break


async def recover_small_rows(provider, image, lines, value_boxes):
    if lines and all(line.rect.h > 12 for line in lines):
        return 0
    gray = cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY if image.shape[2] == 4 else cv2.COLOR_BGR2GRAY)
    rows = _rows(gray)
    candidates = []
    for row in rows:
        original = [line for line in lines if _on_row(line.rect, row)]
        complete = [line for line in original if _covers_row(line.rect, row)]
        if ((len(original) == 1 and complete and not _language(complete[0].text)[1])
                or any(line.container for line in original)
                or sum(line.standalone and len(line.text) > 2 for line in original) > 1
                or any(_on_row(value.rect, row) for value in value_boxes)):
            continue
        candidates.append((row, original))
    # Adjacent candidates usually share a crop. Work stays local to the
    # detected rows and never scales an entire fullscreen frame.
    pending = candidates
    replacements = []
    while pending:
        seed, _ = pending[0]
        bounds = Rect(seed.x - 20, seed.y - 16, seed.w + 40, seed.h + 32)
        bounds = bounds.intersect(Rect(0, 0, gray.shape[1], gray.shape[0]))
        selected = [(row, old) for row, old in pending if row.intersect(bounds) == row]
        pending = [item for item in pending if item not in selected]
        crop = gray[bounds.y:bounds.bottom, bounds.x:bounds.right]
        contrast = cv2.normalize(crop, None, 0, 255, cv2.NORM_MINMAX)
        possible = {row: [] for row, _ in selected}
        for factor in (3.0, 4.0):
            scale = min(factor, 2400 / max(crop.shape))
            enlarged = cv2.resize(contrast, None, fx=scale, fy=scale, interpolation=cv2.INTER_LANCZOS4)
            reread = await provider.recognize(cv2.cvtColor(enlarged, cv2.COLOR_GRAY2BGRA))
            for line in reread:
                rect = line.rect
                left, top = round(rect.x / scale) + bounds.x, round(rect.y / scale) + bounds.y
                right = round(rect.right / scale) + bounds.x
                bottom = round(rect.bottom / scale) + bounds.y
                line.rect = Rect(left, top, right - left, bottom - top)
                line.container = None
                for row, original in selected:
                    if (_on_row(line.rect, row) and line.rect.intersect(row).w >= row.w * .83
                            and line.rect.h <= row.h * 1.45 and line.text.strip()
                            and all(old.rect.intersect(line.rect).w >= old.rect.w * .8 for old in original)):
                        possible[row].append(line)
            if all(any(not _language(line.text)[1] for line in hits) for hits in possible.values()):
                break
        for row, original in selected:
            if not possible[row]:
                continue
            replacement = max(possible[row], key=lambda line: _language(line.text)[0])
            if (len(original) == 1 and _covers_row(original[0].rect, row)
                    and _language(replacement.text)[0] <= _language(original[0].text)[0]):
                continue
            if any(line not in original and _on_row(line.rect, row)
                   and line.rect.overlap(replacement.rect) > .45 for line in lines):
                continue
            lines[:] = [line for line in lines if line not in original] + [replacement]
            replacements.append((row, replacement))
    _discard_ghosts(lines, rows, replacements)
    return len(replacements)
