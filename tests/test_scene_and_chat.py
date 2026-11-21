"""Unit coverage for Watch scene reconciliation, chat/dialogue text handling,
line grouping and overlay fitting (fast; no OCR, model or desktop)."""
import numpy as np
import pytest

from arabic_lens.chat import (collapse_elongation, has_translatable_words, join_speaker_runs,
                              prepare_chat, split_speaker)
from arabic_lens.formatting import display_values
from arabic_lens.models import Rect, TextBlock
from arabic_lens.overlay import column_limit_below, reading_seconds, row_limit
from arabic_lens.scene import TextScene, settle_delay
from arabic_lens.text import group_lines, is_list_item

AREA = [Rect(0, 0, 900, 300)]


def text_image(*rects):
    image = np.zeros((300, 900, 4), dtype=np.uint8)
    for r in rects:
        image[r.y:r.bottom, r.x:r.right:3, :3] = 230
    return image


# --- Scene reconciliation ---------------------------------------------------

def test_growing_typed_line_keeps_one_segment_and_retires_fragments():
    scene = TextScene('watch-')
    scene.reconcile([TextBlock('Hell', Rect(10, 10, 40, 18))], AREA, text_image(Rect(10, 10, 40, 18)), 0)
    # OCR briefly split the line, then read it whole: the fragment is absorbed.
    scene.reconcile([TextBlock('Hello, aya', Rect(10, 10, 90, 18)), TextBlock('how', Rect(110, 10, 30, 18))],
                    AREA, text_image(Rect(10, 10, 130, 18)), 1)
    added, updated, moved, removed, replaced = scene.reconcile(
        [TextBlock('Hello, aya, how are you?', Rect(10, 10, 210, 18))], AREA, text_image(Rect(10, 10, 210, 18)), 2)
    assert list(scene.segments) == ['watch-1']
    assert scene.segments['watch-1'].key == 'hello, aya, how are you?'
    assert removed and not replaced


def test_entirely_different_words_at_the_same_place_are_replaced_not_kept():
    scene = TextScene('watch-')
    scene.reconcile([TextBlock('Find the silver key before sunset.', Rect(10, 10, 300, 18))], AREA, text_image(), 0)
    changes = scene.reconcile([TextBlock('The library opens at nine.', Rect(10, 10, 230, 18))], AREA, text_image(), 1)
    assert changes[4] == ['watch-1']  # replaced: old Arabic must leave at once


def test_vanished_text_is_removed_but_an_ocr_miss_on_unchanged_pixels_is_not():
    scene = TextScene('watch-')
    box = Rect(10, 10, 200, 18)
    image = text_image(box)
    scene.reconcile([TextBlock('A sentence on screen.', box)], AREA, image, 0)
    assert scene.reconcile([], AREA, image, 1)[3] == []  # Same pixels: OCR missed it.
    assert scene.reconcile([], AREA, text_image(), 2)[3] == ['watch-1']  # Really gone.


def test_scrolled_chat_line_keeps_identity_and_reports_a_move():
    scene = TextScene('watch-')
    scene.reconcile([TextBlock('Farhan: hello there', Rect(10, 200, 180, 16))], AREA, text_image(), 0)
    changes = scene.reconcile([TextBlock('Farhan: hello there', Rect(10, 140, 180, 16))], AREA, text_image(), 1)
    assert changes[2] == ['watch-1'] and scene.segments['watch-1'].rect.y == 140


def test_history_keeps_a_finished_line_separate_from_text_typed_below_it():
    scene = TextScene('watch-')
    first = TextBlock('This is a test sentence', Rect(10, 40, 220, 18))
    scene.reconcile([first], [Rect(0, 0, 900, 300)], text_image(), 0)
    line1 = TextBlock('This is a test sentence', Rect(10, 40, 220, 18))
    line2 = TextBlock('how are things going?', Rect(10, 62, 190, 18))
    merged = TextBlock('This is a test sentence how are things going?', Rect(10, 40, 220, 40))
    merged._lines = [line1, line2]
    pieces = scene.split_by_history([merged])
    assert [p.text for p in pieces] == ['This is a test sentence', 'how are things going?']


@pytest.mark.parametrize('text,slow', [('Find the key.', False), ('Th', True), ('This is a sentenc', True)])
def test_partially_typed_words_wait_longer_than_complete_phrases(text, slow):
    assert (settle_delay(text) > .5) == slow


def test_segment_being_typed_is_not_translated_until_its_pixels_settle():
    scene = TextScene('watch-')
    box = Rect(10, 10, 200, 18)
    scene.reconcile([TextBlock('Find the key.', box)], AREA, text_image(box), 0)
    assert scene.due(5, image=text_image(box))  # Settled.
    typing = text_image(box)
    typing[12:26, 150:210, :3] = 0  # Letters inside the line changed since the read.
    assert not scene.due(5, image=typing)  # Still being typed: wait.


# --- Line grouping -------------------------------------------------------------

def test_separately_typed_lines_are_not_merged_into_one_paragraph():
    lines = [TextBlock('Hello, aya, how are you?', Rect(0, 0, 210, 18)),
             TextBlock('This is a test sentence to test the translation', Rect(0, 22, 400, 18)),
             TextBlock('How are things going?', Rect(0, 44, 180, 18))]
    assert [b.text for b in group_lines(lines, 900)] == [l.text for l in lines]


def test_wrapped_paragraph_stays_whole():
    lines = [TextBlock('Collect three silver keys from the old library before the sun', Rect(0, 0, 500, 18)),
             TextBlock('goes down, then bring them back to the guard at the gate.', Rect(0, 22, 470, 18))]
    assert len(group_lines(lines, 900)) == 1


def test_clock_times_are_not_label_value_rows():
    assert not is_list_item('23:33 Farhan: hi') and is_list_item('Gold: 50')


# --- Chat and dialogue ------------------------------------------------------------

@pytest.mark.parametrize('line,prefix,body', [
    ('23:33 MrMoonie: dont jp us', '23:33 MrMoonie: ', 'dont jp us'),
    ("Aya: I'm good, what are you doing right now?", 'Aya: ', "I'm good, what are you doing right now?"),
    ('Happy9234: wssup', 'Happy9234: ', 'wssup'),
    ('Jimmy Jon: Now follow the next path as highlighted on the screen.', 'Jimmy Jon: ',
     'Now follow the next path as highlighted on the screen.'),
    ('Replying to @Fylypzz: is it gta v rp?', '@Fylypzz: ', 'is it gta v rp?'),
    ('Warning: the bridge is out', '', 'Warning: the bridge is out'),
    ('Main Quest: Find the ring', '', 'Main Quest: Find the ring'),
    ('The Lost Ring: Chapter 2', '', 'The Lost Ring: Chapter 2'),
    ('so here: it is', '', 'so here: it is'),
])
def test_speaker_names_are_kept_and_labels_are_not_mistaken_for_names(line, prefix, body):
    assert split_speaker(line) == (prefix, body)


def test_chat_slang_nicknames_and_elongation():
    assert prepare_chat('dont jp us') == ("don't jp us", ['jp'])
    assert prepare_chat('NAHHHHHHHHH LMAO') == ('no LMAO', ['LMAO'])
    assert prepare_chat('wssup')[0] == "what's up"
    assert collapse_elongation('goooood') == 'good' and collapse_elongation('soooo').lower().startswith('so')
    assert not has_translatable_words('LMAO KEKW')
    # Outside chat, ordinary words are not reinterpreted as slang.
    assert prepare_chat('rip the page and press R', chat=False) == ('rip the page and press R', [])


def test_ocr_split_name_and_message_are_rejoined():
    lines = [TextBlock('23:33 MrMoonie.', Rect(5, 93, 125, 12)), TextBlock('• dont jp us', Rect(127, 93, 76, 16)),
             TextBlock('CRASH •', Rect(173, 193, 73, 21)), TextBlock('23:33 SexyLithuanian:', Rect(5, 198, 163, 16))]
    assert sorted(b.text for b in join_speaker_runs(lines)) == ['23:33 MrMoonie: dont jp us',
                                                                 '23:33 SexyLithuanian: CRASH']


def test_clock_time_and_speaker_display_left_to_right_in_arabic():
    shown = display_values('23:33 Farhan: مرحبا 10:30')
    # Time and name are separate LTR units; the colon stays in the RTL flow so
    # it sits between the name and the Arabic message.
    assert shown.startswith('⁦23:33⁩ ⁦Farhan⁩: ')
    assert display_values('Jimmy Jon: اتبع').startswith('⁦Jimmy Jon⁩: ')
    assert '⁦10:30⁩' in shown  # Not "⁦10⁩:⁦30⁩" (shown as 30:10).


# --- Overlay fitting ----------------------------------------------------------------

def test_replace_overlay_stops_before_the_value_beside_its_label():
    label = Rect(70, 70, 50, 14)
    value = Rect(133, 68, 60, 18)
    assert row_limit(label, [value, Rect(70, 100, 90, 14)]) == 133
    assert row_limit(label, [Rect(70, 100, 90, 14)]) is None


def test_automatic_quick_reading_time_scales_with_length():
    assert reading_seconds('مرحبا') == 4.0
    long = ' '.join(['كلمة'] * 60)
    assert 20 < reading_seconds(long) <= 60


def test_covering_overlay_does_not_grow_down_over_the_next_line():
    message = Rect(10, 100, 300, 34)  # A wrapped two-line chat message.
    next_line = Rect(10, 140, 200, 16)
    assert column_limit_below(message, [next_line, Rect(400, 140, 50, 16)]) == 140
    assert column_limit_below(message, [Rect(10, 40, 200, 16)]) is None


def test_limit_height_widens_then_shrinks_type_to_fit():
    from PySide6.QtWidgets import QApplication
    from arabic_lens.config import OverlaySettings
    from arabic_lens.overlay import TranslationOverlay
    QApplication.instance() or QApplication([])
    overlay = TranslationOverlay(OverlaySettings(), ' '.join(['كلمة'] * 15))
    overlay.fit_to_source(Rect(0, 0, 220, 34))
    assert overlay.height() > 60
    overlay.limit_height(60, 420)
    assert overlay.height() <= 60 and overlay.width() <= 420
    assert overlay.document.defaultFont().pixelSize() >= 12  # Still readable.
    # Impossible to fit: keeps the smallest readable size rather than vanishing.
    crowded = TranslationOverlay(OverlaySettings(), ' '.join(['كلمة'] * 60))
    crowded.fit_to_source(Rect(0, 0, 220, 34))
    before = crowded.document.defaultFont().pixelSize()
    crowded.limit_height(40, 260)
    # Shrinks at most 20%, so neighbouring lines keep a matching size.
    assert crowded.document.defaultFont().pixelSize() == max(10, round(before * .8))
    overlay.deleteLater(); crowded.deleteLater()


def test_covering_overlays_take_the_size_of_the_text_they_cover():
    from PySide6.QtWidgets import QApplication
    from arabic_lens.config import OverlaySettings
    from arabic_lens.overlay import TranslationOverlay
    QApplication.instance() or QApplication([])
    sizes, heights = [], []
    for text in ('مرحبا، ما الأمر؟',
                 'أنا جيد، ماذا تفعل الآن؟'):
        overlay = TranslationOverlay(OverlaySettings(), text)
        overlay.fit_to_source(Rect(0, 0, 260, 16), max_extra=160, line_height=16)
        sizes.append(overlay.document.defaultFont().pixelSize())
        heights.append(overlay.height())
        overlay.deleteLater()
    assert sizes[0] == sizes[1] == 16          # Same size as the English it covers.
    assert max(heights) <= 24                  # About one chat line pitch.


@pytest.mark.parametrize('raw,clean', [
    ('CRASH •', 'CRASH'),
    ('now HONK 😂😂', 'now HONK'),
    ('I ❤ this game', 'I this game'),
    ('• Collect the keys', '• Collect the keys'),  # A real list bullet stays.
])
def test_emotes_and_icons_never_reach_translation(raw, clean):
    from arabic_lens.text import clean_source_text
    assert clean_source_text(raw) == clean
