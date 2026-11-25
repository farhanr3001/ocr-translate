"""Drive the real app (capture, Windows OCR, bundled model, overlays) against
separate-process fixtures and check what the user would see.

Usage: python tools/live_scenarios.py OUTDIR SCENARIO [SECONDS]
       python tools/live_scenarios.py OUTDIR all

Set ARABIC_LENS_REFUSE_EXCLUSION=1 to behave like a PC whose Windows refuses
overlay capture exclusion (Windows 11 build 22000), for parity comparisons.

Each run writes OUTDIR/<scenario>/summary.json (events, overlay snapshots,
final overlays) and prints PASS/FAIL lines for the scenario's expectations.
These are developer checks on a real desktop; they briefly show windows.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from arabic_lens.windows import enable_dpi  # noqa: E402
enable_dpi()
from PySide6.QtWidgets import QApplication  # noqa: E402
import arabic_lens.app as app_module  # noqa: E402
import arabic_lens.overlay as overlay_module  # noqa: E402
from arabic_lens.app import Application  # noqa: E402
from arabic_lens.models import Rect  # noqa: E402
from arabic_lens.windows import window_identity  # noqa: E402

LINES = ["Hello, aya, how are you?", "This is a test sentence to test the translation", "how are things going?"]
WRAP = ("This is one long sentence that keeps going across the editor so that it must wrap "
        "onto a second line and still be translated as one complete thought")
TUTORIAL = {"title": "How to play", "lines": [
    "Press E to open the door.",
    "Collect three silver keys from the old library before the sun goes down, then bring them back to the guard at the gate.",
    "Avoid the wolves in the forest.",
    "Your health slowly returns while you rest by a campfire, but resting at night lets the wolves come closer.",
]}
TUTORIAL_B = {"title": "Crafting", "lines": [
    "Open your bag with the I key.",
    "Combine two pieces of wood and one stone to make a simple axe for chopping trees.",
    "Sell extra items to the merchant in the village.",
]}


def has(events, kind, needle=None):
    return [e for e in events if e[1] == kind and (needle is None or needle.lower() in ' '.join(e[2:]).lower())]


def visible_at(snapshots, t):
    """Overlay ids visible at the last snapshot at or before time t."""
    current = []
    for when, ids in snapshots:
        if when <= t:
            current = ids
    return current


SCENARIOS = {}


def scenario(name, fixture, steps, seconds, watch=False, quick_at=None, setup=None):
    def register(check):
        SCENARIOS[name] = dict(fixture=fixture, steps=steps, seconds=seconds, watch=watch,
                               quick_at=quick_at, setup=setup, check=check)
        return check
    return register


@scenario('typewriter', 'editor', [{'type': 'wait', 'ms': 1500}] + [s for line in LINES for s in (
    {'type': 'text', 'text': line, 'delay_ms': 90}, {'type': 'text', 'text': '\n', 'delay_ms': 700})]
    + [{'type': 'wait', 'ms': 4000}], 21, watch=True)
def _(r):
    final = r['final']
    sources = sorted(f['source'] for f in final)
    yield 'three separate overlays, one per typed line', len(final) == 3, sources
    yield 'line 3 kept separate from line 2', any(s.startswith('how are things') for s in sources), sources
    yield 'no fragments left behind', all(len(s) > 12 for s in sources), sources


@scenario('typewriter_wrap', 'editor', [{'type': 'wait', 'ms': 1500}, {'type': 'text', 'text': WRAP, 'delay_ms': 45},
          {'type': 'wait', 'ms': 4000}], 18, watch=True)
def _(r):
    final = r['final']
    yield 'one overlay for the wrapped sentence', len(final) == 1, [f['source'] for f in final]
    yield 'translation covers the whole sentence', bool(final) and final[0]['source'].rstrip('.').endswith('complete thought'), [f['source'][-40:] for f in final]


@scenario('rewrite', 'editor', [{'type': 'wait', 'ms': 1500}, {'type': 'text', 'text': 'Find the silver key before sunset.', 'delay_ms': 60},
          {'type': 'wait', 'ms': 2500}, {'type': 'backspace', 'count': 34, 'delay_ms': 20},
          {'type': 'text', 'text': 'The library opens at nine.', 'delay_ms': 60}, {'type': 'wait', 'ms': 4000}], 18, watch=True)
def _(r):
    final = r['final']
    yield 'first sentence was translated', bool(has(r['events'], 'translated', 'silver key')), ''
    yield 'only the new sentence remains', len(final) == 1 and 'library opens at nine' in final[0]['source'], [f['source'] for f in final]


CAPS = [LINES[0], LINES[1], 'How are things going?']


def static_lines_ok(sources):
    # A still frame cannot tell whether a lowercase line continues the line
    # above (no period); merging those two is accepted, line 1 must be alone.
    return 'hello, aya, how are you?' in sources and len(sources) in (2, 3)


@scenario('quick', 'editor', [{'type': 'set', 'text': '\n'.join(LINES) + '\n'}], 8, quick_at=2.0)
def _(r):
    sources = [f['source'] for f in r['final']]
    yield 'quick keeps the separate sentence apart', static_lines_ok(sources), sources


@scenario('quick_caps', 'editor', [{'type': 'set', 'text': '\n'.join(CAPS) + '\n'}], 8, quick_at=2.0)
def _(r):
    yield 'quick shows every capitalised line separately', len(r['final']) == 3, [f['source'] for f in r['final']]


@scenario('quick_caret', 'editor', [{'type': 'set', 'text': '\n'.join(LINES)}], 10, quick_at=2.0)
def _(r):
    yield 'blinking caret does not remove quick overlays', static_lines_ok([f['source'] for f in r['final']]), [f['source'] for f in r['final']]
    yield 'no source_lost events', not has(r['events'], 'source_lost'), has(r['events'], 'source_lost')


@scenario('quick_noexclude', 'editor', [{'type': 'set', 'text': '\n'.join(LINES)}], 10, quick_at=2.0,
          setup=lambda: setattr(overlay_module, 'exclude_capture', lambda widget: False))
def _(r):
    yield 'overlays survive when capture exclusion is refused', static_lines_ok([f['source'] for f in r['final']]), [f['source'] for f in r['final']]
    yield 'no source_lost events', not has(r['events'], 'source_lost'), has(r['events'], 'source_lost')


@scenario('quick_edit', 'editor', [{'type': 'set', 'text': '\n'.join(CAPS)}, {'type': 'wait', 'ms': 5500},
          {'type': 'backspace', 'count': len(CAPS[2]) + 1, 'delay_ms': 15},
          {'type': 'wait', 'ms': 3000}, {'type': 'clear'}, {'type': 'wait', 'ms': 3000}], 14, quick_at=2.0)
def _(r):
    lost = has(r['events'], 'source_lost')
    yield 'three overlays after quick', len(visible_at(r['snapshots'], 4.5)) == 3, visible_at(r['snapshots'], 4.5)
    middle = visible_at(r['snapshots'], 8.5)
    yield 'erasing line 3 removes only its overlay', len(middle) == 2, middle
    yield 'clearing the text removes the rest', not r['final'], [f['source'] for f in r['final']]


@scenario('quick_timer', 'editor', [{'type': 'set', 'text': LINES[0]}], 11, quick_at=2.0,
          setup='timer')
def _(r):
    shown = [t for t, ids in r['snapshots'] if ids]
    yield 'timed quick overlay appeared', bool(shown), r['snapshots']
    yield 'and hid itself after its reading time', not r['final'] and shown and shown[-1] < 10, shown[-1:] if shown else ''


@scenario('quick_watch', 'editor', [{'type': 'set', 'text': '\n'.join(CAPS) + '\n'}], 9, watch=True, quick_at=4.0)
def _(r):
    ids = [f['id'] for f in r['final']]
    yield 'watch shows three lines', len([i for i in ids if i.startswith('watch-')]) == 3, ids
    yield 'quick on the same text adds no duplicate overlays', len(ids) == 3, ids


POPUP_STEPS = [{'type': 'wait', 'ms': 1200}, {'type': 'show', **TUTORIAL}, {'type': 'wait', 'ms': 6000},
               {'type': 'show', **TUTORIAL_B}, {'type': 'wait', 'ms': 6000}, {'type': 'hide'}, {'type': 'wait', 'ms': 4000}]


@scenario('popup_watch', 'popup', POPUP_STEPS, 20, watch=True)
def _(r):
    first = r['snap_by_source'](6.5)
    yield 'tutorial: title + four instructions, wrapped ones whole', len(first) == 5, first
    yield 'long wrapped instruction is one translation', any(s.startswith('collect three silver keys') and s.endswith('gate') for s in first), first
    second = r['snap_by_source'](13.0)
    yield 'new popup replaces old instructions (no stale)', len(second) == 4 and not any('wolves' in s for s in second), second
    yield 'popup closing removes all overlays', not r['final'], [f['source'] for f in r['final']]


@scenario('popup_quick', 'popup', [{'type': 'wait', 'ms': 600}, {'type': 'show', **TUTORIAL}, {'type': 'wait', 'ms': 7000},
          {'type': 'hide'}, {'type': 'wait', 'ms': 4000}], 14, quick_at=2.5)
def _(r):
    shown = r['snap_by_source'](7.0)
    yield 'quick: title + four instructions', len(shown) == 5, shown
    yield 'quick overlays leave with the popup', not r['final'], [f['source'] for f in r['final']]


CHAT = [
    ['Farhan', '#ff7f50', "Hello, what's up?"],
    ['Aya', '#9acd32', "I'm good, what are you doing right now?"],
    ['Happy9234', '#1e90ff', 'wssup'],
    ['kinebito', '#00ff7f', 'NAHHHHHHHHH LMAO'],
    ['MrMoonie', '#8a2be2', 'dont jp us'],
    ['machiav__', '#5f9ea0', 'gta 4'],
    ['FenrirLr', '#ff69b4', 'the pink car is parked outside the bank again'],
    ['zylai_01', '#daa520', 'happens'],
    ['SexyLithuanian', '#9370db', 'CRASH [emote]'],
    ['gtsirmichael', '#1e90ff', 'now HONK'],
    ['Nameless_69', '#2e8b57', '[emote]'],
    ['JasonP999', '#32cd32', 'Sign the contract before the police arrive'],
    ['kreuzle', '#b22222', 'that was the best chase I have seen all week, honestly the driving was insane'],
    ['reDREWO', '#ff4500', 'lol he really did that'],
    ['wassupnik', '#00ced1', 'xqc is my pilot xqc is my pilot xqc is my pilot'],
    ['Aya', '#9acd32', 'can you send me the link please?'],
    ['Farhan', '#ff7f50', 'I will send it after the stream ends'],
    ['foknbruh', '#ffd700', 'pink car again smh'],
    ['MrMoonie', '#8a2be2', 'where is the hospital in this city?'],
    ['Happy9234', '#1e90ff', 'GG everyone, see you tomorrow'],
]


def chat_scenario(name, interval, seconds):
    @scenario(name, 'chat', {'interval_ms': interval, 'messages': CHAT, 'start_ms': 1500}, seconds, watch=True)
    def _(r):
        visible = r['visible']
        final = r['final']
        expected = [m for m in visible if r['translatable'](m[1])]
        sources = [f['source'] for f in final]
        matched = [m for m in expected if any(m[1].lower()[:18] in s for s in sources)]
        yield f'most visible messages translated at rest ({len(matched)}/{len(expected)})', len(matched) >= max(1, round(len(expected) * .8)), sources
        stale = [s for s in sources if not any(m[1].lower()[:14] in s for m in visible)]
        yield 'no overlay for messages that scrolled away', not stale, stale
        yield 'no duplicate overlays', len(sources) == len(set(sources)), sources
        named = [f for f in final if ':' in f['arabic']]
        yield 'usernames kept before the translated message', len(named) >= len(final) * .8, [f['arabic'][:40] for f in final]
        kept = [f['arabic'] for f in final if ' jp ' in f['source']]  # OCR may glue "dontjp".
        yield 'nickname "jp" kept as written', all('jp' in a for a in kept), kept
        # Every visible chat line may carry one overlay; a pile-up means far more.
        yield 'overlay positions follow the scroll (no pile-up)', r['max_overlays'] <= len(CHAT) + 2, r['max_overlays']

        def overlaps(boxes):
            items = list(boxes.values())
            pairs = []
            for i, a in enumerate(items):
                for b in items[i + 1:]:
                    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
                    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
                    if w > 4 and h > 3:
                        pairs.append((a, b))
            return pairs
        snaps = r['raw_snapshots']
        busy = [s for s in snaps if overlaps(s[5])]
        yield 'overlays never overlap once the chat is at rest', not overlaps(snaps[-1][5]), overlaps(snaps[-1][5])[:3]
        yield f'overlapping overlays rare while scrolling ({len(busy)}/{len(snaps)} snapshots)', len(busy) <= len(snaps) * .15, [s[0] for s in busy][:10]
    return _


@scenario('chat_moderated', 'chat', {'interval_ms': 1400, 'messages': CHAT[:14], 'start_ms': 1500,
          'max_messages': 8, 'delete': {'after': 5, 'position': 2}, 'clear_after': 0}, 26, watch=True)
def _(r):
    removals = r['removals']
    deleted = [e['removed'] for e in removals]
    yield f'messages were removed by the chat ({len(deleted)})', len(deleted) >= 3, deleted
    late = []
    for event in removals:
        name, text = event['removed']
        gone_at = event['t'] - r['harness_started']
        key = text.lower()[:16]
        # Still covered 2 s after it vanished (unless an identical message is
        # still on screen).
        still = [s for when, ids, sources, *rest in r['raw_snapshots'] if when >= gone_at + 2.0
                 for s in sources.values() if key in s]
        if still and not any(text == m[1] for m in r['visible']):
            late.append((name, text))
    yield 'a removed message loses its translation within 2 s', not late, late
    final = [f['source'] for f in r['final']]
    visible = [m for m in r['visible'] if r['translatable'](m[1])]
    stale = [s for s in final if not any(m[1].lower()[:14] in s for m in r['visible'])]
    yield 'no translation left for a message that is gone', not stale, stale
    yield 'remaining messages keep their translations', sum(any(m[1].lower()[:16] in s for s in final) for m in visible) >= len(visible) * .8, final


@scenario('chat_cleared', 'chat', {'interval_ms': 900, 'messages': CHAT[:8], 'start_ms': 1500,
          'clear_after': 8}, 16, watch=True)
def _(r):
    yield 'clearing the chat removes every translation', not r['final'], [f['source'] for f in r['final']]


for _name, _interval in (('chat_slow', 2000), ('chat_medium', 900), ('chat_fast', 350)):
    chat_scenario(_name, _interval, 1.5 + len(CHAT) * _interval / 1000 + 6)


HUD_STEPS = [
    {'at_ms': 500, 'objective': ['Talk to the blacksmith in the village.']},
    {'at_ms': 1200, 'speaker': 'Elder', 'cps': 28,
     'say': 'Welcome, traveller. The road to the north is dangerous after dark, so keep your torch lit.'},
    {'at_ms': 6000, 'notice': 'New area discovered: Old Mill'},
    {'at_ms': 8500, 'notice': ''},
    {'at_ms': 9500, 'objective': ['Find the ring near the old mill.', 'Return the ring to the Elder before nightfall.']},
    {'at_ms': 10500, 'say': 'Thank you. Take this map and follow the river until you reach the bridge.'},
    {'at_ms': 16500, 'say': ''},
]


def hud_checks(r, fullscreen):
    def has_text(sources, needle):
        return any(needle in s for s in sources)

    def inside(rect, part):
        cx, cy = rect[0] + rect[2] / 2, rect[1] + rect[3] / 2
        return part[0] <= cx <= part[0] + part[2] and part[1] <= cy <= part[1] + part[3]

    hud_translations = [e for e in r['events'] if e[1] == 'translated' and 'health' in e[3].lower()]
    yield 'HUD label translated and stable under an animated background', 1 <= len(hud_translations) <= 2, len(hud_translations)
    sources, _ = r['at_game_time'](8.0)
    dialogue = [s for s in sources.values() if 'road to the north' in s]
    yield 'typed dialogue shown once, as the full sentence', len(dialogue) == 1 and dialogue[0].rstrip('.').endswith('torch lit'), dialogue
    yield 'quest objective translated', has_text(sources.values(), 'blacksmith'), sorted(sources.values())
    if fullscreen:
        yield 'notification translated while shown', has_text(sources.values(), 'old mill'), sorted(sources.values())
    sources, _ = r['at_game_time'](10.2)
    if fullscreen:
        yield 'notification overlay leaves with the notification', not has_text(sources.values(), 'new area'), sorted(sources.values())
    sources, _ = r['at_game_time'](15.5)
    yield 'changed objective replaces the old one', (has_text(sources.values(), 'find the ring')
        and has_text(sources.values(), 'return the ring') and not has_text(sources.values(), 'blacksmith')), sorted(sources.values())
    yield 'next dialogue line replaces the previous one', (has_text(sources.values(), 'follow the river')
        and not has_text(sources.values(), 'road to the north')), sorted(sources.values())
    sources, _ = r['at_game_time'](19.0)
    yield 'closed dialogue box removes its overlay', not has_text(sources.values(), 'follow the river'), sorted(sources.values())
    misplaced = []
    game = r['game_rect']
    for snapshot in r['raw_snapshots']:
        for key, rect in snapshot[3].items():
            # Full-screen Watch follows the active window; before the game has
            # focus it may translate another app, which is not game drift.
            if not inside(rect, game):
                continue
            if not any(inside(rect, part) for part in r['parts'].values()):
                misplaced.append((snapshot[0], snapshot[2].get(key), rect))
    yield 'every overlay sits on its own HUD part (no drift or mess)', not misplaced, misplaced[:4]
    mixed = [s for snap in r['raw_snapshots'] for s in snap[2].values()
             if sum(k in s for k in ('health', 'quest:', 'elder', 'discovered')) > 1]
    yield 'no text merged across HUD parts', not mixed, mixed[:3]
    value = r['health_value']
    covering = []
    for snapshot in r['raw_snapshots']:
        for key, box in snapshot[5].items():
            source = snapshot[2].get(key, '')
            row = min(box[1] + box[3], value[1] + value[3]) - max(box[1], value[1]) > 0
            if 'health' in source and row and box[0] + box[2] > value[0]:
                covering.append((snapshot[0], box, value[0]))
    yield 'HUD label overlay never covers the value beside it (85 / 100)', not covering, covering[:3]


SUBTITLE_STEPS = [
    {'at_ms': 500, 'objective': ['Talk to the blacksmith in the village.']},
    {'at_ms': 1200, 'style': 'subtitle', 'speaker': 'Jimmy Jon', 'cps': 26,
     'say': 'Now follow the next path as highlighted on the screen.'},
    {'at_ms': 6500, 'say': 'Watch out for the guards near the gate.'},
    {'at_ms': 11500, 'say': ''},
]


@scenario('hud_fullscreen', 'hud', HUD_STEPS, 22, watch='fullscreen', setup='pin_game')
def _(r):
    yield from hud_checks(r, True)


@scenario('hud_fullscreen_large', 'hud', [{'size': [1560, 860]}] + HUD_STEPS, 22, watch='fullscreen', setup='pin_game')
def _(r):
    yield from hud_checks(r, True)


def subtitle_checks(r):
    sources, _ = r['at_game_time'](5.5)
    first = [s for s in sources.values() if 'follow the next path' in s]
    yield 'borderless subtitle translated once, whole line', len(first) == 1 and first[0].rstrip('.').endswith('on the screen'), sorted(sources.values())
    arabic = [e[4] for e in r['events'] if e[1] == 'translated' and 'follow the next path' in e[3]]
    yield 'speaker name kept before the subtitle', bool(arabic) and arabic[-1].startswith('Jimmy Jon:'), arabic[-1:]
    sources, _ = r['at_game_time'](10.5)
    yield 'next subtitle replaces the previous one', (any('guards near the gate' in s for s in sources.values())
        and not any('follow the next path' in s for s in sources.values())), sorted(sources.values())
    sources, _ = r['at_game_time'](14.0)
    yield 'subtitle overlay leaves when the subtitle ends', not any('guards' in s for s in sources.values()), sorted(sources.values())


@scenario('subtitle_fullscreen', 'hud', SUBTITLE_STEPS, 16, watch='fullscreen', setup='pin_game')
def _(r):
    yield from subtitle_checks(r)


@scenario('subtitle_area', 'hud', SUBTITLE_STEPS, 16, watch='parts')
def _(r):
    yield from subtitle_checks(r)


@scenario('hud_areas', 'hud', HUD_STEPS, 22, watch='parts')
def _(r):
    yield from hud_checks(r, False)


def save_composite(path, fixture, app):
    """What the user sees: the fixture's pixels with our overlays painted on
    (overlays are excluded from screen capture, so they are drawn here)."""
    from PySide6.QtGui import QImage, QPainter, QPixmap
    from arabic_lens.overlay import logical_to_physical
    from arabic_lens.windows import CaptureService
    x, y, w, h = fixture['rect']
    capture = CaptureService()
    try:
        image = capture.capture(Rect(x, y, w, h)).copy()
    finally:
        capture.close()
    canvas = QPixmap.fromImage(QImage(image.data, w, h, image.strides[0], QImage.Format_ARGB32).copy())
    painter = QPainter(canvas)
    for win in app.overlays.windows.values():
        if not win.isVisible() or win.closing:
            continue
        r = logical_to_physical(win.screen(), Rect(win.x(), win.y(), win.width(), win.height()))
        painter.setOpacity(win.windowOpacity())
        painter.drawPixmap(r.x - x, r.y - y, r.w, r.h, win.grab())
    painter.end()
    canvas.save(str(path))


def run(out, name, seconds=None):
    spec = SCENARIOS[name]
    seconds = seconds or spec['seconds']
    out.mkdir(parents=True, exist_ok=True)
    for item in out.glob('*'):
        if item.is_file():
            item.unlink()
    if callable(spec['setup']):
        spec['setup']()
    if os.environ.get('ARABIC_LENS_REFUSE_EXCLUSION') == '1':
        # Behave like Windows 11 build 22000: every capture-exclusion request
        # is refused, so all of our windows are visible to screen capture.
        import arabic_lens.progress as progress_module
        import arabic_lens.selection as selection_module
        import arabic_lens.windows as windows_module
        for module in (overlay_module, progress_module, selection_module, windows_module):
            setattr(module, 'exclude_capture', lambda widget: False)
    (out / 'script.json').write_text(json.dumps(spec['steps']))
    qt = QApplication.instance() or QApplication([])
    qt.setProperty('smokeTest', True)
    qt.setQuitOnLastWindowClosed(False)
    fixture_script = root / 'tests/fixtures' / {'editor': 'editor_window.py', 'popup': 'popup_window.py',
                                                 'chat': 'chat_window.py', 'hud': 'hud_window.py'}[spec['fixture']]
    child = subprocess.Popen([sys.executable, str(fixture_script), str(out), str(out / 'script.json')],
                             env=dict(os.environ, PYTHONPATH=str(root)))
    deadline = time.monotonic() + 15
    while not (out / 'ready.json').exists():
        if time.monotonic() > deadline or child.poll() is not None:
            raise SystemExit('fixture did not start')
        time.sleep(.05)
    fixture = json.loads((out / 'ready.json').read_text())
    app_module.HotkeyManager.register = lambda *args, **kwargs: None
    app = Application(qt, out / 'data')
    app.window.hide()
    if spec['setup'] == 'timer':
        app.settings.overlay.quick_lifetime = 'timer'
        app.settings.overlay.quick_seconds = 0
    events, snapshots = [], []
    started = time.monotonic()

    def log(*item):
        events.append([round(time.monotonic() - started, 2)] + [str(v) for v in item])

    app.engine.translated.connect(lambda r: log('translated', r.id, r.source, r.arabic, r.rect,
                                                [a for a in r.avoid_regions if abs(a.y - r.rect.y) < 30]))
    app.engine.source_lost.connect(lambda key: log('source_lost', key))
    app.engine.removed.connect(lambda key: log('removed', key))
    app.engine.manual_failed.connect(lambda code, *_: log('failed', code))
    x, y, w, h = fixture['rect']
    zone = Rect(x, y, w, min(h, 560))
    fixture_started = fixture.get('started')
    if spec['setup'] == 'pin_game':
        # Full-screen Watch follows the focused window. Pin "focus" to the game
        # so a person using this computer during the test cannot redirect it.
        import arabic_lens.engine as engine_module
        game = (fixture['hwnd'], Rect(*fixture['rect']), 'Game fixture')
        engine_module.active_window = lambda *args, **kwargs: game
    if spec['watch'] == 'fullscreen':
        app.settings.watch_areas = []
        app.settings.watch_fullscreen = True
        app.engine.set_watch(True)
    elif spec['watch'] == 'parts':
        app.settings.watch_areas = [fixture['parts'][k] for k in ('hud', 'quest', 'dialogue')]
        app.settings.watch_fullscreen = False
        app.engine.set_watch(True)
    elif spec['watch']:
        app.settings.watch_areas = [[zone.x, zone.y, zone.w, zone.h]]
        app.settings.watch_fullscreen = False
        app.engine.set_watch(True)
    asked = False
    last = 0
    max_overlays = 0
    while time.monotonic() - started < seconds:
        qt.processEvents()
        time.sleep(.02)
        now = time.monotonic() - started
        if spec['quick_at'] is not None and now > spec['quick_at'] and not asked:
            asked = True
            log('quick')
            quick = Rect(zone.x, zone.y, zone.w, 220) if spec['fixture'] == 'editor' else zone
            app.schedule_capture(quick, 'fixture', window_identity(fixture['hwnd']))
        if now - last >= .5:
            last = now
            snapshots.append([round(now, 1), sorted(key for key, win in app.overlays.windows.items()
                                                    if win.isVisible() and not win.closing)])
            sources = {key: app.overlays.sources.get(key, '') for key in snapshots[-1][1]}
            snapshots[-1].append(sources)
            snapshots[-1].append({key: list(app.overlays.source_rects[key].__dict__.values())
                                  for key in snapshots[-1][1] if key in app.overlays.source_rects})
            snapshots[-1].append(round(time.monotonic() - fixture_started, 2) if fixture_started else None)
            from arabic_lens.overlay import logical_to_physical
            boxes = {}
            for key in snapshots[-1][1]:
                win = app.overlays.windows[key]
                r = logical_to_physical(win.screen(), Rect(win.x(), win.y(), win.width(), win.height()))
                boxes[key] = [r.x, r.y, r.w, r.h]
            snapshots[-1].append(boxes)
            max_overlays = max(max_overlays, len(sources))
    save_composite(out / 'composite.png', fixture, app)
    final = [{'id': key, 'source': app.overlays.sources.get(key, ''), 'arabic': win.text}
             for key, win in app.overlays.windows.items() if win.isVisible() and not win.closing]
    (out / 'quit').touch()
    app.shutdown()
    try:
        child.wait(5)
    except subprocess.TimeoutExpired:
        child.kill()
    summary = {'scenario': name, 'final': final, 'snapshots': snapshots, 'events': events}
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')

    def snap_by_source(t):
        chosen = {}
        for when, ids, sources, *_ in snapshots:
            if when <= t:
                chosen = sources
        return sorted(chosen.values())

    def at_game_time(t):
        """(sources, rects) visible at fixture time t (seconds since game start)."""
        chosen = ({}, {})
        for snapshot in snapshots:
            if snapshot[4] is not None and snapshot[4] <= t:
                chosen = (snapshot[2], snapshot[3])
        return chosen
    results = []
    from arabic_lens.chat import prepare_chat, has_translatable_words
    visible = json.loads((out / 'visible.json').read_text()) if (out / 'visible.json').exists() else []
    removals = json.loads((out / 'removals.json').read_text()) if (out / 'removals.json').exists() else []
    context = dict(summary, snapshots=[s[:2] for s in snapshots], snap_by_source=snap_by_source,
                   visible=visible, max_overlays=max_overlays, at_game_time=at_game_time,
                   parts=fixture.get('parts', {}), raw_snapshots=snapshots, game_rect=fixture['rect'],
                   health_value=fixture.get('health_value'), removals=removals, harness_started=started,
                   translatable=lambda text: has_translatable_words(prepare_chat(text)[0]))
    for label, ok, detail in spec['check'](context):
        results.append((name, label, bool(ok), detail))
    return results


def main():
    out = Path(sys.argv[1])
    names = list(SCENARIOS) if sys.argv[2] == 'all' else sys.argv[2].split(',')
    seconds = float(sys.argv[3]) if len(sys.argv) > 3 else None
    report = []
    for name in names:
        # Each scenario needs a fresh process (fixture patches, Qt app state).
        if len(names) > 1:
            proc = subprocess.run([sys.executable, __file__, str(out), name] + ([str(seconds)] if seconds else []),
                                  capture_output=True, text=True, encoding='utf-8', errors='replace')
            report.extend(line for line in proc.stdout.splitlines() if line.startswith(('PASS', 'FAIL')))
            if proc.returncode:
                report.append(f'FAIL {name}: crashed {proc.stderr[-400:]}')
            continue
        for scenario_name, label, ok, detail in run(out / name, name, seconds):
            line = f"{'PASS' if ok else 'FAIL'} {scenario_name}: {label}" + ('' if ok else f' -> {detail}')
            report.append(line)
    print('\n'.join(report))
    # The combined report sits at the top; a single-scenario run keeps its own.
    target = out / 'report.txt' if len(names) > 1 else out / names[0] / 'report.txt'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('\n'.join(report), encoding='utf-8')


if __name__ == '__main__':
    main()
