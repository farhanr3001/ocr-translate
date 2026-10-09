"""Real Windows API tests; no translation account or network needed."""
import asyncio
import cv2
import numpy as np
from arabic_lens.ocr import WindowsOcrProvider
from arabic_lens.windows import CaptureService, physical_monitors


def test_real_windows_ocr():
    image = np.full((170, 1000, 4), 255, dtype=np.uint8)
    cv2.putText(image, "You need to find the key.", (30, 85), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0, 255), 2)
    blocks = asyncio.run(WindowsOcrProvider().recognize(image))
    text = " ".join(b.text for b in blocks).casefold()
    assert "find the key" in text
    assert all(b.rect.w > 0 and b.rect.h > 0 for b in blocks)


def test_real_capture_reuses_buffer():
    screen = next(iter(physical_monitors().values()))
    capture = CaptureService()
    try:
        from arabic_lens.models import Rect
        rect = Rect(screen.x, screen.y, 200, 100)
        first = capture.capture(rect)
        pointer = first.ctypes.data
        second = capture.capture(rect)
        assert second.shape == (100, 200, 4)
        assert second.ctypes.data == pointer
    finally:
        capture.close()
