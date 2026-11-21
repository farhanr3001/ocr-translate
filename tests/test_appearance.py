import numpy as np
from arabic_lens.config import OverlaySettings
from arabic_lens.appearance import effective_appearance, sample_style


def test_source_matching_is_optional_and_does_not_mutate_settings():
    base = OverlaySettings(font='Segoe UI', text_color='#fefefe')
    assert effective_appearance(base) == base
    base.match_game = True
    appearance = effective_appearance(base)
    assert appearance.font == 'Segoe UI'
    assert appearance.background_color == '#131415'
    assert base.font == 'Segoe UI' and base.text_color == '#fefefe'
    assert appearance.duration == base.duration and appearance.position == base.position


def test_generic_appearance_uses_bounded_capture_sample():
    light = sample_style(np.full((900, 1600, 3), 245, np.uint8))
    dark = sample_style(np.full((900, 1600, 4), 15, np.uint8))
    base = OverlaySettings(match_game=True)
    assert effective_appearance(base, light).text_color == '#272c30'
    assert effective_appearance(base, dark).text_color == '#ffffff'


def test_long_overlay_avoids_requirements_and_nearby_text():
    from arabic_lens.models import Rect
    from arabic_lens.overlay import place_overlay
    source = Rect(287, 111, 440, 141)
    requirements = Rect(314, 296, 216, 189)
    side_text = Rect(917, 104, 156, 46)
    placed = place_overlay(source, 500, 180, Rect(0, 0, 1920, 1080), [requirements, side_text])
    assert placed.overlap(source) == placed.overlap(requirements) == placed.overlap(side_text) == 0
