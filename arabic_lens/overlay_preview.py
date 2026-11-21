from dataclasses import replace

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel

from .appearance import effective_appearance
from .design import PreviewScene
from .models import Rect
from .overlay import ArabicSurface


class OverlayPreview(PreviewScene):
    """Use the on-screen Arabic renderer with a sample source at a fixed size."""

    def __init__(self, appearance):
        super().__init__()
        self.fill_scene = True
        self.setMinimumHeight(220)
        self.source = QLabel("Find the key before sunset.", self)
        self.source.setStyleSheet(
            "background: #191d22; color: white; border-radius: 5px; padding: 3px 8px;"
            "font-size: 21px;")
        self.source.adjustSize()
        self.surface = ArabicSurface(appearance, "اعثر على المفتاح قبل غروب الشمس.")
        self.surface.setParent(self)
        self.effect = QGraphicsOpacityEffect(self.surface)
        self.surface.setGraphicsEffect(self.effect)
        self.fade = QPropertyAnimation(self.effect, b"opacity", self)
        self.fade.setEasingCurve(QEasingCurve.InOutQuad)
        self.set_appearance(appearance)

    def set_appearance(self, base):
        self.appearance = replace(base)
        self.position = base.position
        self.fade.stop()
        self.effect.setOpacity(base.opacity / 100)
        self.render_sample()

    def render_sample(self):
        available = max(160, self.width() - 24)
        appearance = effective_appearance(self.appearance)
        self.surface.appearance = replace(appearance, max_width=min(appearance.max_width, available))
        self.surface.fitted = False
        self.surface.refresh()
        if self.position == "Replace":
            width = min(self.source.width(), available - 4)
            source = Rect(0, 0, width, self.source.height())
            self.surface.fit_to_source(source, max_extra=min(152, available - width), line_height=23)
            self.surface.limit_right(available)
        self.arrange()

    def resizeEvent(self, event):
        self.render_sample()

    def replay_fade(self):
        self.fade.stop()
        self.fade.setDuration(self.appearance.fade_ms)
        self.fade.setStartValue(0.0)
        self.fade.setEndValue(self.appearance.opacity / 100)
        self.fade.start()
