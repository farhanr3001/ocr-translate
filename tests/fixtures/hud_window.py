"""Separate-process game screen: HUD, quest panel, notification, dialogue.

Usage: hud_window.py DIR SCRIPT_JSON
SCRIPT_JSON: list of timed steps {"at_ms": 1500, ...} applied in order:
  {"objective": ["line", ...]}            quest panel objectives (replaced)
  {"notice": "text"} / {"notice": ""}      centre notification on/off
  {"speaker": "Elder", "say": "text", "cps": 30}   dialogue typewriter
  {"say": ""}                              dialogue box closes
The background animates continuously (a moving sun and drifting grass), like
a game scene behind the HUD. Writes DIR/ready.json with the window and the
physical rectangles of each HUD part, and DIR/state.json whenever it changes.
"""
import json
import math
import sys
import time
from pathlib import Path
from arabic_lens.windows import enable_dpi
enable_dpi()
from PySide6.QtCore import QRect, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QTextOption
from PySide6.QtWidgets import QApplication, QWidget
from arabic_lens.models import Rect
from arabic_lens.overlay import logical_to_physical

directory = Path(sys.argv[1])
steps = json.loads(Path(sys.argv[2]).read_text())
size = steps.pop(0)['size'] if steps and 'size' in steps[0] else [1180, 680]
qt = QApplication([])
area = qt.primaryScreen().availableGeometry()
W, H = min(size[0], area.width() - 80), min(size[1], area.height() - 80)
PARTS = {
    'hud': QRect(16, 14, 250, 92),
    'quest': QRect(W - 380, 14, 364, 170),
    'notice': QRect(W // 2 - 230, 210, 460, 54),
    'dialogue': QRect(60, H - 170, W - 120, 150),
}
state = {'objective': [], 'notice': '', 'speaker': '', 'say': '', 'shown': 0, 'cps': 30, 'style': 'box'}
started = time.monotonic()


class Game(QWidget):
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = time.monotonic() - started
        p.fillRect(self.rect(), QColor('#5b8cc4'))
        p.fillRect(0, H // 2, W, H // 2, QColor('#3f7a3a'))
        p.setBrush(QColor('#f6d365')); p.setPen(Qt.NoPen)
        p.drawEllipse(int(W / 2 + math.sin(t / 3) * 300), 60 + int(math.cos(t / 2) * 20), 70, 70)
        p.setBrush(QColor('#2f6a2b'))
        for i in range(14):
            x = (i * 97 + int(t * 40)) % (W + 60) - 30
            p.drawEllipse(x, H // 2 + 30 + (i % 3) * 40, 40, 18)

        def panel(rect, fill='#1c1712', border='#c9a45c', alpha=225):
            colour = QColor(fill); colour.setAlpha(alpha)
            p.setBrush(colour); p.setPen(QPen(QColor(border), 2))
            p.drawRoundedRect(rect, 8, 8)

        def text(rect, value, size=13, bold=False, colour='#f4ead2', wrap=False):
            font = QFont('Segoe UI', size); font.setBold(bold); p.setFont(font)
            p.setPen(QColor(colour))
            option = QTextOption(); option.setWrapMode(QTextOption.WordWrap if wrap else QTextOption.NoWrap)
            from PySide6.QtCore import QRectF
            p.drawText(QRectF(rect), value, option)

        hud = PARTS['hud']; panel(hud)
        text(hud.adjusted(14, 10, -10, 0), 'Health  85 / 100', 13, True, '#ff8a80')
        text(hud.adjusted(14, 36, -10, 0), 'Gold  1,250', 13, True, '#ffd54f')
        text(hud.adjusted(14, 62, -10, 0), 'Level 7 Ranger', 12)
        quest = PARTS['quest']; panel(quest)
        text(quest.adjusted(16, 10, -12, 0), 'Quest: The Lost Ring', 14, True, '#ffd54f')
        y = 42
        for line in state['objective']:
            text(QRect(quest.x() + 16, quest.y() + y, quest.width() - 28, 60), line, 12, wrap=True)
            y += 46
        if state['notice']:
            notice = PARTS['notice']; panel(notice, '#0f1c2b', '#7fb3e6', 235)
            text(notice.adjusted(18, 13, -12, 0), state['notice'], 14, True, '#e3f2ff')
        if state['say'] and state['style'] == 'subtitle':
            # Borderless subtitle: one line of white text with a soft shadow,
            # straight over the moving scene.
            font = QFont('Segoe UI', 17); font.setBold(True); p.setFont(font)
            line = (state['speaker'] + ': ' if state['speaker'] else '') + state['say'][:state['shown']]
            box = PARTS['dialogue']
            for dx, dy, colour in ((2, 2, '#000000'), (0, 0, '#ffffff')):
                p.setPen(QColor(colour))
                p.drawText(box.adjusted(dx, 60 + dy, dx, dy), Qt.AlignHCenter | Qt.AlignTop, line)
        elif state['say']:
            box = PARTS['dialogue']; panel(box, '#120f0b', '#c9a45c', 240)
            text(box.adjusted(22, 12, -20, 0), state['speaker'], 14, True, '#ffd54f')
            text(box.adjusted(22, 42, -20, -10), state['say'][:state['shown']], 14, wrap=True)


game = Game()
game.setWindowTitle('Arabic Lens game fixture')
game.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
game.setGeometry(area.x() + 40, area.y() + 40, W, H)
game.show()
game.activateWindow()
qt.processEvents()
origin = game.mapToGlobal(game.rect().topLeft())
screen = game.screen()


def physical(rect):
    r = logical_to_physical(screen, Rect(origin.x() + rect.x(), origin.y() + rect.y(), rect.width(), rect.height()))
    return [r.x, r.y, r.w, r.h]


from PySide6.QtGui import QFontMetrics
_font = QFont('Segoe UI', 13); _font.setBold(True)
_value_x = PARTS['hud'].x() + 14 + QFontMetrics(_font).horizontalAdvance('Health  ')
value = physical(QRect(_value_x, PARTS['hud'].y() + 10, 60, 20))
(directory / 'ready.json').write_text(json.dumps(dict(hwnd=int(game.winId()), started=started, health_value=value,
    rect=physical(game.rect()), parts={k: physical(v) for k, v in PARTS.items()})))


def write_state():
    (directory / 'state.json').write_text(json.dumps(dict(state, t=round(time.monotonic() - started, 2))))


def tick():
    if (directory / 'quit').exists():
        qt.quit(); return
    now = (time.monotonic() - started) * 1000
    changed = False
    while steps and steps[0]['at_ms'] <= now:
        step = steps.pop(0)
        for key in ('objective', 'notice', 'speaker', 'cps', 'style'):
            if key in step:
                state[key] = step[key]; changed = True
        if 'say' in step:
            state['say'], state['shown'], state['say_at'] = step['say'], 0, now
            changed = True
    if state['say'] and state['shown'] < len(state['say']):
        state['shown'] = min(len(state['say']), int((now - state['say_at']) / 1000 * state['cps']))
    if changed:
        write_state()
    if not steps and not (directory / 'done.json').exists() and state['shown'] >= len(state['say']):
        (directory / 'done.json').write_text('{}')
    game.update()


timer = QTimer()
timer.timeout.connect(tick)
timer.start(33)
qt.exec()
