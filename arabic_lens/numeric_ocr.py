"""Selective recovery of long numeric tails missed by Windows word recognition."""
import re
import cv2
import numpy as np
from .models import Rect


async def recover_numeric_tails(provider, image, lines):
    for block in lines:
        if block.standalone or not block.text.rstrip().endswith(':'):
            continue
        r = block.rect
        top, bottom = max(0, r.y - 4), min(image.shape[0], r.bottom + 7)
        left, right = r.right + 2, min(image.shape[1], r.right + 400)
        roi = image[top:bottom, left:right]
        if not roi.size:
            continue
        # Never annex an already-recognized neighbouring cell/label.
        if any(other is not block and other.rect.x >= left and other.rect.y < bottom and other.rect.bottom > top for other in lines):
            continue
        gray = cv2.cvtColor(roi, cv2.COLOR_BGRA2GRAY if roi.shape[2] == 4 else cv2.COLOR_BGR2GRAY)
        background = float(np.median(gray))
        mask = (np.abs(gray.astype(float) - background) > 90).astype(np.uint8) * 255
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        glyphs = sorted([cv2.boundingRect(c) for c in contours if cv2.boundingRect(c)[2] >= 1 and cv2.boundingRect(c)[3] >= 2])
        if len(glyphs) < 6 or len(glyphs) > 28 or glyphs[0][0] > 25:
            continue
        height = np.median([g[3] for g in glyphs])
        if height < 6 or height > r.h * 2:
            continue
        # Wide gaps mean several independent controls, not one numeric tail.
        if any(b[0] - (a[0] + a[2]) > height for a, b in zip(glyphs, glyphs[1:])):
            continue
        groups, punctuation, group = [], [], []
        for glyph in glyphs:
            if glyph[3] < height * .55:
                if not group:
                    groups = []; break
                groups.append(group); group = []
                punctuation.append(',' if glyph[3] >= 3 else '.')
            else:
                group.append(glyph)
        if group:
            groups.append(group)
        if len(groups) < 2:
            continue  # Recovery is intentionally limited to grouped numeric values.
        parts, currency = [], ''
        valid = True
        first_currency = None
        for index, digits in enumerate(groups):
            x = digits[0][0]; end = digits[-1][0] + digits[-1][2]
            chunk = roi[:, x:end].copy()
            if index and currency and first_currency is not None:
                gap = np.full((roi.shape[0], 3, roi.shape[2]), round(background), np.uint8)
                chunk = np.concatenate([first_currency, gap, chunk], axis=1)
            chunk = cv2.resize(chunk, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
            chunk = cv2.copyMakeBorder(chunk, 16, 16, 16, 16, cv2.BORDER_CONSTANT, value=tuple([round(background)] * chunk.shape[2]))
            recognized = re.sub(r'\s+', '', await provider.recognize_text(chunk))
            expected = len(digits)
            if index == 0 and recognized[:1] in '$£€':
                currency, recognized = recognized[0], recognized[1:]
                symbol = digits[0]
                first_currency = roi[:, symbol[0]:symbol[0] + symbol[2]].copy()
                expected -= 1
            elif index and currency:
                recognized = recognized[1:]  # Discard only the added context glyph.
            recognized = recognized.translate(str.maketrans('OoIl|', '00111'))
            if not recognized.isdigit() or len(recognized) != expected:
                valid = False; break
            parts.append(recognized)
        if valid and len(parts) == len(groups):
            number = currency + parts[0]
            for separator, part in zip(punctuation, parts[1:]):
                number += separator + part
            block.text += ' ' + number
            block.rect = block.rect.union(Rect(left + glyphs[0][0], top + min(g[1] for g in glyphs), glyphs[-1][0] + glyphs[-1][2] - glyphs[0][0], max(g[1]+g[3] for g in glyphs) - min(g[1] for g in glyphs)))
