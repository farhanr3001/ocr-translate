import asyncio
from types import SimpleNamespace

import numpy as np
import pytest

from arabic_lens.engine import Engine
from arabic_lens.models import Rect, TextBlock
from arabic_lens.scene import TextScene


@pytest.mark.parametrize(("change", "retired"), [
    ("vanished", True),
    ("scrolled", False),
    ("transient", False),
])
def test_fast_retirement_checks_twice_and_preserves_a_scrolled_line(change, retired):
    bounds = Rect(0, 0, 80, 60)
    box = Rect(15, 8, 40, 12)
    original = np.zeros((bounds.h, bounds.w, 4), dtype=np.uint8)
    pattern = np.random.default_rng(10).integers(0, 255, (box.h, box.w, 1), dtype=np.uint8)
    original[box.y:box.bottom, box.x:box.right, :3] = pattern
    changed = np.zeros_like(original)
    if change == "scrolled":
        changed[28:28 + box.h, box.x:box.right, :3] = pattern

    scene = TextScene("watch-")
    scene.reconcile([TextBlock("Wait beside the bridge.", box)], [bounds], original, 1)
    segment = next(iter(scene.segments.values()))
    segment.shown_key = segment.key
    state = {"scene": scene, "bounds": bounds}
    frames = iter([changed, original if change == "transient" else changed])
    events = []

    def capture(_):
        frame = next(frames)
        engine.watch = False if getattr(engine, "first_sample", False) else True
        engine.first_sample = True
        engine.latest = frame
        return frame

    engine = SimpleNamespace(
        watch=True, zone_states={0: state},
        preview_capture=SimpleNamespace(capture=capture),
        capture=SimpleNamespace(capture=lambda _: engine.latest),
        _masked=lambda frame, _: (frame, []),
        _retire_segment=lambda _, key: events.append(key),
    )
    asyncio.run(Engine._probe_watch_sources(engine))
    assert events == ([segment.id] if retired else [])


def test_completed_edit_uses_fast_job_without_dropping_the_shown_translation():
    bounds = Rect(0, 0, 80, 60)
    image = np.zeros((bounds.h, bounds.w, 4), dtype=np.uint8)
    box = Rect(15, 8, 40, 12)
    scene = TextScene("watch-")
    scene.reconcile([TextBlock("Meet me by the bridge.", box)], [bounds], image, 1)
    segment = next(iter(scene.segments.values()))
    segment.shown_key = "meet me by the gate"
    evidence = (box, 6, image[6:22, :, 0].copy())
    state = {"scene": scene, "image": image, "ocr_rows": {segment.id: (segment.text, evidence)}}
    started = []

    async def translate(*args, **options):
        started.append(options)

    engine = SimpleNamespace(settings=SimpleNamespace(stability_ms=400, max_regions=12),
                             jobs={}, generation=1, fast_watch_removal=True,
                             _cancel_segment=lambda _: None, _translate_segment=translate)

    async def schedule():
        Engine._schedule_scene(engine, state, bounds, "", None, 1, early_ids={segment.id})
        await asyncio.gather(*engine.jobs.values())

    asyncio.run(schedule())
    assert started == [{"evidence": evidence, "early": True}]
    assert segment.shown_key == "meet me by the gate"
