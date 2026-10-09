"""Scrolling a settings page must never change a property accidentally."""
from PySide6.QtCore import QObject, QEvent
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QWidget, QAbstractSpinBox, QComboBox, QSlider, QScrollArea, QApplication, QPlainTextEdit


class TranslationResult(QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setMinimumHeight(90)
        self.setMaximumHeight(220)

    def setText(self, text):
        from .formatting import display_values
        self.setPlainText(display_values(text))

    def text(self):
        return self.toPlainText()


class PropertyWheelFilter(QObject):
    def eventFilter(self, watched, event):
        if event.type() != QEvent.Wheel:
            return False
        # Forward once to the page, preserving scrolling even over a slider or
        # number field. Accept the original so it cannot also reach the control.
        parent = watched.parentWidget()
        while parent and not isinstance(parent, QScrollArea):
            parent = parent.parentWidget()
        if parent:
            viewport = parent.viewport()
            forwarded = QWheelEvent(viewport.mapFromGlobal(event.globalPosition().toPoint()),
                                    event.globalPosition(), event.pixelDelta(), event.angleDelta(),
                                    event.buttons(), event.modifiers(), event.phase(), event.inverted())
            QApplication.sendEvent(viewport, forwarded)
        event.accept()
        return True


def protect_wheel_fields(root):
    if not hasattr(root, '_property_wheel_filter'):
        root._property_wheel_filter = PropertyWheelFilter(root)
    for widget in root.findChildren(QWidget):
        if not isinstance(widget, (QAbstractSpinBox, QComboBox, QSlider)):
            continue
        widget.installEventFilter(root._property_wheel_filter)
        # Editable spin boxes receive wheel events on their line editor too.
        if isinstance(widget, QAbstractSpinBox) and widget.lineEdit():
            widget.lineEdit().installEventFilter(root._property_wheel_filter)
