from dataclasses import dataclass, field
import cv2
import numpy as np
from .models import Rect


def fingerprint(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY if image.shape[2] == 4 else cv2.COLOR_BGR2GRAY)
    return cv2.resize(gray, (48, 20), interpolation=cv2.INTER_AREA)


def difference(a, b):
    return float(np.mean(cv2.absdiff(a, b)))


class TextRegionDetector:
    """Cheap downscaled edge morphology groups likely text before OCR."""
    def detect(self, image, sensitivity=50):
        h, w = image.shape[:2]
        scale = min(1, 1280 / w)
        small = cv2.resize(image, (round(w * scale), round(h * scale)))
        gray = cv2.cvtColor(small, cv2.COLOR_BGRA2GRAY if small.shape[2] == 4 else cv2.COLOR_BGR2GRAY)
        edges = cv2.Sobel(gray, cv2.CV_16S, 1, 0, ksize=3)
        edges = cv2.convertScaleAbs(edges)
        _, mask = cv2.threshold(edges, max(25, 105 - sensitivity), 255, cv2.THRESH_BINARY)
        # Thin horizontal joining keeps glyphs together without bridging text
        # into an ornate tooltip border or surrounding game artwork.
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 1)))
        # Text inside bordered dialogue/tooltips is nested within the panel's
        # contour. RETR_EXTERNAL silently discarded those lines in Dressmaker.
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        lines = []
        for c in contours:
            x, y, rw, rh = cv2.boundingRect(c)
            if rw < 35 or rh < 7 or rh > 90 or rw / max(1, rh) < 1.7:
                continue
            density = np.count_nonzero(mask[y:y+rh, x:x+rw]) / (rw * rh)
            if not .15 < density:
                continue
            lines.append(Rect(x, y, rw, rh))
        # Fixed pixel dilation alone splits words in large desktop/game fonts.
        # Join nearby glyph runs on the same baseline using their text height,
        # while retaining the thin mask that avoids decorative panel borders.
        rows = []
        for line in sorted(lines, key=lambda r: (r.x, r.y)):
            match = next((r for r in rows
                if min(r.h, line.h) >= 20
                and max(0, min(r.bottom, line.bottom) - max(r.y, line.y)) > min(r.h, line.h) * .65
                and max(r.h, line.h) < min(r.h, line.h) * 2.2
                and -4 <= line.x - r.right <= max(r.h, line.h) * 3), None)
            if match:
                rows[rows.index(match)] = match.union(line)
            else:
                rows.append(line)
        lines = [r for r in rows if r.w >= 35 and r.w / max(1, r.h) >= 1.7]
        groups = []
        for line in sorted(lines, key=lambda r: (r.y, r.x)):
            match = next((g for g in groups if -4 <= line.y - g.bottom < max(22, line.h * 1.6) and max(0, min(g.right, line.right) - max(g.x, line.x)) > min(g.w, line.w) * .35 and g.h < gray.shape[0] * .35), None)
            if match:
                groups[groups.index(match)] = match.union(line)
            else:
                groups.append(line)
        result = []
        for r in sorted(groups, key=lambda r: r.w * r.h, reverse=True):
            x, y = max(0, round(r.x / scale) - 10), max(0, round(r.y / scale) - 10)
            candidate = Rect(x, y, min(w - x, round(r.w / scale) + 20), min(h - y, round(r.h / scale) + 20))
            if not any(candidate.overlap(existing) > .55 for existing in result):
                result.append(candidate)
            # A fixed top-ten cutoff silently loses short dialogue lines and
            # labels in dense documents. The caller owns its OCR work budget;
            # return every distinct likely-text region in this changed crop.
        return result


@dataclass
class TrackedRegion:
    id: str
    rect: Rect
    hash: np.ndarray
    changed: float
    seen: float
    revision: int = 0
    processed: bool = False
    attempted: float = 0
    delivered: set = field(default_factory=set)


class RegionTracker:
    def __init__(self):
        self.regions = {}
        self.sequence = 0

    def update(self, candidates, image, now, threshold=9, previous_image=None):
        matched, invalidated = set(), []
        for rect in candidates:
            crop = image[rect.y:rect.bottom, rect.x:rect.right]
            if not crop.size:
                continue
            available = [r for r in self.regions.values() if r.id not in matched and r.rect.overlap(rect) > .65 and max(r.rect.w* r.rect.h, rect.w * rect.h) / max(1, min(r.rect.w * r.rect.h, rect.w * rect.h)) < 1.7]
            region = max(available, key=lambda r: r.rect.overlap(rect), default=None)
            if region is not None and previous_image is not None and previous_image.shape == image.shape:
                old = previous_image[rect.y:rect.bottom, rect.x:rect.right]
                if old.shape == crop.shape and np.count_nonzero(np.any(
                        np.abs(crop.astype(np.int16) - old.astype(np.int16)) > 12, axis=2)) < 3:
                    # Motion elsewhere in the same tile cannot change this
                    # region's revision or restart its OCR/translation.
                    region.seen = now
                    matched.add(region.id)
                    continue
            hashed = fingerprint(crop)
            if region is None:
                self.sequence += 1
                region = TrackedRegion(str(self.sequence), rect, hashed, now, now)
                self.regions[region.id] = region
            else:
                if difference(region.hash, hashed) > threshold:
                    region.changed, region.processed = now, False
                    region.revision += 1
                    region.delivered.clear()
                    invalidated.append(region.id)
                # Anchor small box motion. Keep the capture box fresh on larger motion.
                if abs(rect.x - region.rect.x) > 6 or abs(rect.y - region.rect.y) > 6 or abs(rect.w - region.rect.w) > 12 or abs(rect.h - region.rect.h) > 12:
                    region.rect = rect
                # Compare against the stability baseline, not the previous frame; catches typewriter text.
                if region.changed == now:
                    region.hash = hashed
                region.seen = now
            matched.add(region.id)
        return invalidated + self.expire(now)

    def expire(self, now):
        """Retire vanished text without rehashing unchanged screen areas."""
        removed = []
        for key, region in list(self.regions.items()):
            if now - region.seen > .6:
                removed.append(key)
                del self.regions[key]
        return removed

    def ready(self, now, stability_ms, cooldown_ms, limit):
        return sorted([r for r in self.regions.values() if not r.processed and now - r.changed >= stability_ms / 1000 and now - r.attempted >= cooldown_ms / 1000], key=lambda r: r.rect.w * r.rect.h, reverse=True)[:limit]

    def clear(self):
        self.regions.clear()
