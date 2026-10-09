import cv2
import numpy as np
import pytest
from arabic_lens.models import Rect
from arabic_lens.windows import CaptureService, PreviewCaptureService, gdi32


@pytest.mark.parametrize('background,foreground', [(0, 255), (255, 0)])
def test_small_native_preview_retains_thin_text_changes(background, foreground):
    # Render into a native off-screen DIB, never a visible desktop test window.
    source, preview = CaptureService(), PreviewCaptureService()
    desktop_dc = preview.screen
    try:
        source.capture(Rect(0, 0, 1920, 1080))
        source.buffer[:] = (background, background, background, 0)
        preview.screen = source.dc
        before = preview.capture(Rect(0, 0, 1920, 1080)).copy()
        cv2.putText(source.buffer, 'Find the key before sunset.', (400, 500),
            cv2.FONT_HERSHEY_SIMPLEX, .6, (foreground, foreground, foreground, 0), 1)
        after = preview.capture(Rect(0, 0, 1920, 1080))
        assert after.shape == (180, 320, 4)
        assert np.count_nonzero(np.abs(after.astype(np.int16) - before.astype(np.int16)) > 12) >= 3
    finally:
        preview.screen = desktop_dc
        preview.close()
        source.close()
