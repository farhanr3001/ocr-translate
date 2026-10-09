import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget


@pytest.fixture(autouse=True)
def keep_test_windows_off_desktop(monkeypatch):
    """Render native Qt widgets for tests without composing them on the desktop."""
    original = QWidget.show
    def show_hidden(widget):
        widget.setAttribute(Qt.WA_DontShowOnScreen, True)
        original(widget)
    monkeypatch.setattr(QWidget, 'show', show_hidden)
