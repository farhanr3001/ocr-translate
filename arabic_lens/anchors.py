"""Bounded visual source tracking; no OCR, input hooks or app-specific APIs."""
from dataclasses import dataclass
import time
import cv2
import numpy as np
from .models import Rect


@dataclass
class Anchor:
    rect: Rect
    pixels: np.ndarray
    source_window: tuple
    expires: float
    source_text: str = ''
    capture_bounds: Rect | None = None


class VisualAnchors:
    def __init__(self):
        self.items = {}

    def add(self, result, image, box, duration, capture_bounds=None):
        if not result.source_window and capture_bounds is None:
            return
        crop = image[max(0, box.y):min(image.shape[0], box.bottom), max(0, box.x):min(image.shape[1], box.right)]
        if crop.size and box.w >= 12 and box.h >= 8:
            # Small text patches only, never whole screens.
            gray = cv2.cvtColor(crop, cv2.COLOR_BGRA2GRAY if crop.shape[2] == 4 else cv2.COLOR_BGR2GRAY)
            if gray.nbytes > 1_000_000:
                return
            pixels = gray.copy()
            if pixels.std() >= 3:
                self.items[result.id] = Anchor(result.rect, pixels, result.source_window,
                    time.monotonic() + duration, result.source, capture_bounds)
        while len(self.items) > 48 or sum(item.pixels.nbytes for item in self.items.values()) > 8_000_000:
            self.items.pop(next(iter(self.items)))

    def update(self, image, bounds, now=None, keys=None):
        now = time.monotonic() if now is None else now
        gray = cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY if image.shape[2] == 4 else cv2.COLOR_BGR2GRAY)
        scale = min(.5, 960 / image.shape[1])
        frame = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        moved, lost = [], []
        for key, anchor in list(self.items.items()):
            if keys is not None and key not in keys:
                continue
            if now > anchor.expires:
                self.items.pop(key, None); lost.append(key); continue
            patch = cv2.resize(anchor.pixels, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            h, w = patch.shape
            x, y = round((anchor.rect.x - bounds.x) * scale), round((anchor.rect.y - bounds.y) * scale)
            nx, ny = anchor.rect.x - bounds.x, anchor.rect.y - bounds.y
            native_h, native_w = anchor.pixels.shape
            current = gray[ny:ny+native_h, nx:nx+native_w] if nx >= 0 and ny >= 0 else None
            if current is not None and self.identical(current, anchor.pixels):
                continue
            # Scroll search: same column, full vertical viewport. At most 960px
            # wide; only changed frames enter this work and matching never OCRs.
            left, right = max(0, x - round(160 * scale)), min(frame.shape[1], x + w + round(160 * scale))
            search = frame[:, left:right]
            if search.shape[0] < h or search.shape[1] < w:
                self.items.pop(key, None); lost.append(key); continue
            scores = cv2.matchTemplate(search, patch, cv2.TM_CCOEFF_NORMED)
            _, confidence, _, location = cv2.minMaxLoc(scores)
            if confidence < .55:
                self.items.pop(key, None); lost.append(key); continue
            candidate_x, candidate_y = round((left + location[0]) / scale), round(location[1] / scale)
            fine_x, fine_y = max(0, candidate_x - 4), max(0, candidate_y - 4)
            fine = gray[fine_y:min(gray.shape[0], candidate_y + native_h + 5), fine_x:min(gray.shape[1], candidate_x + native_w + 5)]
            if fine.shape[0] < native_h or fine.shape[1] < native_w:
                self.items.pop(key, None); lost.append(key); continue
            _, score, _, exact = cv2.minMaxLoc(cv2.matchTemplate(fine, anchor.pixels, cv2.TM_CCOEFF_NORMED))
            exact_x, exact_y = fine_x + exact[0], fine_y + exact[1]
            if score < .98 or not self.identical(gray[exact_y:exact_y+native_h, exact_x:exact_x+native_w], anchor.pixels):
                self.items.pop(key, None); lost.append(key); continue
            new = Rect(bounds.x + exact_x, bounds.y + exact_y, anchor.rect.w, anchor.rect.h)
            if abs(new.x - anchor.rect.x) > 2 or abs(new.y - anchor.rect.y) > 2:
                moved.append((key, anchor.rect, new)); anchor.rect = new
        return moved, lost

    def clear(self):
        self.items.clear()

    @staticmethod
    def identical(current, original):
        if current.shape != original.shape:
            return False
        if np.count_nonzero(np.abs(current.astype(np.int16) - original.astype(np.int16)) > 24) <= 12:
            return True
        # Hover/focus often changes a label's colour while keeping its glyph
        # edges. Preserve that text anchor; OCR will still decide whether the
        # words themselves changed before replacing the Arabic overlay.
        original_edges = cv2.Canny(original, 40, 100)
        current_edges = cv2.Canny(current, 40, 100)
        count_original = np.count_nonzero(original_edges)
        count_current = np.count_nonzero(current_edges)
        if min(count_original, count_current) < 16:
            return False
        kernel = np.ones((3, 3), dtype=np.uint8)
        near_current = cv2.dilate(current_edges, kernel)
        near_original = cv2.dilate(original_edges, kernel)
        return (np.count_nonzero(original_edges & near_current) / count_original >= .87
            and np.count_nonzero(current_edges & near_original) / count_current >= .87)
