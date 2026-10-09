"""Replay a screen recording through production OCR-first Watch without translating.

Usage: python tools/analyze_watch_video.py VIDEO.mp4
The supplied video is read in place and is never copied into the app package.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arabic_lens.config import Settings
from arabic_lens.detection import RegionTracker
from arabic_lens.engine import Engine, whole_screen_tiles
from arabic_lens.models import Rect, TextBlock
import arabic_lens.engine as engine_module


async def analyze(path):
    video = cv2.VideoCapture(str(path))
    if not video.isOpened():
        raise RuntimeError('Video could not be opened')
    width = round(video.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = round(video.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = video.get(cv2.CAP_PROP_FPS) or 30
    # The app scans every 250 ms. Decode all frames but submit only the frame
    # Watch would see on each scan, using recording time for OCR debounce.
    clock = [0.0]
    original_engine_time = engine_module.time
    engine_module.time = SimpleNamespace(monotonic=lambda: clock[0])
    bounds = Rect(0, 0, width, height)
    nav = Rect(round(width * .17), round(height * .12), round(width * .14), round(height * .8))
    feed = Rect(round(width * .31), round(height * .12), round(width * .32), round(height * .8))
    nav_label = Rect(nav.x + 30, nav.y + 50, 90, 23)
    counts = {'full_captures': 0, 'ocr_calls': 0, 'alive': 0, 'removed': 0}
    current = [None]
    capture_area = [None]
    current_tile = [0]
    tile_captures = {}
    tile_ocr = {}

    class Capture:
        def capture(self, area):
            counts['full_captures'] += 1
            tile_captures[current_tile[0]] = tile_captures.get(current_tile[0], 0) + 1
            capture_area[0] = area
            return current[0][area.y:area.bottom, area.x:area.right].copy()

    class StubOcr:
        async def read(self, image):
            counts['ocr_calls'] += 1
            tile_ocr[current_tile[0]] = tile_ocr.get(current_tile[0], 0) + 1
            area = capture_area[0]
            # One stable known text block is enough to check region identity
            # without loading OCR/model weights for 153 recorded frames.
            if area and image.shape[:2] == (area.h, area.w) and area.intersect(nav_label) == nav_label:
                return [TextBlock('Home', Rect(nav_label.x - area.x, nav_label.y - area.y,
                                               nav_label.w, nav_label.h))]
            return []

    fake = SimpleNamespace(settings=Settings(watch_fullscreen=True), zone_states={},
        tracker=RegionTracker(), preview_capture=None, capture=Capture(), ocr_zone_tracking=True,
        ocr_lock=asyncio.Lock(), _get_ocr=lambda: StubOcr(), anchors=SimpleNamespace(items={}),
        jobs={}, backoff=float('inf'), generation=1, removed=SimpleNamespace(emit=lambda key: counts.__setitem__('removed', counts['removed'] + 1)),
        region_alive=SimpleNamespace(emit=lambda key: counts.__setitem__('alive', counts['alive'] + 1)),
        source_lost=SimpleNamespace(emit=lambda key: None))
    fake._scan_ocr_zone = lambda *args, **kwargs: Engine._scan_ocr_zone(fake, *args, **kwargs)
    fake._read_dirty_zone = lambda *args, **kwargs: Engine._read_dirty_zone(fake, *args, **kwargs)
    nav_keys = set()
    feed_changes = 0
    nav_pixel_changes = 0
    old_nav = old_feed = None
    frames = scans = 0
    next_scan = 0.0
    tiles = list(whole_screen_tiles(bounds, (180, 320, 4)))
    while True:
        ok, frame = video.read()
        if not ok:
            break
        clock[0] = frames / fps
        frames += 1
        if clock[0] + 1e-6 < next_scan:
            continue
        next_scan += .25
        current[0] = frame
        preview = cv2.resize(frame, (320, 180), interpolation=cv2.INTER_AREA)
        nav_crop = frame[nav.y:nav.bottom, nav.x:nav.right]
        feed_crop = frame[feed.y:feed.bottom, feed.x:feed.right]
        if old_nav is not None:
            nav_pixel_changes += bool(np.count_nonzero(np.abs(nav_crop.astype(np.int16) - old_nav.astype(np.int16)) > 20) > 1000)
            feed_changes += bool(np.count_nonzero(np.abs(feed_crop.astype(np.int16) - old_feed.astype(np.int16)) > 20) > 1000)
        old_nav, old_feed = nav_crop.copy(), feed_crop.copy()
        for index, (core, padded, (x0, y0, x1, y1)) in enumerate(tiles):
            current_tile[0] = index
            await Engine._scan_zone(fake, index, padded, 1, 'Recorded X', np, 0,
                preview=preview[y0:y1, x0:x1], core=core, multiple=True)
            tracker = fake.zone_states[index]['tracker']
            if scans == 0:
                for region in tracker.regions.values():
                    actual = Rect(padded.x + region.rect.x, padded.y + region.rect.y, region.rect.w, region.rect.h)
                    if actual.overlap(nav) > .5:
                        nav_keys.add((index, region.id))
                        region.processed = True
                        region.delivered.add('static nav label')
        scans += 1
    video.release()
    retained = []
    for index, key in nav_keys:
        region = fake.zone_states[index]['tracker'].regions.get(key)
        retained.append(bool(region and region.processed and region.revision == 0 and region.delivered == {'static nav label'}))
    fullscreen = {'frames': frames, 'watch_scans': scans, 'size': [width, height], 'tiles': len(tiles),
        'feed_frames_with_motion': feed_changes, 'nav_frames_with_motion': nav_pixel_changes,
        'initial_nav_regions': len(nav_keys), 'unchanged_nav_regions_retained': sum(retained), **counts}
    fullscreen['nav_label'] = [nav_label.x, nav_label.y, nav_label.w, nav_label.h]
    fullscreen['nav_tiles'] = [{'index': index, 'captures': tile_captures.get(index, 0),
        'ocr_calls': tile_ocr.get(index, 0)} for index in sorted({index for index, _ in nav_keys})]

    # Replay the same recording as two user-drawn zones. A scrolling feed must
    # never trigger the full capture or detector for the static left navigation.
    video = cv2.VideoCapture(str(path))
    zones = [nav, feed]
    zone_captures = [0, 0]
    zone_ocr = [0, 0]
    current_zone = [0]
    zone_capture_area = [None]

    class ZoneCapture:
        def capture(self, area):
            zone_captures[current_zone[0]] += 1
            zone_capture_area[0] = area
            return current[0][area.y:area.bottom, area.x:area.right].copy()

    class ZoneStubOcr:
        async def read(self, image):
            zone_ocr[current_zone[0]] += 1
            area = zone_capture_area[0]
            if current_zone[0] == 0 and area and image.shape[:2] == (area.h, area.w):
                return [TextBlock('Home', Rect(nav_label.x - area.x, nav_label.y - area.y,
                                               nav_label.w, nav_label.h))]
            return []

    selected = SimpleNamespace(settings=Settings(watch_areas=[[z.x, z.y, z.w, z.h] for z in zones]),
        zone_states={}, tracker=RegionTracker(), preview_capture=None, capture=ZoneCapture(),
        ocr_zone_tracking=True, ocr_lock=asyncio.Lock(), _get_ocr=lambda: ZoneStubOcr(),
        anchors=SimpleNamespace(items={}),
        jobs={}, backoff=float('inf'), generation=1,
        removed=SimpleNamespace(emit=lambda key: None), region_alive=SimpleNamespace(emit=lambda key: None),
        source_lost=SimpleNamespace(emit=lambda key: None))
    selected._scan_ocr_zone = lambda *args, **kwargs: Engine._scan_ocr_zone(selected, *args, **kwargs)
    selected._read_dirty_zone = lambda *args, **kwargs: Engine._read_dirty_zone(selected, *args, **kwargs)
    selected_nav_ids = set()
    nav_events = []
    nav_preview_differences = []
    nav_baseline_differences = []
    prior_nav_preview = None
    index = scan_index = 0
    next_scan = 0.0
    while True:
        ok, frame = video.read()
        if not ok:
            break
        clock[0] = index / fps
        index += 1
        if clock[0] + 1e-6 < next_scan:
            continue
        next_scan += .25
        current[0] = frame
        for zone_index, area in enumerate(zones):
            current_zone[0] = zone_index
            before_capture, before_ocr = zone_captures[0], zone_ocr[0]
            cropped = frame[area.y:area.bottom, area.x:area.right]
            preview = cv2.resize(cropped, (320, 180), interpolation=cv2.INTER_AREA)
            if zone_index == 0:
                if prior_nav_preview is not None:
                    nav_preview_differences.append(int(np.count_nonzero(
                        np.abs(preview.astype(np.int16) - prior_nav_preview.astype(np.int16)) > 12)))
                prior_nav_preview = preview.copy()
                baseline = selected.zone_states.get(0, {}).get('preview')
                if baseline is not None:
                    nav_baseline_differences.append((scan_index, int(np.count_nonzero(
                        np.abs(preview.astype(np.int16) - baseline) > 12))))
            await Engine._scan_zone(selected, zone_index, area, 1, 'Recorded X', np, 0,
                preview=preview, multiple=True)
            if zone_index == 0 and (zone_captures[0] != before_capture or zone_ocr[0] != before_ocr):
                nav_events.append({'scan': scan_index, 'second': round(clock[0], 2),
                    'captures': zone_captures[0] - before_capture,
                    'ocr_calls': zone_ocr[0] - before_ocr})
            if scan_index == 0 and zone_index == 0:
                for region in selected.zone_states[0]['tracker'].regions.values():
                    selected_nav_ids.add(region.id)
                    region.processed = True
                    region.delivered.add('static nav label')
        scan_index += 1
    video.release()
    nav_tracker = selected.zone_states[0]['tracker']
    selected_retained = sum(bool((r := nav_tracker.regions.get(key)) and r.processed
        and r.revision == 0 and r.delivered == {'static nav label'}) for key in selected_nav_ids)
    fullscreen['selected_areas'] = {
        'watch_scans': scan_index,
        'nav_full_captures': zone_captures[0], 'feed_full_captures': zone_captures[1],
        'nav_ocr_calls': zone_ocr[0], 'feed_ocr_calls': zone_ocr[1],
        'nav_preview_change_pixels': {'max': max(nav_preview_differences, default=0),
            'at_least_3': sum(n >= 3 for n in nav_preview_differences),
            'at_least_20': sum(n >= 20 for n in nav_preview_differences),
            'at_least_100': sum(n >= 100 for n in nav_preview_differences)},
        'nav_baseline_large_changes': [(i, n) for i, n in nav_baseline_differences if n >= 20],
        'initial_nav_regions': len(selected_nav_ids), 'unchanged_nav_regions_retained': selected_retained}
    fullscreen['selected_areas']['nav_events'] = nav_events
    engine_module.time = original_engine_time
    return fullscreen


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('video', type=Path)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(analyze(args.video)), indent=2))
