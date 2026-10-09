import os
import asyncio
from pathlib import Path

import pytest

from tools.analyze_watch_video import analyze


def test_recorded_x_scroll_keeps_static_navigation_out_of_watch_ocr():
    recording = Path(os.environ.get('ARABIC_LENS_WATCH_VIDEO', 'artifacts/fixtures/watch-scroll.mp4'))
    if not recording.exists():
        pytest.skip('User-provided X scroll recording is unavailable')
    result = asyncio.run(analyze(recording))
    selected = result['selected_areas']
    assert result['frames'] == 153 and result['watch_scans'] >= 20
    assert result['feed_frames_with_motion'] >= 15
    assert result['nav_frames_with_motion'] == 0
    assert result['unchanged_nav_regions_retained'] == result['initial_nav_regions'] == 1
    assert selected['unchanged_nav_regions_retained'] == selected['initial_nav_regions'] == 1
    assert selected['feed_full_captures'] >= 15
    assert selected['nav_full_captures'] == selected['nav_ocr_calls'] == 1
    # The fullscreen tile also includes X's top header, which genuinely
    # changes once in the recording. That local crop may be read again, but
    # the unchanged Home text must keep its region and translation identity.
    assert result['nav_tiles'] == [{'index': 0, 'captures': 2, 'ocr_calls': 2}]
    assert result['removed'] == 0
