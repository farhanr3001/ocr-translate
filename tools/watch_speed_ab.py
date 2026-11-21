"""Run a local split-screen Watch experiment, using isolated app instances.

Usage: .venv/Scripts/python.exe tools/watch_speed_ab.py artifacts/watch-speed/run-01 [--swap]
The candidate exists only in this harness. The capture rectangle is limited to
the supplied fixture. Frames combine real GDI source pixels with Qt overlay
grabs because the overlay windows are normally excluded from screen capture.
"""
import asyncio
import json
import os
import statistics
import subprocess
import sys
import threading
import time
from collections import Counter
from contextvars import ContextVar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from arabic_lens.windows import enable_dpi

enable_dpi()

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from arabic_lens.app import Application, HotkeyManager
from arabic_lens.models import Rect
from arabic_lens.offline import OfflineTranslationProvider
from arabic_lens.overlay import logical_to_physical
from arabic_lens.text import normalize
from arabic_lens.translation import TranslationError, TranslationService
from arabic_lens.windows import CaptureService, PreviewCaptureService, window_at_rect

STEPS = [
    ("Single line · first use", ["Find the silver needle before sunset."]),
    ("Burst · six lines", [
        "Hide behind the wall.",
        "Wait for the boat to arrive.",
        "The shop closes after sunset.",
        "Bring the cloth to the tailor.",
        "Collect the reward from the guard.",
        "Take the stairs to the library.",
    ]),
    ("Warm lines · names and numbers", [
        "Your balance is 85 gold.",
        "23:33 Aya: Meet me by the gate.",
        "The new coat costs 120 coins.",
    ]),
    ("Source text gone", []),
]
STABILITY_STEPS = [
    ("Stable subtitle", ["Find the silver needle before sunset."]),
    ("Six lines at once", STEPS[1][1]),
    ("Typewriter dialogue", ["The tailor is waiting beside the old bridge."]),
    ("Live chat · messages arrive and scroll", [
        "23:33 Aya: Meet me by the gate.",
        "23:34 Sam: Bring the blue coat.",
        "23:35 Lena: I have 85 gold.",
        "23:36 Omar: The shop closes soon.",
        "23:37 Noor: The boat is ready.",
    ]),
    ("Source text gone", []),
]
FIRST_STEP = 3.0
STEP_SECONDS = 4.0
FPS = 20
NOW = time.perf_counter
CAPTURE_LOCK = threading.Lock()


class SerialCapture(CaptureService):
    def capture(self, rect):
        with CAPTURE_LOCK:
            return super().capture(rect)


class SerialPreview(PreviewCaptureService):
    def capture(self, rect):
        with CAPTURE_LOCK:
            return super().capture(rect)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def physical(widget):
    point = widget.mapToGlobal(widget.rect().topLeft())
    return logical_to_physical(widget.screen(), Rect(point.x(), point.y(), widget.width(), widget.height()))


def coordinates(rect):
    return [rect.x, rect.y, rect.w, rect.h]


def fixture(directory, swap, stability):
    qt = QApplication([])
    screen = qt.primaryScreen().availableGeometry()
    window = QWidget()
    window.setWindowTitle("Arabic Lens · Live Watch speed test")
    window.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
    window.setStyleSheet("background: #192a29; color: #f1eee2; font-family: 'Segoe UI'")
    window.resize(min(1200, screen.width() - 40), min(575, screen.height() - 60))
    window.move(screen.center() - window.rect().center())
    layout = QVBoxLayout(window)
    title = QLabel("Arabic Lens   /   Live Watch comparison")
    title.setFont(QFont("Segoe UI", 19, QFont.DemiBold))
    layout.addWidget(title)
    stage = QLabel("Waiting for both Watch sessions")
    stage.setStyleSheet("color: #a0c1b6; padding: 3px;")
    layout.addWidget(stage)
    columns = QHBoxLayout()
    layout.addLayout(columns, 1)
    panes, rows, timings = [], [], []
    experiment = "EARLY TRANSLATION + SOURCE CHECK" if stability else "PRELOAD + READY QUEUE"
    headings = ("CURRENT · 0.1.6", "EXPERIMENT · " + experiment)
    for heading in reversed(headings) if swap else headings:
        column = QVBoxLayout()
        label = QLabel(heading)
        label.setFont(QFont("Segoe UI", 11, QFont.DemiBold))
        header = QHBoxLayout()
        header.addWidget(label, 1)
        time_header = QLabel("VISIBLE IN")
        time_header.setFixedWidth(82)
        time_header.setAlignment(Qt.AlignCenter)
        time_header.setStyleSheet("color: #a0c1b6")
        header.addWidget(time_header)
        column.addLayout(header)
        pane = QWidget()
        pane.setStyleSheet("background: #142220;")
        content = QVBoxLayout(pane)
        content.setSpacing(7)
        row_labels = []
        for _ in range(6):
            line = QLabel()
            line.setStyleSheet("color: #f6f3ea; background: #263f38; padding: 6px 10px;")
            line.setFont(QFont("Segoe UI", 14, QFont.DemiBold))
            content.addWidget(line, 1)
            row_labels.append(line)
        rows.append(row_labels)
        panes.append(pane)
        timing_pane = QWidget()
        timing_pane.setFixedWidth(82)
        timing_layout = QVBoxLayout(timing_pane)
        timing_layout.setContentsMargins(3, 9, 3, 9)
        timing_layout.setSpacing(7)
        timing_rows = []
        for _ in range(6):
            timing = QLabel()
            timing.setAlignment(Qt.AlignCenter)
            timing.setStyleSheet("background: #203732; color: #bfe5d1; font-weight: 600")
            timing_layout.addWidget(timing, 1)
            timing_rows.append(timing)
        timings.append(timing_rows)
        content_grid = QHBoxLayout()
        content_grid.addWidget(pane, 1)
        content_grid.addWidget(timing_pane)
        column.addLayout(content_grid, 1)
        columns.addLayout(column, 1)
    footer = QLabel("  ")
    footer.setMinimumHeight(34)
    layout.addWidget(footer)
    window.show()
    window.raise_()
    window.activateWindow()
    qt.processEvents()
    write_json(directory / "ready.json", {
        "window": coordinates(physical(window)), "panes": [coordinates(physical(p)) for p in panes],
        "footer": coordinates(physical(footer)), "hwnd": int(window.winId()),
        "rows": [[coordinates(physical(row)) for row in labels] for labels in rows],
    })
    steps = STABILITY_STEPS if stability else STEPS
    state = {"start": None, "step": -1, "lines": None}
    changes = []
    first_seen = {}

    def refresh_timings(lines):
        try:
            raw = (directory / "timings.json").read_text(encoding="utf-8")
            scores = json.loads(raw)
        except (OSError, ValueError):
            return
        modes = ("experiment", "current") if swap else ("current", "experiment")
        for mode, labels in zip(modes, timings):
            for i, label in enumerate(labels):
                key = normalize(lines[i]) if i < len(lines) else ""
                value = scores.get(mode, {}).get(key)
                label.setText(f"{value} ms" if value is not None else ("·" if key else ""))

    def tick():
        if (directory / "quit").exists():
            qt.quit()
        if state["start"] is None:
            if not (directory / "go").exists():
                return
            state["start"] = NOW()
        elapsed = NOW() - state["start"]
        current = min(len(steps) - 1, int((elapsed - FIRST_STEP) // STEP_SECONDS))
        if current < 0:
            return
        first = current != state["step"]
        state["step"] = current
        name, lines = steps[current]
        phase_elapsed = elapsed - FIRST_STEP - current * STEP_SECONDS
        if stability and current == 2:
            length = 1 + int(phase_elapsed / .035)
            lines = [lines[0][:length]]
        if stability and current == 3:
            sent = min(len(lines), 1 + int(phase_elapsed / .50))
            lines = lines[max(0, sent - 3):sent]
        refresh_timings(lines)
        if not first and lines == state["lines"]:
            return
        if first:
            first_seen.clear()
        state["lines"] = lines
        stage.setText(name)
        for labels in rows:
            for index, label in enumerate(labels):
                label.setText(lines[index] if index < len(lines) else "")
        window.repaint()
        when = NOW()
        for line in lines:
            first_seen.setdefault(normalize(line), when)
        change = {"step": current, "time": when, "lines": lines, "first_seen": first_seen.copy()}
        changes.append(change)
        write_json(directory / "source-live.json", change)
        if current == len(steps) - 1:
            write_json(directory / "source-changes.json", changes)
        if first:
            path = directory / f"step-{current}.txt"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(str(when), encoding="ascii")
            tmp.replace(path)

    timer = QTimer(window)
    timer.timeout.connect(tick)
    timer.start(20)
    qt.exec()
    write_json(directory / "source-changes.json", changes)


class ReadyQueueProvider(OfflineTranslationProvider):
    """Use the existing batch runner with requests ready on the next loop turn."""
    async def warm_up(self):
        await asyncio.get_running_loop().run_in_executor(self.executor, self._initialize)

    async def _dispatch(self):
        while self.pending:
            await asyncio.sleep(0)
            batch, self.pending = self.pending[:8], self.pending[8:]
            batch = [entry for entry in batch if not entry[1].cancelled()]
            if not batch:
                continue
            try:
                answers = await asyncio.get_running_loop().run_in_executor(self.executor, self._batch, batch)
            except Exception:
                answers = [TranslationError("local_unavailable")] * len(batch)
            for (_, future, _, _), answer in zip(batch, answers):
                if future.done():
                    continue
                if isinstance(answer, Exception):
                    future.set_exception(answer)
                elif answer is None:
                    future.cancel()
                else:
                    future.set_result(answer)


class TimedService(TranslationService):
    def __init__(self, provider, store, events):
        super().__init__(provider, store)
        self.events = events

    async def translate(self, text, on_started=None):
        start = NOW()
        arabic, cached = await super().translate(text, on_started=on_started)
        self.events.append({
            "source": text, "arabic": arabic, "cached": cached,
            "submitted": start, "finished": NOW(),
        })
        return arabic, cached


class EarlyService(TimedService):
    """Keep speculative work local to this experiment and keyed by exact text."""
    def __init__(self, provider, store, events):
        super().__init__(provider, store, events)
        self.pending = {}
        self.check_source = ContextVar("check_source", default=None)

    def prepare(self, source):
        if source not in self.pending and len(self.pending) < 8:
            self.pending[source] = asyncio.create_task(super().translate(source))

    def discard(self, source):
        future = self.pending.pop(source, None)
        if future is not None:
            if future.done() and not future.cancelled():
                future.exception()
            else:
                future.cancel()

    async def translate(self, text, on_started=None):
        future = self.pending.pop(text, None)
        if future is None:
            result = await super().translate(text, on_started)
        else:
            if on_started:
                on_started()
            result = await future
        validate = self.check_source.get()
        if validate is not None and not validate():
            raise asyncio.CancelledError
        return result


def install_early_experiment(engine):
    """Speculate after OCR and reuse the production renderer and job checks."""
    import cv2
    import numpy as np
    from arabic_lens.scene import _gray, crop, text_related
    from arabic_lens.windows import source_window_current, window_identity

    read_scene = engine._read_scene
    translate_segment = engine._translate_segment
    ocr_events = []
    last_capture = (0, None, None)
    missing_since = {}

    def fresh_frame(bounds):
        nonlocal last_capture
        now, (captured_at, previous_bounds, frame) = NOW(), last_capture
        if bounds != previous_bounds or now - captured_at > .020:
            frame, _ = engine._masked(engine.capture.capture(bounds).copy(), bounds)
            last_capture = (NOW(), bounds, frame)
        return frame

    def find_row(gray, top, pixels):
        height = pixels.shape[0]
        if np.array_equal(gray[top:top + height], pixels):
            return top
        distances = cv2.matchTemplate(gray, pixels, cv2.TM_SQDIFF_NORMED)
        _, _, (_, y), _ = cv2.minMaxLoc(distances)
        return y if np.array_equal(gray[y:y + height], pixels) else None

    async def publish_checked(state, segment, key, block, bounds, title, generation, source_window, image):
        # Bind the words to the immutable pixels from the OCR pass. The
        # shared scene frame may already contain the next chat viewport.
        reference = state.get("ocr_rows", {}).get(segment.id)
        if reference is None or reference[0] != block.text:
            if segment.pending_key == key:
                segment.pending_key = ""
            return
        _, source_rect, top, before = reference
        scene = state["scene"]

        def validate():
            try:
                frame = fresh_frame(bounds)
                y = find_row(_gray(frame), top, before)
                current = (generation == engine.generation and scene.segments.get(segment.id) is segment
                           and segment.key == key and y is not None)
            except OSError:
                current = False
            if not current and segment.pending_key == key:
                segment.pending_key = ""
            elif current:
                # OCR can update a segment's internal patch during scrolling.
                # Retain independent evidence of exactly what was published.
                located = Rect(source_rect.x, source_rect.y + y - top, source_rect.w, source_rect.h)
                segment.rect = located
                state.setdefault("published_rows", {})[segment.id] = (located, y, before)
                missing_since.pop(segment.id, None)
            return current

        token = engine.translator.check_source.set(validate)
        try:
            await translate_segment(state, segment, key, block, bounds, title, generation, source_window, image)
        finally:
            engine.translator.check_source.reset(token)

    def follow_checked(state, image, bounds):
        published = state.get("published_rows", {})
        gray = _gray(image)
        for identifier, (source_rect, top, pixels) in list(published.items()):
            segment = state["scene"].segments.get(identifier)
            if segment is None or not segment.shown_key:
                published.pop(identifier, None)
                missing_since.pop(identifier, None)
                continue
            if any(segment.rect.overlap(covered) > .2 for covered in state.get("protected", ())):
                continue
            y = find_row(gray, top, pixels)
            if y is None:
                now = NOW()
                if now - missing_since.setdefault(identifier, now) < .075:
                    continue
                # Remove a result that lost its source on this changed frame.
                # Keep the scene entry for the ordinary OCR reconciliation.
                segment.shown_key = segment.shown_source = ""
                published.pop(identifier, None)
                missing_since.pop(identifier, None)
                engine.anchors.items.pop(identifier, None)
                engine.removed.emit(identifier)
                continue
            missing_since.pop(identifier, None)
            moved = Rect(source_rect.x, source_rect.y + y - top, source_rect.w, source_rect.h)
            if moved == segment.rect and y == top:
                continue
            published[identifier] = (moved, y, pixels)
            segment.rect = moved
            physical_rect = Rect(bounds.x + moved.x, bounds.y + moved.y, moved.w, moved.h)
            anchor = engine.anchors.items.get(identifier)
            if anchor:
                anchor.rect = physical_rect
            engine.source_moved.emit(identifier, physical_rect)

    async def read(state, bounds, core, np_module, now, hwnd=None):
        scene = state["scene"]
        previous = {identifier: segment.key for identifier, segment in scene.segments.items()}
        await read_scene(state, bounds, core, np_module, now, hwnd)
        still_visible = {segment.text[:6000] for zone in engine.zone_states.values()
                         for segment in zone["scene"].segments.values()}
        for source in list(engine.translator.pending):
            if source not in still_visible:
                engine.translator.discard(source)
        generation = engine.generation
        source_window = window_identity(hwnd) if hwnd else None
        read_time = NOW()
        candidates = []
        references = state.setdefault("ocr_rows", {})
        for key in list(references):
            if key not in scene.segments:
                references.pop(key)
        for key, segment in scene.segments.items():
            if segment.confirmed == now:
                rect = segment.rect
                strip = Rect(0, max(0, rect.y - 2), bounds.w, rect.h + 4)
                pixels = _gray(crop(state["image"], strip))
                if pixels is not None:
                    references[key] = (segment.text, rect, strip.y, pixels.copy())
            if key in previous and text_related(previous[key], segment.key):
                continue
            source = segment.text[:6000]
            ocr_events.append({"source": source, "time": read_time})
            if (len(source.split()) >= 4 and source.endswith((".", "?", "!"))
                    and "\n" not in source and segment.pixels is not None):
                strip = Rect(0, max(0, segment.rect.y - 3), bounds.w, segment.rect.h + 6)
                pixels = crop(state["image"], strip)
                if pixels is not None:
                    candidates.append((segment, source, strip, pixels.copy()))
                    engine.translator.prepare(source)
        if not candidates:
            return

        async def confirm():
            try:
                await asyncio.sleep(.10)
                if generation != engine.generation or not engine.watch or not source_window_current(source_window):
                    return
                pending = {future for _, source, _, _ in candidates
                           if (future := engine.translator.pending.get(source)) is not None and not future.done()}
                if pending:
                    await asyncio.wait(pending, timeout=.075)
                if generation != engine.generation or not engine.watch:
                    return
                # Verify after inference, so a slow batch cannot publish pixels
                # that matched only when it started. Unfinished work stays on
                # the normal Watch path.
                ready = [(segment, source, strip, pixels)
                         for segment, source, strip, pixels in candidates
                         if (future := engine.translator.pending.get(source)) is not None
                         and future.done() and not future.cancelled() and future.exception() is None]
                if not ready:
                    return
                captured = fresh_frame(bounds)
                verified = [
                    segment for segment, source, strip, pixels in ready
                    if (scene.segments.get(segment.id) is segment and segment.text[:6000] == source
                        and not segment.pending_key and not segment.shown_key
                        and source in engine.translator.pending
                        and np.array_equal(crop(captured, strip), pixels))
                ]
                if not verified:
                    return

                def due(current, base, limit, image):
                    # The fast wake-up must never schedule unrelated segments.
                    # Normal jobs rely on the regular scan's freshest image.
                    return verified[:limit]

                scene.due = due
                try:
                    engine._schedule_scene(state, bounds, "Speed fixture", hwnd, time.monotonic())
                finally:
                    del scene.due
            except OSError:
                # The regular Watch scheduler recovers on the next normal pass.
                return
            finally:
                for segment, source, _, _ in candidates:
                    # A missed early display window should reuse the same work
                    # at normal settle time. Cancelling a running CPU batch
                    # here just makes the regular path wait for it twice.
                    if scene.segments.get(segment.id) is not segment or segment.text[:6000] != source:
                        engine.translator.discard(source)

        asyncio.create_task(confirm())

    engine._read_scene = read
    engine._translate_segment = publish_checked
    engine._follow_scene = follow_checked

    async def follow_between_reads():
        # Translation tracking stays responsive while the main task waits for
        # OCR. An unchanged small preview does not trigger another full capture.
        previews = {}
        while True:
            await asyncio.sleep(.085)
            live = set()
            for state in list(engine.zone_states.values()):
                bounds = state["bounds"]
                if not any(segment.shown_key for segment in state["scene"].segments.values()):
                    continue
                live.add(bounds)
                try:
                    preview = engine.preview_capture.capture(bounds).copy()
                    previous = previews.get(bounds)
                    previews[bounds] = preview
                    if (previous is None or missing_since
                            or np.any(np.abs(preview.astype(np.int16) - previous) > 18)):
                        follow_checked(state, fresh_frame(bounds), bounds)
                except OSError:
                    continue
            previews = {key: sample for key, sample in previews.items() if key in live}

    asyncio.create_task(follow_between_reads())
    return ocr_events


def show_events(app, events):
    original = app.show_translation
    app.engine.translated.disconnect(original)

    def show(result):
        original(result)
        window = app.overlays.windows.get(result.id)
        if window is not None and window.isVisible() and not window.closing:
            events.append({
                "source": result.source, "arabic": window.text, "cached": result.cached,
                "shown": NOW(),
            })

    app.engine.translated.connect(show)


def composite(capture, bounds, footer, apps, caption):
    image = capture.capture(bounds).copy()
    canvas = QPixmap.fromImage(QImage(image.data, bounds.w, bounds.h, image.strides[0],
                                      QImage.Format_RGB32).copy())
    painter = QPainter(canvas)
    for app in apps:
        for win in app.overlays.windows.values():
            if win.isVisible() and not win.closing and win.capture_excluded:
                rect = physical(win)
                painter.setOpacity(win.windowOpacity())
                painter.drawPixmap(rect.x - bounds.x, rect.y - bounds.y, rect.w, rect.h, win.grab())
    painter.setOpacity(1)
    painter.setPen(QColor("#d3e9df"))
    painter.setFont(QFont("Segoe UI", 12))
    target = QRect(footer.x - bounds.x, footer.y - bounds.y, footer.w, footer.h)
    painter.drawText(target, Qt.AlignVCenter | Qt.AlignLeft, caption)
    painter.end()
    return canvas


def misplaced(app, rows, source_state):
    lines = {normalize(line): box for line, box in zip(source_state["lines"], rows)}
    issues = []
    for key, window in app.overlays.windows.items():
        if window.closing or not window.isVisible():
            continue
        text = app.overlays.sources.get(key, "")
        row = lines.get(normalize(text))
        if row is None:
            issues.append({"source": text, "reason": "no matching visible source"})
            continue
        rect = physical(window)
        source = app.overlays.source_rects.get(key)
        if not source or row.intersect(source).h < source.h * .7 or abs(rect.y - row.y - row.h / 2) > row.h * .7:
            issues.append({"source": text, "reason": "outside the matching source row",
                           "overlay": coordinates(rect), "row": coordinates(row),
                           "anchor": coordinates(source) if source else None})
    return issues


def compare(times, translated, displayed, cleared, steps, changes):
    results = []
    for index, start in enumerate(times[:-1]):
        finish = times[index + 1]
        expected = {normalize(line): line for line in steps[index][1]}
        first_seen = {}
        for change in changes:
            if change["step"] == index:
                for line in change["lines"]:
                    first_seen.setdefault(normalize(line), change["time"])
        row = {"step": steps[index][0], "expected_blocks": len(expected)}
        outputs = []
        for mode in ("current", "experiment"):
            shows = [e for e in displayed[mode] if start <= e["shown"] < finish]
            work = [e for e in translated[mode] if start <= e["submitted"] < finish]
            complete = [e for e in shows if normalize(e["source"]) in expected]
            outputs.append(Counter((e["source"], e["arabic"]) for e in complete))
            latencies = [1000 * (e["finished"] - e["submitted"]) for e in work]
            response = {expected[key]: round((e["shown"] - first_seen[key]) * 1000)
                        for e in reversed(complete)
                        if (key := normalize(e["source"])) in first_seen}
            row[mode] = {
                "shown": len(shows), "first_visible_ms": round(1000 * (shows[0]["shown"] - start)) if shows else None,
                "last_visible_ms": round(1000 * (shows[-1]["shown"] - start)) if shows else None,
                "translation_ms": [round(v, 1) for v in latencies],
                "median_translation_ms": round(statistics.median(latencies), 1) if latencies else None,
                "completed_line_visible_ms": response,
                "other_overlays": [e["source"] for e in shows if normalize(e["source"]) not in expected],
                "repeat_publications": len(complete) - len(outputs[-1]),
            }
        row["exact_match"] = set(outputs[0]) == set(outputs[1])
        row["coverage_pass"] = all(len({normalize(src) for src, _ in output}) == len(expected) for output in outputs)
        row["extra_overlays_pass"] = len(row["experiment"]["other_overlays"]) <= len(row["current"]["other_overlays"])
        row["repeat_pass"] = row["experiment"]["repeat_publications"] <= row["current"]["repeat_publications"]
        results.append(row)
    # A stale baseline overlay is evidence about the baseline, not a failure
    # of a candidate which cleared and presented every expected translation.
    return {"steps": results, "cleared": cleared, "pass": bool(results) and cleared["experiment"] and
            all(row["exact_match"] and row["coverage_pass"] and row["extra_overlays_pass"]
                and row["repeat_pass"] for row in results)}


def run(directory, swap, stability, production=False):
    directory.mkdir(parents=True, exist_ok=False)
    frames = directory / "frames"
    frames.mkdir()
    qt = QApplication([])
    qt.setProperty("smokeTest", True)
    qt.setQuitOnLastWindowClosed(False)
    HotkeyManager.register = lambda *args, **kwargs: None
    import arabic_lens.engine as engine_module
    # The desktop DC can reject concurrent blits from the recorder and two
    # independent Watch workers. Serialize only within this test process.
    engine_module.CaptureService = SerialCapture
    engine_module.PreviewCaptureService = SerialPreview
    command = [sys.executable, __file__, str(directory), "--fixture"]
    if swap:
        command.append("--swap")
    if stability:
        command.append("--stability")
    child = subprocess.Popen(command, env=dict(os.environ, PYTHONPATH=str(ROOT)))
    apps = []
    capture = None
    try:
        deadline = NOW() + 15
        while not (directory / "ready.json").exists():
            if child.poll() is not None or NOW() >= deadline:
                raise RuntimeError("Split-screen fixture did not start")
            time.sleep(.05)
        fixture_info = json.loads((directory / "ready.json").read_text())
        bounds, footer = (Rect(*fixture_info[k]) for k in ("window", "footer"))
        steps = STABILITY_STEPS if stability else STEPS
        translated, displayed = {}, {}
        recognized = []
        placement = {"current": [], "experiment": []}
        row_rects = [[Rect(*row) for row in rows] for rows in fixture_info["rows"]]
        for index, mode in enumerate(("current", "experiment")):
            app = Application(qt, directory / mode)
            apps.append(app)
            app.window.hide()
            app.settings.cache_enabled = False
            app.settings.history_enabled = False
            app.settings.watch_areas = [fixture_info["panes"][1 - index if swap else index]]
            if production:
                app.engine.fast_watch = mode == "experiment"
            else:
                app.engine.fast_watch = False
            if mode == "experiment" and stability and not production:
                # Shorter preview ticks are part of this prototype only. OCR
                # settings and the existing typing quiet period are unchanged.
                app.settings.scan_ms = 100
            translated[mode], displayed[mode] = [], []
            show_events(app, displayed[mode])

            async def configure(engine, experiment, events):
                if experiment and not stability:
                    await engine.provider.local.close()
                    engine.provider.local = ReadyQueueProvider()
                service = EarlyService if experiment and stability and not production else TimedService
                engine.translator = service(engine.provider, engine.store, events)
                if stability:
                    # Equal warm model state on both sides isolates the scheduling change.
                    await asyncio.get_running_loop().run_in_executor(
                        engine.provider.local.executor, engine.provider.local._initialize)
                    if experiment and not production:
                        recognized.extend([install_early_experiment(engine)])
                elif experiment:
                    await engine.provider.local.warm_up()

            app.engine._submit(configure(app.engine, mode == "experiment", translated[mode])).result(15)
        # Force both Watch sessions to use the owned fixture even if another
        # desktop window grabs foreground focus during capture.
        engine_module.active_window = lambda *args, **kw: (fixture_info["hwnd"], bounds, "Speed fixture")
        capture = SerialCapture()
        for app in apps:
            app.engine.set_watch(True)
        (directory / "go").touch()
        start = NOW()
        next_frame = start
        frame = 0
        times = []
        saved = set()
        previous_scores = None
        while (elapsed := NOW() - start) < FIRST_STEP + STEP_SECONDS * len(steps):
            qt.processEvents()
            now = NOW()
            if now < next_frame:
                time.sleep(.004)
                continue
            # A separate topmost menu or window can cover a pane on the real
            # desktop. Abort an obstructed run before recording those pixels.
            for pane in (Rect(*values) for values in fixture_info["panes"]):
                for dx, dy in ((.15, .15), (.85, .15), (.5, .5), (.15, .85), (.85, .85)):
                    target = Rect(pane.x + round(pane.w * dx), pane.y + round(pane.h * dy), 1, 1)
                    owner = window_at_rect(target)
                    if owner and owner[0] != fixture_info["hwnd"]:
                        raise RuntimeError("Comparison fixture was covered by another desktop window")
            if len(times) < len(steps):
                step_path = directory / f"step-{len(times)}.txt"
                if step_path.exists():
                    times.append(float(step_path.read_text()))
            if times:
                shown = [len([e for e in displayed[mode] if e["shown"] >= times[-1]]) for mode in displayed]
                sides = [f"Current: {shown[0]} shown", f"Experiment: {shown[1]} shown"]
                caption = "        ".join(reversed(sides) if swap else sides)
                caption += f"        |        {now - times[-1]:.2f} s since change"
            else:
                shown = [0, 0]
                caption = "Both sides are watching the same text."
            canvas = composite(capture, bounds, footer, apps, caption)
            if (live := directory / "source-live.json").exists():
                try:
                    source_state = json.loads(live.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    source_state = None
                if source_state:
                    first_seen = source_state["first_seen"]
                    scores = {
                        mode: {key: max(0, round((result["shown"] - first_seen[key]) * 1000))
                               for result in reversed(results)
                               if (key := normalize(result["source"])) in first_seen
                               and result["shown"] >= first_seen[key]}
                        for mode, results in displayed.items()
                    }
                    if scores != previous_scores:
                        write_json(directory / "timings.json", scores)
                        previous_scores = scores
                if stability and source_state and source_state["step"] in (3, 4) and now - source_state["time"] >= .30:
                    for index, (mode, app) in enumerate(zip(displayed, apps)):
                        issues = misplaced(app, row_rects[1 - index if swap else index], source_state)
                        if issues:
                            placement[mode].append({"time": now, "phase": source_state["step"], "issues": issues})
            canvas.save(str(frames / f"{frame:05}.jpg"), quality=86)
            frame += 1
            next_frame += 1 / FPS
            if len(times) > 0 and len(times) not in saved and times[-1] + 1.9 < now and all(shown):
                canvas.save(str(directory / f"step-{len(times)}.png"))
                saved.add(len(times))
        assert len(times) == len(steps), times
        cleared = {mode: not any(not w.closing and w.isVisible() for w in app.overlays.windows.values())
                   for mode, app in zip(displayed, apps)}
        changes = json.loads((directory / "source-changes.json").read_text(encoding="utf-8"))
        report = compare(times, translated, displayed, cleared, steps, changes)
        report["real_seconds"] = round(elapsed, 3)
        report["frames"] = frame
        report["swapped"] = swap
        report["placement_frames_with_issues"] = {mode: len(events) for mode, events in placement.items()}
        report["pass"] = report["pass"] and not placement["experiment"]
        report["events"] = {"translation": translated, "overlay": displayed, "fixture_changes": changes,
                            "candidate_ocr": recognized[0] if recognized else [],
                            "placement": placement}
        write_json(directory / "report.json", report)
        print(json.dumps({k: v for k, v in report.items() if k != "events"}, indent=2), flush=True)
        return 0 if report["pass"] else 1
    finally:
        if capture:
            capture.close()
        for app in reversed(apps):
            qt.aboutToQuit.disconnect(app.shutdown)
            app.shutdown()
        (directory / "quit").touch()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.terminate()
            child.wait(timeout=5)


if __name__ == "__main__":
    output = Path(sys.argv[1]).resolve()
    swapped = "--swap" in sys.argv[2:]
    stability = "--stability" in sys.argv[2:]
    if "--fixture" in sys.argv[2:]:
        fixture(output, swapped, stability)
    else:
        raise SystemExit(run(output, swapped, stability, "--production" in sys.argv))
