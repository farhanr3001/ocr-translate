from dataclasses import dataclass, field


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self):
        return self.x + self.w

    @property
    def bottom(self):
        return self.y + self.h

    def overlap(self, other):
        area = max(0, min(self.right, other.right) - max(self.x, other.x)) * max(0, min(self.bottom, other.bottom) - max(self.y, other.y))
        return area / max(1, min(self.w * self.h, other.w * other.h))

    def union(self, other):
        x, y = min(self.x, other.x), min(self.y, other.y)
        return Rect(x, y, max(self.right, other.right) - x, max(self.bottom, other.bottom) - y)

    def intersect(self, other):
        x, y = max(self.x, other.x), max(self.y, other.y)
        return Rect(x, y, max(0, min(self.right, other.right) - x), max(0, min(self.bottom, other.bottom) - y))


@dataclass
class TextBlock:
    text: str
    rect: Rect
    confidence: float | None = None
    standalone: bool = False
    container: Rect | None = None


@dataclass
class Translation:
    id: str
    source: str
    arabic: str
    rect: Rect
    application: str = ""
    cached: bool = False
    latency_ms: int = 0
    style_hint: dict | None = None
    avoid_regions: list[Rect] = field(default_factory=list)
    container: Rect | None = None
    source_window: tuple | None = None
    notice: bool = False
