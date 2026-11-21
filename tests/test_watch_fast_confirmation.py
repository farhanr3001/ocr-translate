from types import SimpleNamespace

import numpy as np

from arabic_lens.engine import Engine
from arabic_lens.models import Rect


def test_fast_watch_accepts_an_intact_scrolled_row_and_rejects_a_replacement():
    bounds = Rect(100, 100, 32, 24)
    source = Rect(4, 3, 20, 4)
    pixels = np.random.default_rng(4).integers(0, 255, (8, bounds.w), dtype=np.uint8)
    frame = np.zeros((bounds.h, bounds.w, 4), dtype=np.uint8)
    frame[10:18, :, :3] = pixels[..., None]
    engine = SimpleNamespace(capture=SimpleNamespace(capture=lambda _: frame),
                             _masked=lambda image, _: (image, ()))
    evidence = (source, 1, pixels)
    result = Engine._confirm_watch_row(engine, {}, bounds, evidence)
    assert result[0] == Rect(source.x, source.y + 9, source.w, source.h)

    frame[12, 8, :3] ^= 255
    assert Engine._confirm_watch_row(engine, {}, bounds, evidence) is None
