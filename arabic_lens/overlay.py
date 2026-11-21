import html
from PySide6.QtCore import Qt, QRect, QRectF, QPoint, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QPainter, QPen, QTextDocument, QFont, QTextOption, QCursor
from PySide6.QtWidgets import QWidget, QApplication
from .models import Rect
from .windows import exclude_capture, physical_monitors


def display_maps():
    native = physical_monitors()
    result = []
    for screen in QApplication.screens():
        g = screen.geometry()
        fallback = Rect(g.x(), g.y(), round(g.width() * screen.devicePixelRatio()), round(g.height() * screen.devicePixelRatio()))
        matched = native.get(screen.name()) or next((r for r in native.values() if r.x == g.x() and r.y == g.y()), fallback)
        result.append((screen, matched))
    return result


def physical_to_logical(rect):
    maps = display_maps()
    screen, native = max(maps, key=lambda pair: pair[1].overlap(rect))
    g, ratio = screen.geometry(), screen.devicePixelRatio()
    return screen, Rect(round(g.x() + (rect.x - native.x) / ratio), round(g.y() + (rect.y - native.y) / ratio), round(rect.w / ratio), round(rect.h / ratio))


def logical_to_physical(screen, rect):
    native = dict((s.name(), r) for s, r in display_maps())[screen.name()]
    g, ratio = screen.geometry(), screen.devicePixelRatio()
    return Rect(round(native.x + (rect.x - g.x()) * ratio), round(native.y + (rect.y - g.y()) * ratio), round(rect.w * ratio), round(rect.h * ratio))


def place_overlay(source, width, height, screen, occupied, preference="Below"):
    margin, gap = 10, 8
    x = min(max(screen.x + margin, source.x + (source.w - width) // 2), screen.right - width - margin)
    below = Rect(x, source.bottom + gap, width, height)
    above = Rect(x, source.y - height - gap, width, height)
    choices = [above, below] if preference == "Above" else [below, above]
    side_y = min(max(screen.y + margin, source.y), screen.bottom - height - margin)
    for side_x in (source.right + gap, source.x - width - gap):
        choices += [Rect(side_x, y, width, height) for y in
            (side_y, source.bottom + gap, source.y - height - gap)]
    if preference == "Replace":
        choices.insert(0, Rect(x, source.y, width, height))
    for candidate in choices:
        if candidate.x >= screen.x + margin and candidate.right <= screen.right - margin and candidate.y >= screen.y + margin and candidate.bottom <= screen.bottom - margin and all(candidate.overlap(other) == 0 for other in occupied):
            return candidate
    for y in range(screen.bottom - height - margin, screen.y + margin, -height - gap):
        candidate = Rect(x, y, width, height)
        if candidate.overlap(source) == 0 and all(candidate.overlap(other) == 0 for other in occupied):
            return candidate
    return Rect(x, min(max(screen.y + margin, below.y), screen.bottom - height - margin), width, height)


class ArabicSurface(QWidget):
    def __init__(self, appearance, text, floating=False):
        super().__init__()
        self.appearance, self.text = appearance, text
        if floating:
            self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
            self.setAttribute(Qt.WA_ShowWithoutActivating)
            self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.document = QTextDocument()
        self.fitted = False
        self.document.setDocumentMargin(0)
        self.refresh()

    def refresh(self):
        a = self.appearance
        font = QFont(a.font)
        font.setPixelSize(a.font_size)
        self.document.setDefaultFont(font)
        option = QTextOption(Qt.AlignRight)
        option.setTextDirection(Qt.RightToLeft)
        option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.document.setDefaultTextOption(option)
        from .formatting import display_values
        self.document.setPlainText(display_values(self.text))
        self.document.setTextWidth(max(100, a.max_width - a.padding * 2))
        ideal = max(140, min(a.max_width - a.padding * 2, self.document.idealWidth()))
        self.document.setTextWidth(ideal)
        self.setFixedSize(round(ideal) + a.padding * 2, round(self.document.size().height()) + a.padding * 2)
        self.update()

    def fit_to_source(self, source, max_extra=0, line_height=0):
        """Keep a readable base size; let Arabic use modest extra width/height.

        With `line_height` (one source text line, logical px) the Arabic takes
        the size of the text it covers, so every line of the same size gets
        the same Arabic size and a covering box never exceeds its line pitch.
        A single source line stays on one Arabic line, using spare width.
        """
        from dataclasses import replace
        self.fitted = True
        if line_height:
            # Match the English text's size (never larger than the preset).
            line_font = max(12, min(self.appearance.font_size, round(line_height * 1.0)))
            self.appearance = replace(self.appearance, font_size=line_font)
            if source.h < line_height * 1.6:
                return self._fit_single_line(source, max_extra, line_font)
            return self._fit_lines(source, max_extra, line_font, line_height)
        cell = self.appearance.padding <= 2 and self.appearance.border_width == 0
        # A 30–36 px source is often two desktop text lines, not one large
        # label. Keep its paragraph width instead of stretching it sideways.
        compact = source.h < 28
        self.fit_margin = 3 if compact else (4 if cell else 8)
        width, height = max(24 if cell else 72, source.w + self.fit_margin * 2), max(18 if compact else 34, source.h + self.fit_margin * 2)
        padding = 1 if cell else (2 if compact else (4 if source.h < 75 else 8))
        self.appearance = replace(self.appearance, padding=padding, background_opacity=100)
        font = self.document.defaultFont()
        if cell:
            option = self.document.defaultTextOption()
            option.setWrapMode(QTextOption.NoWrap)
            self.document.setDefaultTextOption(option)
        base_size = self.appearance.font_size
        font.setPixelSize(base_size)
        self.document.setDefaultFont(font)
        if compact and max_extra and not cell:
            # Short Arabic labels need somewhat more horizontal room than their
            # English source. Avoid the old 11px fallback on ordinary list rows.
            self.document.setTextWidth(-1)
            desired = round(self.document.idealWidth()) + padding * 2
            width = max(width, min(self.appearance.max_width, source.w + max_extra, desired))
        self.document.setTextWidth(width - padding * 2)
        # Keep default labels readable, while honoring larger user/preset type.
        minimum = min(base_size, max(16, round(base_size * .65)))
        while font.pixelSize() > minimum and (self.document.size().height() > height - padding * 2
                or (cell and self.document.idealWidth() > width - padding * 2)):
            font.setPixelSize(font.pixelSize() - 1)
            self.document.setDefaultFont(font)
        if compact and max_extra and not cell:
            self.document.setTextWidth(-1)
            width = max(source.w + self.fit_margin * 2,
                        min(self.appearance.max_width, source.w + max_extra,
                            round(self.document.idealWidth()) + padding * 2))
            self.document.setTextWidth(width - padding * 2)
        self.setFixedSize(width, max(height, round(self.document.size().height()) + padding * 2))
        self.source_box_height = height

    def _fit_lines(self, source, max_extra, line_font, line_height):
        """A wrapped source paragraph: same type size as its own lines, using
        spare width so the Arabic needs no more lines than the English."""
        from dataclasses import replace
        self.fit_margin = 2
        padding = 0  # Lines of Arabic at the source size already fill the box.
        self.appearance = replace(self.appearance, padding=padding, background_opacity=100)
        font = self.document.defaultFont()
        font.setPixelSize(line_font)
        self.document.setDefaultFont(font)
        option = self.document.defaultTextOption()
        option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.document.setDefaultTextOption(option)
        box = source.h + self.fit_margin * 2
        extra = min(60, max(0, max_extra))  # Stay close to the paragraph's own width.
        widths = [source.w, source.w + extra // 2, source.w + extra]
        for width in widths:
            self.document.setTextWidth(width)
            if self.document.size().height() + padding * 2 <= box:
                break
        self.setFixedSize(round(self.document.textWidth()) + padding * 2,
                          max(box, round(self.document.size().height()) + padding * 2))
        self.source_box_height = box
        self.single_line = True  # Sized from its own lines: no later shrinking.

    def _fit_single_line(self, source, max_extra, line_font):
        from dataclasses import replace
        self.fit_margin = 2
        padding = 1
        self.appearance = replace(self.appearance, padding=padding, background_opacity=100)
        font = self.document.defaultFont()
        font.setPixelSize(line_font)
        self.document.setDefaultFont(font)
        option = self.document.defaultTextOption()
        option.setWrapMode(QTextOption.NoWrap)
        self.document.setDefaultTextOption(option)
        self.document.setTextWidth(-1)
        widest = source.w + max(0, max_extra)
        if self.document.idealWidth() + padding * 2 > widest:
            # Far longer than the room beside it: wrap rather than cover more.
            option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
            self.document.setDefaultTextOption(option)
            self.document.setTextWidth(widest - padding * 2)
        else:
            self.document.setTextWidth(max(source.w, self.document.idealWidth() + 1))
        width = round(self.document.textWidth()) + padding * 2
        height = max(source.h + self.fit_margin * 2, round(self.document.size().height()) + padding * 2)
        self.setFixedSize(max(width, source.w + self.fit_margin * 2), height)
        self.source_box_height = source.h + self.fit_margin * 2
        self.single_line = True

    def limit_right(self, max_width):
        """Keep a fitted overlay within `max_width`, shrinking type if needed
        (never below a readable minimum; it may then wrap to two lines)."""
        max_width = max(24, int(max_width))
        if self.width() <= max_width:
            return
        padding = self.appearance.padding
        if getattr(self, 'single_line', False):
            # One size everywhere: wrap at the limit instead of shrinking.
            option = self.document.defaultTextOption()
            option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
            self.document.setDefaultTextOption(option)
            self.document.setTextWidth(max_width - padding * 2)
            self.setFixedSize(max_width, max(getattr(self, 'source_box_height', 0),
                                             round(self.document.size().height()) + padding * 2))
            self.update()
            return
        font = self.document.defaultFont()
        minimum = max(12, round(self.appearance.font_size * .7))
        option = self.document.defaultTextOption()
        option.setWrapMode(QTextOption.NoWrap)
        self.document.setDefaultTextOption(option)
        self.document.setTextWidth(-1)
        while font.pixelSize() > minimum and self.document.idealWidth() > max_width - padding * 2:
            font.setPixelSize(font.pixelSize() - 1)
            self.document.setDefaultFont(font)
        if self.document.idealWidth() > max_width - padding * 2:
            option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
            self.document.setDefaultTextOption(option)
        self.document.setTextWidth(max_width - padding * 2)
        self.setFixedSize(max_width, max(self.height(), round(self.document.size().height()) + padding * 2))
        self.update()

    def limit_height(self, max_height, max_width):
        """Fit within `max_height`: widen up to `max_width`, then reduce the
        type size (to 60% at most). Only if still impossible does it keep the
        smallest readable size and take the extra height."""
        max_height, max_width = int(max_height), int(max_width)
        if max_height <= 0 or self.height() <= max_height:
            return
        padding = self.appearance.padding
        font = self.document.defaultFont()
        # Only a modest reduction, so neighbouring lines keep a matching size.
        minimum = max(10, round(font.pixelSize() * .8))
        option = self.document.defaultTextOption()
        option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.document.setDefaultTextOption(option)
        widest = max(self.width(), max_width)
        for width in (self.width(), (self.width() + widest) // 2, widest):
            self.document.setTextWidth(width - padding * 2)
            if self.document.size().height() + padding * 2 <= max_height:
                break
        while (self.document.size().height() + padding * 2 > max_height and font.pixelSize() > minimum):
            font.setPixelSize(font.pixelSize() - 1)
            self.document.setDefaultFont(font)
        needed = round(self.document.size().height()) + padding * 2
        # Still cover the English box itself, but no more than the room allows.
        box = getattr(self, 'source_box_height', 0)
        self.setFixedSize(width, max(needed, min(box, max_height)))
        self.update()

    def paintEvent(self, event):
        from PySide6.QtGui import QAbstractTextDocumentLayout, QPalette
        a, p = self.appearance, QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        background = QColor(a.background_color)
        background.setAlpha(round(a.background_opacity * 2.55))
        p.setPen(QPen(QColor(a.border_color), a.border_width) if a.border_width else Qt.NoPen)
        p.setBrush(background)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), a.radius, a.radius)
        if getattr(self, 'collapsed', False):
            p.setPen(QColor(a.text_color))
            p.setFont(QFont('Segoe UI', 10))
            p.drawText(self.rect(), Qt.AlignCenter, 'العربية')
            return
        p.translate(a.padding, max(a.padding, (self.height() - self.document.size().height()) / 2) if self.fitted else a.padding)
        ctx = QAbstractTextDocumentLayout.PaintContext()
        def draw(color, dx=0, dy=0):
            ctx.palette.setColor(QPalette.Text, QColor(color))
            p.save()
            p.translate(dx, dy)
            self.document.documentLayout().draw(p, ctx)
            p.restore()
        if a.shadow:
            draw("#a0000000", 1, 2)
        if a.outline:
            for x, y in ((-a.outline, 0), (a.outline, 0), (0, -a.outline), (0, a.outline)):
                draw("#0b0e13", x, y)
        draw(a.text_color)


class TranslationOverlay(ArabicSurface):
    def __init__(self, appearance, text):
        super().__init__(appearance, text, floating=True)
        # Ordinary translations are retired by source tracking, never by age.
        # The timer is reserved for short failure/status notices.
        self.notice = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.dismiss)
        self.animation = QPropertyAnimation(self, b"windowOpacity", self)
        self.animation.setEasingCurve(QEasingCurve.InOutQuad)
        self.closing = False
        self.collapsed = False
        self.capture_excluded = exclude_capture(self)

    def toggle_collapsed(self):
        if self.collapsed:
            self.setFixedSize(self.expanded_size)
        else:
            self.expanded_size = self.size()
            self.setFixedSize(76, 30)
        self.collapsed = not self.collapsed
        self.update()

    def zoom(self, change):
        if self.collapsed:
            self.toggle_collapsed()
        font = self.document.defaultFont()
        font.setPixelSize(max(14, min(72, font.pixelSize() + change)))
        self.document.setDefaultFont(font)
        self.setFixedHeight(max(getattr(self, 'source_box_height', 0),
            round(self.document.size().height()) + self.appearance.padding * 2))
        self.update()

    def reveal(self, fade=True, lifetime=None):
        """Show the overlay. `lifetime` (seconds) is only for notices and the
        optional timed Quick Translate mode; translations otherwise stay until
        their source text changes or disappears."""
        self.setWindowOpacity(0 if fade else self.appearance.opacity / 100)
        self.show()
        self.animation.setDuration(self.appearance.fade_ms if fade else 0)
        self.animation.setStartValue(0.0 if fade else self.appearance.opacity / 100)
        self.animation.setEndValue(self.appearance.opacity / 100)
        self.animation.start()
        if self.notice:
            self.timer.start(max(1000, self.appearance.duration * 1000))
        elif lifetime:
            self.timer.start(max(1000, round(lifetime * 1000)))

    def dismiss(self):
        if self.closing:
            return
        self.closing = True
        self.timer.stop()
        self.animation.stop()
        self.animation.setDuration(self.appearance.fade_ms)
        self.animation.setStartValue(self.windowOpacity())
        self.animation.setEndValue(0.0)
        self.animation.finished.connect(self.close)
        self.animation.start()


def row_limit(source, others):
    """Left edge of the nearest item to the right on the same text row."""
    edges = []
    for other in others:
        vertical = min(source.bottom, other.bottom) - max(source.y, other.y)
        if vertical > min(source.h, other.h) * .5 and other.x >= source.right - 4:
            edges.append(other.x)
    return min(edges) if edges else None


def column_limit_below(source, others):
    """Top edge of the nearest item below `source` that shares its columns."""
    edges = []
    for other in others:
        horizontal = min(source.right, other.right) - max(source.x, other.x)
        if horizontal > min(source.w, other.w) * .2 and other.y >= source.bottom - 2:
            edges.append(other.y)
    return min(edges) if edges else None


def reading_seconds(arabic):
    """Automatic Quick Translate display time: a comfortable reading pace
    (about 150 words a minute) plus a little time to find the overlay."""
    words = len(arabic.split())
    return max(4.0, min(60.0, 2.5 + words * .4))


class OverlayManager:
    def __init__(self, settings, report, on_remove=None):
        self.settings, self.report = settings, report
        self.on_remove = on_remove
        self.source_rects = {}
        self.sources = {}
        self.windows = {}
        self.retired = []
        self.controls = {}
        self.dismissed = set()
        # None until the first overlay shows whether Windows honours capture
        # exclusion. When it does not, our overlays are visible to our own
        # screen capture: the engine masks these rectangles and Replace
        # placement falls back to Below so the English stays readable.
        self.capture_visible = None
        self._visible_rects = ()
        self.interaction_timer = QTimer()
        self.interaction_timer.setInterval(50)
        self.interaction_timer.timeout.connect(self.update_interaction)

    def capture_visible_rects(self):
        """Thread-safe snapshot (physical pixels) for the processing thread."""
        return self._visible_rects if self.capture_visible else ()

    def _refresh_visible_rects(self):
        if not self.capture_visible:
            return
        rects = []
        for overlay in list(self.windows.values()) + list(self.controls.values()):
            if not overlay.isVisible():
                continue
            screen = overlay.screen() or QApplication.primaryScreen()
            try:
                rects.append(logical_to_physical(screen, Rect(overlay.x(), overlay.y(), overlay.width(), overlay.height())))
            except KeyError:
                continue
        self._visible_rects = tuple(rects)

    def _duplicate_of(self, result):
        """A Quick result already shown by Watch (or vice versa)."""
        from .text import normalize
        key = normalize(result.source)
        if not key:
            return None
        for other, source in self.sources.items():
            if other == result.id or other.split(':')[0] == result.id.split(':')[0]:
                continue
            overlay = self.windows.get(other)
            rect = self.source_rects.get(other)
            if (overlay and not overlay.closing and rect and source == key
                    and rect.overlap(result.rect) > .6):
                return other
        return None

    def show(self, result):
        if result.id in self.dismissed:
            return
        if not result.notice and self._duplicate_of(result):
            return
        previous = self.windows.get(result.id)
        replacing = previous is not None and not previous.closing and previous.isVisible()
        if replacing:
            # In-place update (a line grew or was corrected): swap without a
            # fade so the subtitle never blinks while text is being typed.
            self.windows.pop(result.id, None)
            control = self.controls.pop(result.id, None)
            if control:
                control.hide(); control.deleteLater()
            previous.timer.stop(); previous.animation.stop()
            previous.hide(); previous.deleteLater()
        else:
            self.remove(result.id, notify=False)
        from .text import normalize
        self.source_rects[result.id] = result.rect
        self.sources[result.id] = normalize(result.source)
        screen, source = physical_to_logical(result.rect)
        available = screen.availableGeometry()
        bounds = Rect(available.x(), available.y(), available.width(), available.height())
        from dataclasses import replace
        from .appearance import effective_appearance
        a = effective_appearance(self.settings.overlay, result.application, result.style_hint)
        if result.notice:
            a = replace(a, position='Below', duration=4, persistence=False, max_width=420, font_size=20)
        if self.capture_visible and a.position == 'Replace':
            a = replace(a, position='Below')
        a = replace(a, max_width=min(a.max_width, bounds.w - 20))
        overlay = TranslationOverlay(a, result.arabic)
        overlay.notice = result.notice
        if self.capture_visible is None or (self.capture_visible is False and not overlay.capture_excluded):
            self.capture_visible = not overlay.capture_excluded
            if self.capture_visible:
                # Exclusion only keeps overlays out of screen capture. Some
                # Windows builds refuse it; still show translations, mask them
                # from our own OCR, and never cover the source text.
                self.report("Capture exclusion is unavailable; overlays are placed beside text.")
                if a.position == 'Replace':
                    overlay.close(); overlay.deleteLater()
                    a = replace(a, position='Below')
                    overlay = TranslationOverlay(a, result.arabic)
                    overlay.notice = result.notice
        avoid = [physical_to_logical(r)[1] for r in result.avoid_regions]
        if a.position == 'Replace':
            # Grow only into free space: never over a neighbouring value
            # ("Health 85 / 100") or other text on the same row.
            right_limit = row_limit(source, avoid)
            if result.container:
                # Inside a panel/cell: grow up to its inner edge, never past it.
                edge = physical_to_logical(result.container)[1].right - 4
                right_limit = edge if right_limit is None else min(right_limit, edge)
            if right_limit is not None:
                # Always at least cover the English itself.
                right_limit = max(right_limit, source.right + 4)
            room = right_limit - source.right if right_limit is not None else 160
            line = round(result.line_height / max(.5, screen.devicePixelRatio())) if result.line_height else 0
            overlay.fit_to_source(source, max_extra=max(0, min(160 if line else 80, room - 8)), line_height=line)
            if right_limit is not None:
                overlay.limit_right(right_limit - (source.x - overlay.fit_margin) - 1)
            # Never grow down over the next line of text or another overlay
            # (wrapped chat messages, stacked dialogue): use spare width first,
            # then smaller type, before taking more height.
            others = avoid + [Rect(w.x(), w.y(), w.width(), w.height()) for key, w in self.windows.items()
                              if key != result.id and w.isVisible() and not w.closing]
            bottom = column_limit_below(source, others)
            if bottom is not None and not getattr(overlay, 'single_line', False):
                top = source.y - overlay.fit_margin
                left = source.x - overlay.fit_margin
                width_limit = right_limit - left - 1 if right_limit is not None else overlay.width() + 80
                width_limit = min(width_limit, bounds.right - 10 - left)
                overlay.limit_height(bottom - top - 1, max(overlay.width(), width_limit))
        occupied = [Rect(w.x(), w.y(), w.width(), w.height()) for w in self.windows.values() if w.isVisible() and not w.closing]
        occupied += avoid
        if a.position == 'Replace':
            rect = Rect(max(bounds.x, min(source.x - overlay.fit_margin, bounds.right - overlay.width())),
                max(bounds.y, min(source.y - overlay.fit_margin, bounds.bottom - overlay.height())), overlay.width(), overlay.height())
        elif replacing and a.position == previous.appearance.position:
            # Keep a growing line's subtitle where the reader already looks.
            rect = Rect(previous.x(), previous.y(), overlay.width(), overlay.height())
            if rect.right > bounds.right - 10:
                rect = Rect(max(bounds.x + 10, bounds.right - 10 - rect.w), rect.y, rect.w, rect.h)
        else:
            rect = place_overlay(source, overlay.width(), overlay.height(), bounds, occupied, a.position)
        overlay.move(rect.x, rect.y)
        if len(self.windows) >= self.settings.max_regions:
            self.remove(next(iter(self.windows)))
        self.windows[result.id] = overlay
        lifetime = None
        if (result.id.startswith('manual') and not result.notice
                and getattr(self.settings.overlay, 'quick_lifetime', 'source') == 'timer'):
            seconds = getattr(self.settings.overlay, 'quick_seconds', 0)
            lifetime = seconds if seconds > 0 else reading_seconds(result.arabic)
        overlay.reveal(fade=not replacing, lifetime=lifetime)
        self.interaction_timer.start()
        overlay.animation.finished.connect(lambda: self._collect(result.id, overlay))
        overlay.timer.timeout.connect(lambda key=result.id: self._expired(key, overlay))
        self._refresh_visible_rects()

    def _expired(self, key, overlay):
        """A timed overlay ended; forget its bookkeeping like a removal."""
        if self.windows.get(key) is overlay:
            self.windows.pop(key, None)
            self.source_rects.pop(key, None)
            self.sources.pop(key, None)
            if self.on_remove:
                self.on_remove(key)
            self.retired.append(overlay)
        self._refresh_visible_rects()

    def _collect(self, key, overlay):
        if overlay.closing:
            if self.windows.get(key) is overlay:
                self.windows.pop(key, None)
                self.source_rects.pop(key, None)
                self.sources.pop(key, None)
                if self.on_remove:
                    self.on_remove(key)
            if overlay in self.retired:
                self.retired.remove(overlay)
            overlay.deleteLater()
            control = self.controls.pop(key, None) if key not in self.windows else None
            if control:
                control.hide()
                control.deleteLater()

    def update_interaction(self):
        from .windows import modifiers_held
        held = modifiers_held(self.settings.overlay.interaction_hold)
        cursor = QCursor.pos()
        selected = next((key for key, control in self.controls.items() if control.dragging or (control.isVisible() and control.geometry().contains(cursor))), None)
        if selected is None:
            selected = next((key for key, overlay in reversed(list(self.windows.items())) if overlay.geometry().adjusted(-2,-2,2,2).contains(cursor)), None)
        for key, overlay in list(self.windows.items()):
            active = held and key == selected and not overlay.closing
            control = self.controls.get(key)
            if active:
                if control is None:
                    control = OverlayInteraction(overlay, lambda k=key: self.dismiss_one(k))
                    self.controls[key] = control
                control.follow_overlay()
                control.show()
                control.raise_()
            elif control:
                control.dragging = False
                control.hide()
        if self.capture_visible:
            self._refresh_visible_rects()
        if not self.windows:
            self.interaction_timer.stop()

    def dismiss_one(self, key):
        self.dismissed.add(key)
        self.remove(key)

    def keep_alive_group(self, group):
        """Legacy engine heartbeat; source tracking now owns overlay lifetime."""
        return

    def remove_group(self, key, immediate=False):
        for item in list(self.windows):
            if item == key or item.startswith(key + ':'):
                self.remove(item, immediate=immediate)
        self.dismissed = {item for item in self.dismissed if item != key and not item.startswith(key + ':')}

    def remove(self, key, immediate=False, notify=True):
        self.source_rects.pop(key, None)
        self.sources.pop(key, None)
        if notify and self.on_remove:
            self.on_remove(key)
        control = self.controls.pop(key, None)
        if control:
            control.hide()
            control.deleteLater()
        overlay = self.windows.pop(key, None)
        if overlay:
            if immediate:
                overlay.timer.stop()
                overlay.animation.stop()
                overlay.close()
                overlay.deleteLater()
            else:
                self.retired.append(overlay)
                overlay.dismiss()
        self._refresh_visible_rects()

    def clear(self, immediate=False):
        self.dismissed.clear()
        self.interaction_timer.stop()
        for key in list(self.windows):
            self.remove(key, immediate)
        if immediate:
            for overlay in self.retired:
                overlay.animation.stop()
                overlay.close()
                overlay.deleteLater()
            self.retired.clear()

    def follow_source(self, key, rect):
        overlay = self.windows.get(key)
        old = self.source_rects.get(key)
        if overlay and old and not overlay.closing:
            _, previous = physical_to_logical(old)
            _, current = physical_to_logical(rect)
            overlay.move(overlay.x() + current.x - previous.x, overlay.y() + current.y - previous.y)
            self.source_rects[key] = rect
            if key in self.controls:
                self.controls[key].follow_overlay()
            self._refresh_visible_rects()


class OverlayInteraction(QWidget):
    """Temporary no-focus input surface, visible only during the hold gesture.

    The translation itself always stays click-through. No keys are injected,
    swallowed or sent to games; only deliberate held mouse interaction is used.
    """
    def __init__(self, overlay, close_one):
        super().__init__()
        self.overlay, self.close_one = overlay, close_one
        self.dragging = False
        self.copied = False
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.SizeAllCursor)
        self.capture_excluded = exclude_capture(self)

    def button_rects(self):
        right = self.width() - 14
        return (QRect(right - 14, 0, 28, 28),) + tuple(QRect(right - 14 - 28 * i, 2, 24, 24) for i in range(1, 5))

    def follow_overlay(self):
        width = max(156, self.overlay.width())
        self.setGeometry(self.overlay.x() + self.overlay.width() - width, self.overlay.y() - 14, width + 14, self.overlay.height() + 14)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # Nonzero alpha makes this temporary layered window draggable on Windows.
        p.fillRect(self.rect(), QColor(0, 0, 0, 1))
        p.setPen(QPen(QColor('#ad8b51'), 1))
        body = QRectF(self.width() - 14 - self.overlay.width(), 14, self.overlay.width(), self.overlay.height())
        p.drawRoundedRect(body.adjusted(.5, .5, -.5, -.5), 5, 5)
        font = QFont('Segoe UI'); font.setPixelSize(13); p.setFont(font)
        for rect, text in zip(self.button_rects(), ['×', '▸' if self.overlay.collapsed else '▾', 'A+', 'A−']):
            p.setBrush(QColor(self.overlay.appearance.background_color))
            p.drawEllipse(QRectF(rect))
            p.setPen(QColor(self.overlay.appearance.text_color))
            p.drawText(rect, Qt.AlignCenter, text)
        rect = self.button_rects()[4]
        p.setBrush(QColor(self.overlay.appearance.background_color)); p.drawEllipse(QRectF(rect))
        p.setPen(QPen(QColor(self.overlay.appearance.text_color), 1.3))
        if self.copied:
            p.drawText(rect, Qt.AlignCenter, '✓')
        else:
            # Two overlapping sheets: a font-independent clipboard copy icon.
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(rect.x() + 5, rect.y() + 4, 7, 9), 1, 1)
            p.drawRoundedRect(QRectF(rect.x() + 8, rect.y() + 7, 7, 9), 1, 1)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        # The 50 ms hover poll can leave this input window visible briefly
        # after the keys are released. A normal click must never operate it.
        from .windows import modifiers_held
        if not modifiers_held(self.overlay.appearance.interaction_hold):
            self.hide()
            event.ignore()
            return
        close, collapse, larger, smaller, copy = self.button_rects()
        if close.contains(event.position().toPoint()):
            self.close_one()
        elif collapse.contains(event.position().toPoint()):
            self.overlay.toggle_collapsed()
            self.follow_overlay()
            self.update()
        elif larger.contains(event.position().toPoint()) or smaller.contains(event.position().toPoint()):
            self.overlay.zoom(2 if larger.contains(event.position().toPoint()) else -2)
            self.follow_overlay()
            self.update()
        elif copy.contains(event.position().toPoint()):
            QApplication.clipboard().setText(self.overlay.text)
            self.copied = True
            self.update()
            QTimer.singleShot(900, self.reset_copy_feedback)
        else:
            self.dragging = True
            self.drag_offset = event.globalPosition().toPoint() - self.overlay.pos()

    def reset_copy_feedback(self):
        self.copied = False
        self.update()

    def mouseMoveEvent(self, event):
        from .windows import modifiers_held
        if not modifiers_held(self.overlay.appearance.interaction_hold):
            self.dragging = False
            self.hide()
            event.ignore()
            return
        if self.dragging:
            position = event.globalPosition().toPoint() - self.drag_offset
            self.overlay.move(position)
            self.follow_overlay()
        else:
            self.setCursor(Qt.PointingHandCursor if any(r.contains(event.position().toPoint()) for r in self.button_rects()) else Qt.SizeAllCursor)

    def mouseReleaseEvent(self, event):
        self.dragging = False


class DiagnosticOverlay(QWidget):
    def __init__(self, screen, regions):
        super().__init__()
        self.regions = regions
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setGeometry(screen.geometry())
        exclude_capture(self)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setPen(QColor("#58e1c0"))
        for key, rect, revision in self.regions:
            p.drawRect(QRect(rect.x - self.x(), rect.y - self.y(), rect.w, rect.h))
            p.drawText(rect.x - self.x(), rect.y - self.y() - 3, f"region {key} · revision {revision}")
