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


@pytest.fixture
def watch_engine():
    """Build a Watch engine using the real scan/scene code with stub capture
    and OCR (no translation is scheduled: backoff is infinite)."""
    import asyncio
    import types
    from types import SimpleNamespace
    import numpy as np
    from arabic_lens.anchors import VisualAnchors
    from arabic_lens.engine import Engine
    from arabic_lens.models import Rect, TextBlock

    class StubOcr:
        def __init__(self):
            self.calls = []
            self.last_lines = []

        async def read(self, image):
            self.calls.append(image.shape)
            if not np.any(image[:, :, :3] > 100):
                return []
            h, w = image.shape[:2]
            return [TextBlock('A readable English sentence.',
                Rect(2, 2, max(8, min(130, w - 4)), max(6, min(24, h - 4))))]

    def build(settings, capture, preview, ocr=None):
        ocr = ocr or StubOcr()
        events = SimpleNamespace(removed=[], moved=[])
        fake = SimpleNamespace(settings=settings, fast_watch=False, zone_states={}, preview_capture=preview,
            capture=capture, ocr=ocr, _get_ocr=lambda: ocr, ocr_lock=asyncio.Lock(),
            anchors=VisualAnchors(), jobs={}, backoff=float('inf'), generation=1,
            own_overlays=lambda: (), removed=SimpleNamespace(emit=events.removed.append),
            source_moved=SimpleNamespace(emit=lambda *args: events.moved.append(args)),
            diagnostics=SimpleNamespace(emit=lambda *args: None),
            progress=SimpleNamespace(emit=lambda *args: None), events=events)
        for name in ('_masked', '_follow_scene', '_read_scene', '_verify_read', '_schedule_scene',
                     '_retire_segment', '_cancel_segment', '_translate_segment', '_scan_ocr_zone'):
            setattr(fake, name, types.MethodType(getattr(Engine, name), fake))
        return fake, ocr
    return build
