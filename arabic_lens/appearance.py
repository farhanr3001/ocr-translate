"""Optional external appearance matching, without reading game assets/processes."""
from dataclasses import replace
import numpy as np


def sample_style(image):
    # Sample a small bounded grid of pixels in the already captured OCR crop.
    pixels = image[::max(1, image.shape[0] // 24), ::max(1, image.shape[1] // 48), :3]
    b, g, r = np.median(pixels.reshape(-1, 3), axis=0)
    return {'background': [int(r), int(g), int(b)]}


def effective_appearance(base, application='', hint=None):
    if not base.match_game:
        return replace(base)
    if (hint or {}).get('cell_background'):
        rgb = hint['cell_background']
        luminance = sum(a * b for a, b in zip(rgb, [.2126, .7152, .0722]))
        return replace(base, font='Segoe UI', font_size=20,
            text_color='#493b31' if luminance > 185 else '#ffffff',
            background_color='#' + ''.join(f'{c:02x}' for c in rgb), background_opacity=100,
            padding=2, radius=2, shadow=False, outline=0, border_width=0)
    if 'dressmaker' in application.casefold():
        return replace(base, font='Traditional Arabic', font_size=34,
            text_color='#493b31', background_color='#f7eee2', background_opacity=96,
            padding=14, radius=5, outline=0, shadow=False,
            border_color='#ad8b51', border_width=1)
    rgb = (hint or {}).get('background', [25, 29, 34])
    luminance = sum(a * b for a, b in zip(rgb, [.2126, .7152, .0722]))
    light = luminance > 145
    # Desaturate toward a readable light/dark surface instead of copying a busy
    # scene literally. Exact game font recognition is deliberately not claimed.
    neutral = 245 if light else 18
    mixed = [round(c * .18 + neutral * .82) for c in rgb]
    return replace(base, font='Segoe UI', text_color='#272c30' if light else '#ffffff',
        background_color='#' + ''.join(f'{c:02x}' for c in mixed),
        background_opacity=90, shadow=not light, outline=0, border_width=0)


def sample_cell_style(image, block):
    hint = sample_style(image)
    if block.standalone:
        bounds = block.container or block.rect
        if not block.container:
            from .models import Rect
            bounds = Rect(bounds.x - 4, bounds.y - 3, bounds.w + 8, bounds.h + 6)
        crop = image[max(0, bounds.y):min(image.shape[0], bounds.bottom), max(0, bounds.x):min(image.shape[1], bounds.right), :3]
        if crop.size:
            # The modal colour rejects foreground glyphs and anti-aliasing,
            # unlike a median taken inside a tightly bounded text rectangle.
            pixels = crop.reshape(-1, 3)
            quantized = pixels // 16
            colours, counts = np.unique(quantized, axis=0, return_counts=True)
            modal = colours[counts.argmax()]
            b, g, r = np.median(pixels[np.all(quantized == modal, axis=1)], axis=0)
            hint['cell_background'] = [int(r), int(g), int(b)]
    return hint
