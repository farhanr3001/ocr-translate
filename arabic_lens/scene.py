"""OCR scene reconciliation for Watch zones and Quick selections.

Each OCR read of an area is the truth for that area. Previous segments are
matched to the newly read blocks: a growing or edited line keeps its identity
(typing), fragments absorbed into a longer line are retired (no ghosts), blocks
that are really gone are removed, and a segment OCR merely missed survives only
while its pixels are unchanged. Translation is requested once the text has
settled, so partially typed words are not translated on every keystroke.
"""
from dataclasses import dataclass, field
from difflib import SequenceMatcher
import re

import cv2
import numpy as np

from .anchors import VisualAnchors
from .models import Rect, TextBlock
from .text import normalize, plausible_word

ENDS_PHRASE = re.compile(r'[.!?:;…"”\')\]]$')


def similarity(a, b):
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def text_related(a, b):
    """Same words being typed, edited or extended rather than new content."""
    if not a or not b:
        return False
    return a.startswith(b) or b.startswith(a) or a in b or b in a or similarity(a, b) >= .6


def _gray(image):
    if image is None or not image.size:
        return None
    if image.ndim == 2:
        return image
    return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY if image.shape[2] == 4 else cv2.COLOR_BGR2GRAY)


def crop(image, rect):
    if image is None:
        return None
    h, w = image.shape[:2]
    x0, y0 = max(0, rect.x), max(0, rect.y)
    x1, y1 = min(w, rect.right), min(h, rect.bottom)
    if x1 <= x0 or y1 <= y0:
        return None
    return image[y0:y1, x0:x1]


def first_line_height(block):
    line = getattr(block, '_last_line', None)
    height = block.rect.h
    if line is not None:
        height = min(height, line.rect.h)
    return max(8, height)


def blank(gray):
    """No strokes at all: whatever was read here is not text (any more)."""
    return gray is None or not gray.size or int(gray.max()) - int(gray.min()) < 12


def locate(segment, image):
    """Find a segment's unchanged pixels after vertical scrolling."""
    template = segment.pixels
    gray = _gray(image)
    if gray is None or template is None or template.size == 0:
        return None
    th, tw = template.shape
    x0 = max(0, segment.rect.x - 12)
    x1 = min(gray.shape[1], segment.rect.right + 12)
    strip = gray[:, x0:x1]
    if strip.shape[0] < th or strip.shape[1] < tw or template.std() < 3:
        return None
    _, score, _, (x, y) = cv2.minMaxLoc(cv2.matchTemplate(strip, template, cv2.TM_CCOEFF_NORMED))
    if score < .97:
        return None
    if not VisualAnchors.identical(strip[y:y + th, x:x + tw], template):
        return None
    return Rect(x0 + x, y, segment.rect.w, segment.rect.h)


@dataclass
class Segment:
    id: str
    block: TextBlock
    rect: Rect
    key: str
    changed: float
    confirmed: float
    line_height: int
    pixels: np.ndarray | None = None
    shown_key: str = ''
    shown_source: str = ''
    pending_key: str = ''
    seen_below: bool = False  # A read showed the area beneath its last line.
    task: object = None
    failures: int = 0
    retry_after: float = 0.0
    attempts: dict = field(default_factory=dict)

    @property
    def text(self):
        return self.block.text


def settle_delay(text, base=.35):
    """Seconds a segment's words must stay unchanged before translation.

    Complete phrases translate quickly. A line that still ends mid-word (a
    fragment or a non-word) waits longer, because it is usually being typed.
    """
    stripped = text.strip()
    letters = re.findall(r'[A-Za-z]', stripped)
    if len(letters) <= 2:
        return max(base, .9)
    if ENDS_PHRASE.search(stripped):
        return base
    words = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", stripped)
    last = words[-1] if words else ''
    if not last or (len(last) <= 2 and last.casefold() not in {'a', 'i', 'an', 'at', 'be', 'by', 'do', 'go', 'he',
            'if', 'in', 'is', 'it', 'me', 'my', 'no', 'of', 'oh', 'ok', 'on', 'or', 'so', 'to', 'up', 'us', 'we'}):
        return max(base, .8)
    if not plausible_word(last):
        return max(base, .75)
    return max(base, .5)


class TextScene:
    """Text segments of one Watch unit (zone or fullscreen tile) or Quick area.

    Coordinates are relative to the unit's capture bounds.
    """

    def __init__(self, prefix):
        self.prefix = prefix
        self.segments = {}
        self.sequence = 0

    def _new_id(self):
        self.sequence += 1
        return f'{self.prefix}{self.sequence}'

    @staticmethod
    def _score(segment, block):
        a, b = segment.rect, block.rect
        inter = a.intersect(b)
        overlap = inter.w * inter.h / max(1, min(a.w * a.h, b.w * b.h))
        height = min(segment.line_height, first_line_height(block))
        same_start = abs(a.x - b.x) <= max(10, height * .9) and abs(a.y - b.y) <= max(6, height * .6)
        key = normalize(block.text)
        related = text_related(segment.key, key)
        if overlap < .3 and not same_start:
            # Scrolling (chat, documents): the same words moved vertically in
            # the same column. Prefer the nearest such match.
            if (len(key) >= 3 and abs(a.x - b.x) <= max(12, height) and abs(a.h - b.h) <= max(6, height * .6)
                    and (key == segment.key or similarity(segment.key, key) >= .9)):
                return 1.2 + (.3 if key == segment.key else 0) - min(.9, abs(a.y - b.y) / 3000)
            return 0.0
        if not related and not (same_start and overlap >= .3):
            return 0.0
        return overlap * .5 + (.6 if same_start else 0) + similarity(segment.key, key) + (.5 if related else 0)

    def split_by_history(self, blocks, offset=(0, 0)):
        """Keep a line the scene already knew as complete separate from new
        text written beneath it.

        One still frame cannot tell a manual newline from a word-wrapped
        continuation when the next line starts in lowercase. History can: if an
        existing segment is exactly the first lines of a new block, the writer
        added lines below it (word wrap would have moved its last word).
        `offset` converts block line rectangles to scene coordinates.
        """
        result = []
        for block in blocks:
            lines = getattr(block, '_lines', None) or []
            cut = None
            if len(lines) >= 2:
                for segment in self.segments.values():
                    if segment.rect.overlap(block.rect) < .3 or not segment.seen_below:
                        continue
                    for k in range(1, len(lines)):
                        if normalize(' '.join(line.text for line in lines[:k])) == segment.key:
                            cut = k
                            break
                    if cut:
                        break
            if not cut:
                result.append(block)
                continue
            for part in (lines[:cut], lines[cut:]):
                rect = part[0].rect
                for line in part[1:]:
                    rect = rect.union(line.rect)
                dx, dy = getattr(block, '_offset', offset)
                rect = Rect(rect.x + dx, rect.y + dy, rect.w, rect.h)
                piece = TextBlock(' '.join(line.text for line in part), rect, block.confidence,
                    block.standalone, block.container)
                piece._lines = part
                piece._last_line = part[-1]
                piece._offset = (dx, dy)
                result.append(piece)
        return result

    @staticmethod
    def _seen_below(block, areas):
        """The read covered at least a line of space under this block, so a
        missing next line was really absent (not cut off by the read strip)."""
        height = first_line_height(block)
        return any(area.x <= block.rect.x and area.y <= block.rect.y
                   and area.bottom - block.rect.bottom >= height * 1.5 for area in areas)

    def in_areas(self, segment, areas):
        r = segment.rect
        for area in areas:
            inter = r.intersect(area)
            if inter.w * inter.h >= r.w * r.h * .5:
                return True
        return False

    def reconcile(self, blocks, areas, image, now, protected=()):
        """Apply one OCR read of `areas` (unit-relative). Returns changes.

        `protected` rectangles are covered by our own overlays when Windows
        cannot exclude them from capture: text beneath them is unknown, so a
        segment there is never removed merely because OCR could not see it.
        Returns (added, updated, moved, removed, replaced) id lists, where
        `replaced` are updated segments whose words changed entirely.
        """
        # Segments in the read areas, plus any that a freshly read block now
        # covers: OCR has just read those pixels too, so the block is the truth
        # there (a partly typed line beside its finished sentence is a ghost).
        candidates = [s for s in self.segments.values() if self.in_areas(s, areas)
                      or any(s.rect.overlap(block.rect) >= .5 for block in blocks)]
        pairs = []
        for segment in candidates:
            for index, block in enumerate(blocks):
                score = self._score(segment, block)
                if score > 0:
                    pairs.append((score, segment.id, index))
        pairs.sort(reverse=True)
        used_segments, used_blocks, matches = set(), set(), {}
        for score, segment_id, index in pairs:
            if segment_id in used_segments or index in used_blocks:
                continue
            used_segments.add(segment_id)
            used_blocks.add(index)
            matches[segment_id] = index
        added, updated, moved, removed, replaced = [], [], [], [], []
        for segment_id, index in matches.items():
            segment, block = self.segments[segment_id], blocks[index]
            key = normalize(block.text)
            if segment.rect != block.rect:
                shift = abs(segment.rect.x - block.rect.x) > 2 or abs(segment.rect.y - block.rect.y) > 2
                if shift and key == segment.key:
                    moved.append(segment_id)
            if key != segment.key:
                if not text_related(segment.key, key):
                    replaced.append(segment_id)
                segment.key = key
                segment.changed = now
                updated.append(segment_id)
            segment.block = block
            segment.rect = block.rect
            segment.line_height = first_line_height(block)
            segment.confirmed = now
            segment.seen_below = self._seen_below(block, areas)
            segment.pixels = _gray(crop(image, block.rect))
            if segment.pixels is not None:
                segment.pixels = segment.pixels.copy()
        for segment in candidates:
            if segment.id in matches:
                continue
            absorbed = any(segment.rect.overlap(blocks[i].rect) >= .3 for i in range(len(blocks)))
            if not absorbed:
                covered = sum(segment.rect.intersect(p).w * segment.rect.intersect(p).h for p in protected)
                if covered >= segment.rect.w * segment.rect.h * .5:
                    continue  # Hidden beneath our own overlay: unknown, not gone.
                current = _gray(crop(image, segment.rect))
                if (segment.pixels is not None and current is not None and not blank(current)
                        and VisualAnchors.identical(current, segment.pixels)):
                    continue  # OCR missed unchanged pixels this pass.
            removed.append(segment.id)
            del self.segments[segment.id]
        for index, block in enumerate(blocks):
            if index in used_blocks:
                continue
            pixels = _gray(crop(image, block.rect))
            segment = Segment(self._new_id(), block, block.rect, normalize(block.text), now, now,
                first_line_height(block), pixels.copy() if pixels is not None else None,
                seen_below=self._seen_below(block, areas))
            self.segments[segment.id] = segment
            added.append(segment.id)
        return added, updated, moved, removed, replaced

    def due(self, now, base=.35, limit=None, image=None):
        """Segments whose settled words have no translation shown or pending.

        With `image` (the latest capture), a segment whose pixels changed since
        OCR last read it is still being typed/edited and waits; a finished line
        above or below the one being typed is not held back.
        """
        ready = []
        for segment in self.segments.values():
            if not segment.key or segment.key == segment.shown_key or segment.key == segment.pending_key:
                continue
            if image is not None and segment.pixels is not None:
                current = _gray(crop(image, segment.rect))
                if current is None or not VisualAnchors.identical(current, segment.pixels):
                    found = locate(segment, image)
                    if found is None:
                        continue  # Being typed/edited: wait for the next read.
                    segment.rect = found  # Unchanged words that scrolled.
            if now < segment.retry_after:
                continue
            if now - segment.changed < settle_delay(segment.text, base):
                continue
            ready.append(segment)
        ready.sort(key=lambda s: (s.rect.y, s.rect.x))
        return ready[:limit] if limit is not None else ready

    def remove(self, segment_id):
        return self.segments.pop(segment_id, None)

    def clear(self):
        self.segments.clear()
