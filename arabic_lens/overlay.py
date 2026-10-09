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

    def fit_to_source(self, source, max_extra=0):
        """Keep a readable base size; let Arabic use modest extra width/height."""
        from dataclasses import replace
        self.fitted = True
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

    def reveal(self):
        self.setWindowOpacity(0)
        self.show()
        self.animation.setDuration(self.appearance.fade_ms)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(self.appearance.opacity / 100)
        self.animation.start()
        if self.notice:
            self.timer.start(max(1000, self.appearance.duration * 1000))

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


class OverlayManager:
    def __init__(self, settings, report, on_remove=None):
        self.settings, self.report = settings, report
        self.on_remove = on_remove
        self.source_rects = {}
        self.windows = {}
        self.retired = []
        self.controls = {}
        self.dismissed = set()
        self.interaction_timer = QTimer()
        self.interaction_timer.setInterval(50)
        self.interaction_timer.timeout.connect(self.update_interaction)

    def show(self, result):
        if result.id in self.dismissed:
            return
        self.remove(result.id, notify=False)
        self.source_rects[result.id] = result.rect
        screen, source = physical_to_logical(result.rect)
        available = screen.availableGeometry()
        bounds = Rect(available.x(), available.y(), available.width(), available.height())
        from dataclasses import replace
        from .appearance import effective_appearance
        a = effective_appearance(self.settings.overlay, result.application, result.style_hint)
        if result.notice:
            a = replace(a, position='Below', duration=4, persistence=False, max_width=420, font_size=20)
        a = replace(a, max_width=min(a.max_width, bounds.w - 20))
        overlay = TranslationOverlay(a, result.arabic)
        overlay.notice = result.notice
        if a.position == 'Replace':
            overlay.fit_to_source(source, max_extra=0 if result.container else 80)
        if not overlay.capture_excluded:
            overlay.close()
            self.report("Capture exclusion is unavailable on this Windows version.")
            return
        occupied = [Rect(w.x(), w.y(), w.width(), w.height()) for w in self.windows.values() if w.isVisible() and not w.closing]
        occupied += [physical_to_logical(r)[1] for r in result.avoid_regions]
        if a.position == 'Replace':
            rect = Rect(max(bounds.x, min(source.x - overlay.fit_margin, bounds.right - overlay.width())),
                max(bounds.y, min(source.y - overlay.fit_margin, bounds.bottom - overlay.height())), overlay.width(), overlay.height())
        else:
            rect = place_overlay(source, overlay.width(), overlay.height(), bounds, occupied, a.position)
        overlay.move(rect.x, rect.y)
        if len(self.windows) >= self.settings.max_regions:
            self.remove(next(iter(self.windows)))
        self.windows[result.id] = overlay
        overlay.reveal()
        self.interaction_timer.start()
        overlay.animation.finished.connect(lambda: self._collect(result.id, overlay))

    def _collect(self, key, overlay):
        if overlay.closing:
            if self.windows.get(key) is overlay:
                self.windows.pop(key, None)
                self.source_rects.pop(key, None)
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
        if not self.windows:
            self.interaction_timer.stop()

    def dismiss_one(self, key):
        self.dismissed.add(key)
        self.remove(key)

    def keep_alive_group(self, group):
        """Legacy engine heartbeat; source tracking now owns overlay lifetime."""
        return

    def remove_group(self, key):
        for item in list(self.windows):
            if item == key or item.startswith(key + ':'):
                self.remove(item)
        self.dismissed = {item for item in self.dismissed if item != key and not item.startswith(key + ':')}

    def remove(self, key, immediate=False, notify=True):
        self.source_rects.pop(key, None)
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
