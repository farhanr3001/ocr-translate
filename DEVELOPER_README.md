# Arabic Lens — developer and AI handoff

Last reviewed: **9 October 2026** (installer and public release verified; the desktop OCR baseline below remains dated 28 September). This document preserves the product decisions, implementation map, verification workflow and remaining limitations for the next developer or AI assistant. Read it alongside [README.md](README.md). Code and current test results take precedence if this snapshot becomes stale; update this document when behavior changes.

## Start here

Arabic Lens translates visible English into **Modern Standard Arabic** using ordinary Windows screen capture, Windows OCR, and a bundled English–Arabic translation model. It is a general desktop accessibility utility. Dressmaker, browser pages and the supplied X scrolling recording are test cases, not the scope of the product.

The intended experience is: English appears, readable Arabic appears in its place, and the user continues what they were doing. Setup, technical controls, notifications and resource usage must stay out of the way.

Treat the directory containing this file as the repository root. The developer's working portable copy is **`dist\ArabicLens\ArabicLens.exe` inside that checkout**. Updating source alone does not update that application. For implementation work, build, verify and replace the portable folder before calling the update delivered. For another laptop, build and test the installer using [RELEASE.md](RELEASE.md). Do not tell this user to extract another archive after replacing their local portable folder yourself.

**Standing delivery requirement (9 October): every completed application update must also increment its version, push the source to GitHub, publish the tested installer and checksum as a newer stable GitHub Release, and verify that the production updater discovers it from the preceding installed version. Updating local `dist` alone is not completion. The user has explicitly authorized this release workflow for future app changes. Preserve existing published assets; use a new version/tag.**

For a new session:

1. Read this document, the user README, and the latest user request. Later user corrections override older feature requests.
2. Inspect existing source, tests and current task checklists before editing. Preserve working behavior and user settings.
3. Reproduce the issue at the failing layer: detection, grouping, filtering, scheduling, translation, rendering, source tracking, or packaging.
4. Maintain a concrete checklist with acceptance criteria, implement incrementally, and test the affected subsystem.
5. For a shipped code change, run relevant regressions, the full suite when warranted, native fixture checks, and the packaged smoke test. Deploy the tested folder, then verify it starts.
6. Report measured results, what was actually exercised, and remaining limitations. A fixture render is not proof of live desktop interaction or universal OCR accuracy.

Check the current Git state before issuing Git operations; the working checkout and published release may differ. The previous desktop OCR baseline was recorded before repository initialization.

## Current verified baseline

The themed Settings window now uses `window_frame.py` for Windows native resizing: WS_THICKFRAME enables the OS resize loop, WM_NCCALCSIZE preserves the custom client/title area, and WM_NCHITTEST identifies all eight edges/corners using physical screen coordinates and a DPI-scaled border. Maximized/fullscreen windows do not expose resize hits. Preserve this alongside title-bar dragging and controls; the bottom-right QSizeGrip alone is insufficient. `tests/test_window_frame.py` checks real HWND hit-test messages, the native style, all edges/corners, and scaled-border classification.

Resize-fix verification on 9 October: 171 tests passed, two optional video fixtures skipped, two warnings; staged EXE bundled-translation smoke passed and the guarded deployment replaced `dist/ArabicLens` and portable ZIP, restarting minimized. Evidence: `artifacts/window-resize-checklist.md`, `window-resize-regressions.log`, and `window-resize-smoke-final/offline-translation.json`. Native message tests exercised resize hit handling; physical mouse dragging at every edge was not separately recorded.

On 9 October 2026, the full suite passed **156 tests**, with two optional video tests skipped because the supplied local recording was unavailable. Native Windows capture/OCR tests ran in the desktop context. The integration test now yields the Python GIL with `time.sleep` between Qt event pumps; a long `QTest.qWait` could starve the engine thread and manufacture a timeout. Production code was not changed for this test fix.

The final updater-enabled 0.1.0 installer passed isolated installation, installed bundled-model translation, running-app reinstall with exactly one automatic reopen, uninstall, and preservation of separate user data. Its SHA-256 is `a32ead8efa67d874b6e295d2e5a5b17422c186b4f6f4f68158849889cd58e2ff`. Source and installer are published at [v0.1.0](https://github.com/farhanr3001/ocr-translate/releases/tag/v0.1.0). Future versions require a rebuilt installer and a newer published release; a source push alone is not an update.

These are recorded results from the preceding implementation, **not a fresh test run performed for this documentation-only change**. The `artifacts/` evidence directory is ignored by Git because it contains generated screenshots, logs and local test data. Links below resolve in the original developer checkout only; regenerate fixture evidence before making a new public claim.

| Evidence | Recorded result |
| --- | --- |
| [Full regression log](artifacts/desktop-coverage-tests.log) | 142 passed; two third-party deprecation warnings; 55.61 seconds |
| [Packaged smoke result](artifacts/desktop-coverage-smoke-final/offline-translation.json) | Successful startup and real bundled-model translation |
| [Coverage findings](artifacts/desktop-clean-coverage/findings.md) | Issues, fixes, measurements and known misses |
| [Latest completed checklist](artifacts/coverage-improvement-checklist.md) | Coverage, progress display, bilingual ignore list, performance, regressions and deployment |
| [Clean desktop fixture](artifacts/desktop-clean-coverage/source.png) and [OCR output](artifacts/desktop-clean-coverage/coverage.json) | 71 blocks after filtering/reconciliation in both selection and fullscreen audits |
| [Translation outputs](artifacts/desktop-clean-coverage/translation-results.json) | 71/71 processed; 70 Arabic results and one account handle preserved verbatim |
| [Rendered translations](artifacts/desktop-clean-coverage/translated-screen.png) | Actual production Qt overlay rendering with actual model outputs, composed onto the fixture |
| [Detection/progress preview](artifacts/desktop-clean-coverage/translation-boxes.png) | Actual progress widget rendered at the detected stage |
| [Model benchmark](artifacts/desktop-clean-coverage/model-benchmark.json) | Ten mixed inputs: approximately 0.396 s sequential vs 0.119 s batched after initialization |
| [Build log](artifacts/desktop-coverage-build.log) | Latest recorded packaged build |

The executable and portable ZIP were replaced after those checks. Artifacts can be regenerated or removed; missing evidence is not a passing result. Measurements are from the development PC, not the target HP Victus 15 fa2082wm laptop.

## Product contracts: preserve these

### Translation and layout

- English → natural, concise Modern Standard Arabic. Do not introduce Darija, explanations or additional facts.
- Keep proper RTL shaping, punctuation, Arabic-compatible fonts and readable contrast.
- Preserve paragraphs, blank-line gaps and list rows. Wrapped lines of a sentence belong together; unrelated controls, chips, labels and table cells do not.
- Keep numbers as Western digits **0–9**, with their actual values, decimal separators, currency and grouping punctuation. Inside prose, include them in the Arabic message. In a separate label/value UI cell, translate the label and leave its independently displayed number alone.
- Decode HTML entities such as `&quot;` in results. Do not show provider markup or raw OCR garbage.
- Translate eligible single words as well as sentences. Do not restore a large minimum-character threshold or a dialogue-only filter to conceal incomplete coverage.
- Ignore matching is on the normalized **whole reconstructed source entry**. `CONTINUE!` may match `Continue`; `Continue through the tunnel until you reach the village.` must translate. Do not remove ignored words from a larger sentence or filter its OCR lines before grouping.
- The ignore list's Arabic column is an editable reference. The English source entry controls matching; this is not an Arabic-output substring blacklist.

### Lifetime, independence and input

- Normal translation overlays have **no expiry timer**. A legacy duration field is not permission to bring expiration back. Temporary error/status notices may expire.
- Remove/update a translation when its source changes, disappears, leaves the view, or its source window closes, hides, minimizes, moves or resizes. Explicit hide, dismissal and disabling Watch can also clear it.
- A click, focus change, keyboard input or scrolling somewhere else is not evidence that a source text disappeared. Invalidation must follow relevant visual/window-state evidence.
- Each selected Watch area has independent change detection and processing state. Motion inside one area must not trigger OCR, translation or removal in an unchanged area. Motion outside every selected area must not affect their content.
- Fullscreen has the same contract at text-block level. Changed content in a tile does not justify replacing every unchanged block inside that tile.
- Presets and newly created areas enter the same processing pipeline. A preset is stored geometry, not a different OCR mode or an executable binding.
- Cancel obsolete work and reject late results by region/session revision. One failed text must not block unrelated regions or produce a permanent backlog.
- Overlays are capture-excluded, non-focusing and click-through during ordinary use. **Ctrl+Alt held while hovering** enables controls. Recheck modifiers in mouse handlers, not just in the hover polling loop.
- Overlay controls include dragging the body, close, collapse/expand, font zoom and copying Arabic. Keep controls compact; the close button is a 28 px circle outside the top-right corner.

### Simplicity, resources and safety

- Default translation is bundled, free, offline and ready to use. Do not require the user to obtain a key, configure a server or install a model. External providers belong in optional advanced setup.
- The target is a gaming laptop, **HP Victus 15 fa2082wm**. Keep CPU work bounded and avoid competing with a game. CPU is the current default and only active model backend. The user permits an optional GPU backend if measured benefits justify it; it is not implemented simply because experimental GPU code exists.
- Idle scenes still require lightweight preview/window checks. Do not describe this as literally zero CPU or an event-only capture implementation. Idle scenes should skip expensive OCR and inference.
- Use ordinary Windows APIs. Never inject DLLs, read another app's process memory, manipulate game rendering, automate gameplay input, or add game hooks.
- Preserve the soft green application theme, themed title bar, bilingual interface and close-to-tray behavior. Keep setup short and normal use quiet.
- Wheel scrolling over a property must scroll the page without changing that property's value. Preserve Overlay's restore-defaults action and the live preview.
- Preserve user data during development and updates. Do not reset settings/cache/history to make a test pass.

## User-visible features and flows

| Feature | Behavior |
| --- | --- |
| Quick Translate, **Alt+Q** | Dim the monitor, drag a rectangle, release to submit; Esc cancels. No confirmation click. Source tracking keeps the result until its source is gone. |
| Repeat Region, **Alt+E** | Recapture the last Quick rectangle. Named pinned regions are also supported. |
| Watch, **Alt+W** | Start according to the selected startup option, or turn Watch off. |
| Add Watch area, **Alt+Shift+W** | Add a selected area to the active Watch workflow. |
| Hide, **Alt+H** | Hide current translations and invalidate pending results. |
| Translator page | User enters English and receives Arabic through the configured Translation setup. |
| Translation setup | Built-in switch beside its title; external-provider setup mutually exclusive. Preserve an already configured provider during upgrades. |
| System tray | Watch on/off, Quick, Repeat, pause, Settings, History and Exit; Settings close does not terminate the utility. |
| Ignore List | English/Arabic reference columns, bilingual search, add/edit/remove/defaults; only complete standalone labels ignored. |
| Block apps | Choose open/installed desktop apps or browse to an executable; normalized executable-path matching. Watch skips blocked apps. Manual Quick remains available. |
| History/cache | Optional searchable history and bounded persistent cache; separate clear actions. |
| Overlay customization | Font, size, colors, opacity, padding, corner radius, width, outline, shadow, placement, fade, presets, preview and defaults. |
| Match game appearance | Optional sampled styling overrides regular appearance. Includes warm paper treatment for Dressmaker; not a universal game-theme/font recognizer. |
| Show Translation boxes | Optional capture-excluded outlines with pipeline-stage percentages and error indication. Off by default. |

Shortcuts are editable with modifier combinations. Windows or other programs can reserve keys. Startup registers independent available bindings so one conflict does not disable all of them; settings edits validate conflicts and retain previous bindings when the change fails. An old Alt+R add-zone conflict caused regressions; its default is now Alt+Shift+W.

### Watch startup and presets

Four options beneath Enable Watch are mutually exclusive, in this order:

| Option | Activation |
| --- | --- |
| Watch fullscreen | Immediately watch the focused application's monitor, without selection. |
| Create New | Hide Settings; draw one or more areas; compact centered ✓ starts Watch, × cancels. Pointer over those controls must not remain a crosshair. |
| Use Previous | Immediately start with the most recently used areas. |
| Show Presets | Hide the main window and open the compact Watch Mode preset popup. |

The popup contains a selectable saved-preset list, an empty state, always-visible +/− controls (− disabled with no selection), Start with Preset, Start New, Use Previous and Close. The + flow asks for a **preset name first**, then optionally brings a selected open application forward for easy area selection. The app is only a focus aid. ✓ saves areas, returns to the popup and selects the new preset; × returns without changing saved presets. Start New begins immediately after selection, without automatically saving a preset.

Previous areas automatically become the latest normal selection or last started preset. Saved presets persist until explicitly deleted. Keep these concepts separate. Stored areas are physical desktop coordinates, not responsive window-relative layouts; recapture after changing window geometry or display layout.

## Runtime and dependency stack

Windows 10 version 2004+ or Windows 11, x64, with English Windows OCR installed. Python **3.10 x64** is the development runtime. The current environment uses 3.10.0; the packager has a narrowly scoped workaround for that patch release. Packaged users do not install Python.

| Component | Pinned dependency / role |
| --- | --- |
| UI and rendering | PySide6 6.11.2 / Qt Widgets, signals, QTextDocument RTL, tray and custom windows |
| Native integration | `ctypes` Windows APIs: DPI, GDI capture, HWND/source state, hotkeys, DPAPI and capture exclusion |
| OCR | PyWinRT runtime and Windows.* packages 3.2.1; Windows.Media.Ocr English engine |
| Images | NumPy 2.2.6, OpenCV headless 5.0.0.93, Pillow 12.3.0 |
| Translation inference | CTranslate2 4.8.2 and SentencePiece 0.2.1 |
| Optional HTTP providers | HTTPX 0.28.1 |
| Persistence | Python SQLite, JSON settings, Windows DPAPI credentials |
| Testing and packaging | pytest 9.1.1; PyInstaller 6.22.3 |

[requirements.txt](requirements.txt) and [requirements-dev.txt](requirements-dev.txt) are authoritative. [THIRD_PARTY.md](THIRD_PARTY.md) describes notices and model attribution.

### Active model versus retired experiments

The active built-in provider is [offline.py](arabic_lens/offline.py), model ID **`hplt-en-ar-int8-v1`**, with assets in `arabic_lens/data/cpu-en-ar`. It is HPLT's English–Arabic Transformer-base trained on OPUS/HPLT data, converted from Marian weights to CTranslate2 int8; approximately 86 MB of model assets. No training or fine-tuning has been performed for this app.

The pinned source revision is `66fc22dc4ee77aeb1cfd186cfdb6bd658bba36bd`, repository `HPLT/translate-en-ar-v1.0-hplt_opus`, CC-BY-4.0. The bundled [model card](arabic_lens/data/cpu-en-ar/MODEL_CARD.md) and `sources.json` hold provenance and hashes. The upstream card's Transformers instructions are not this application's inference path.

Inference uses CPU int8, `inter_threads=1`, `intra_threads=2`, beam size 2, a single executor worker and reduced worker priority. The model loads lazily. Pending requests coalesce for approximately 8 ms into batches of up to eight. Long/protected text has a separate fallback path; do not assume every request takes the plain batch path. Cancellation prevents obsolete queued results being published.

`model_runtime.py`, `data/translation`, `data/offline-en-ar` and some download/benchmark tools reflect retired TranslateGemma/Vulkan or Argos experiments. They may remain on disk. The active application does not use these as its default translator; the packaging spec excludes those old model directories. Do not resurrect them accidentally or describe them as the shipped backend.

`tools/fetch_cpu_model.py` reproduces model download/conversion, not normal app startup. It uses additional maintenance-time dependencies such as `requests`; check those before running it. Model re-download or replacement is unnecessary for routine UI/pipeline fixes. Preserve attribution, hashes and cache namespace isolation when changing a model.

## Architecture and ownership

```text
UI / tray / global shortcut
  -> Application routes mode and selection
  -> Engine worker event loop
     -> native capture + independent zone previews
     -> dirty crops / tracked blocks
     -> Windows OCR + coverage retries
     -> layout grouping / source filtering
     -> normalized persistent cache
     -> bounded translation provider / CPU batches
  -> revision-checked Qt signal
  -> OverlayManager / TranslationProgress
     -> source-window checks and visual anchors
```

| Files | Responsibility |
| --- | --- |
| `main.py`, `app.py` | DPI/bootstrap, command-line options, single-instance handling, tray, service composition, action routing, preset workflow, settings application, accepted-result delivery, smoke test |
| `engine.py` | Background asyncio processing, selected/fullscreen scanning, per-zone state, dirty-crop work, cancellation/revisions, scheduling and progress signals |
| `windows.py` | Native desktop capture, monitor/window geometry and Windows integration |
| `models.py` | Shared rectangle/text data structures |
| `detection.py`, `anchors.py`, `source_monitor.py` | Change/region tracking, bounded source-patch matching and source-window validity |
| `ocr.py`, `numeric_ocr.py` | Replaceable OCR interface, native English recognition, coverage retries and numeric recovery |
| `layout.py`, `text.py`, `formatting.py` | Containers/cells/paragraphs, normalization/filtering, formatting and values |
| `translation.py`, `offline.py` | Provider abstraction, optional remote providers, de-duplication/cache service, active local model and batching |
| `storage.py` | SQLite cache/history, memory cache, seed packs, limits and pruning |
| `config.py`, `localization.py` | Settings schema/migrations, DPAPI secrets and English/Arabic UI strings |
| `ui.py`, `design.py`, `ui_controls.py`, `titlebar.py` | Settings/Translator interface, theme, non-wheel-mutating fields and custom title bar |
| `selection.py`, `watch_dialogs.py`, `hotkeys.py` | Capture selection, multi-area setup/presets and global shortcuts |
| `overlay.py`, `appearance.py`, `progress.py` | Actual Arabic rendering, placement/interaction/style and optional detection progress |
| `app_catalog.py`, `app_picker.py`, `ignore_labels.py` | Open/installed app discovery, blocking UI and bilingual ignored-label references |

The Qt UI runs on its main thread. Engine owns a background thread and asyncio loop, with the Windows Runtime apartment initialized appropriately. OCR access is serialized; translation has bounded concurrency and its own model executor. Cross-thread UI changes go through signals. OpenCV is limited to one processing thread for the small crop workloads.

### Watch processing details

Each zone keeps its own preview/baselines, OCR image, tracker, text blocks, pending work and identifiers. Small previews are polled at about 250 ms under current defaults; `scan_ms` defaults to 500 in settings but the processing loop caps the polling interval at 250 ms. Read the code before equating a settings value to observed cadence.

Unchanged previews avoid full-size capture and OCR. Changed frames produce spatial dirty regions; existing block extents help preserve complete paragraph context. Dirty regions receive a short settling delay, with a bounded delay for continuously animated content. Scheduling rotates zone order to avoid starvation. Concurrency and region limits keep obsolete work from growing indefinitely.

Large areas are partitioned into overlapping tiles with separate ownership cores; OCR uses padded context and assigns a block by its center. Current padding is 256 px horizontally and 96 px vertically. Geometric/text reconciliation removes overlapping duplicate fragments, such as a paragraph plus its final line. It must not merge disjoint zones or unrelated nearby cells.

Unchanged source patches and equivalent recognized text retain their region identity, accepted translation and position. Visual anchors can move a translation with its unchanged source patch without running the model again. A changed tile does not invalidate all of its blocks. All delivered results must still match the current session/region revision.

The optional source-window monitor checks about every 75 ms. It tracks window identity, bounds and visibility; **foreground focus alone is not a disappearance signal**. Selection sessions, manual requests and application shutdown must cleanly cancel their own pending work. Manual requests currently pause Watch scanning briefly; this is an implementation tradeoff to consider when profiling.

### OCR coverage and grouping

Windows OCR supplies word/line boxes but no recognition-confidence scores. Do not invent confidence from this provider. Plausibility, shape/layout checks and alternative image passes are used instead.

New/changed crops receive a native pass, a second-scale grayscale/contrast pass, and targeted retries for unaccounted text-like strokes. Large images can be split for OCR limits. Complementary results are merged without duplicating recognized words or turning nearby numeric/icon noise into text. These audits run when OCR is needed, not on every idle preview.

Container/layout rules distinguish prose, separate columns, buttons, chips and label/value rows. Paragraphs are reconstructed before whole-entry ignore filtering. A lowercase short continuation can belong to a preceding prose line even if its height differs. The same relaxation must not fuse separate UI labels. `text.py` contains older dialogue-preference logic that is not the active OCR-first Watch policy; do not route general desktop coverage back through a selective dialogue-only path.

Text can still be missed or misread. Residual-stroke auditing improves coverage but cannot prove the entire image contains no undetected text. Test both recall and over-grouping/false positives.

### Translation, cache and formatting

`ITranslationProvider` is replaceable. TranslationService de-duplicates concurrent requests by normalized source, checks cache before inference, limits work with a semaphore, and preserves formatting/value rules around provider calls. One provider error should be reported/retried regionally; a rate limit can trigger a bounded provider backoff.

The cache has a 256-entry memory layer and bounded SQLite storage (5,000 default entries). The key normalizes whitespace/case and appropriate punctuation while preserving meaningful explicit line layout. Cache ownership distinguishes the active model or remote-provider configuration; reviewed seed entries can be reused. Do not accidentally serve another model's stale output after switching providers or collapse list layout into a single cache key.

History is optional, defaults to 500 entries, and includes source, Arabic, time and application metadata. The reviewed Dressmaker pack currently has 165 entries from eight official screenshots and 62 trailer frames. This is **pre-seeding**, not model training or the full game script. Seed updates add entries without overwriting user translations. A missing optional pack must not crash startup.

Standalone handles may deliberately remain unchanged. Protected abbreviations and reviewed short terminology avoid mistranslations such as treating NFL as an unrelated organization. Completion and Arabic output are not quality scores: slang, names and wrong OCR can still translate incorrectly.

### Overlay and progress rendering

Production rendering uses QTextDocument with RTL layout and Arabic-capable fonts. Default placement is Replace, anchored to source geometry. Compact labels and multiline paragraphs have different sizing rules; keep bounded expansion and readable minimum sizing. Dense content can still crowd or overlap and requires visual review, not just string assertions.

Capture exclusion prevents the app from OCRing its own translations and progress outlines. Windows input-transparent/no-focus flags protect normal desktop interaction. Modifier-held controls restore temporary interaction, then return immediately to click-through behavior on release.

Progress is opt-in and stage-based:

| Display | Meaning |
| --- | --- |
| 25% | Text block detected |
| 50% | Work queued |
| 75% | Submitted for translation |
| 100% | Result accepted/displayed, or an identifier correctly preserved |
| Amber `!` | Failed/unavailable work requiring retry or attention |

These numbers are not elapsed-time estimates, token percentages or percentages of all text on the screen discovered. They describe detected blocks. Progress entries must follow the same source lifetime and independent-zone rules as translations.

## Settings, data and privacy

Runtime data defaults to `%LOCALAPPDATA%\ArabicLens`: `settings.json`, `translations.db` (SQLite WAL), lock state and `app.log` with rotation. Current log size limit is 256,000 bytes with two backups. API keys are stored as Windows-user DPAPI ciphertext, never plaintext. Normal operation does not persist screenshots or send them to remote providers; optional providers receive recognized text. The built-in provider sends neither.

Tests must use `--data-dir` or temporary stores. Never copy a user's keys/history into a fixture or a distributable. Diagnostic captured text and screenshot artifacts may contain private material; keep these out of normal logs and public distributions.

Current settings schema is **7**. Defaults include built-in offline translation, UI filtering on, minimum text length 1, up to 128 regions, source-following on, Ctrl+Alt interaction, Replace positioning, and persistent overlays. Migration logic preserves configured providers and customizations, switches unconfigured legacy providers to built-in, and repairs old default thresholds/shortcuts. Add migration tests for future schema changes; do not blindly reset a user's edited value because a default changed.

## Test workflow

### Development setup and routine commands

Run PowerShell from the repository root:

```powershell
.\Setup.ps1
.\.venv\Scripts\python.exe main.py --data-dir artifacts\dev-session
.\.venv\Scripts\python.exe -m pytest -q --disable-warnings
```

Setup installs development requirements; packaged users do not run it. Use a separate development data directory and avoid starting competing instances with the same global shortcuts. Tests use an autouse fixture to keep ordinary Qt test widgets off the visible desktop; native capture/input tests still need a real Windows desktop session. Do not surprise the user with repeated full-screen test windows or error dialogs.

Under a restricted execution token, native capture tests may fail with `Screen capture unavailable`. If authorized tooling can run them in the real desktop context, do so. Otherwise report the limitation; do not replace native capture with a stub and claim the original test passed. Inspect skip counts and missing-fixture reasons too.

### Regression map

| Tests | What to protect |
| --- | --- |
| `test_core.py`, `test_translation_cleanup.py`, `test_document_layout_and_tracking.py` | Normalization, entities, numeric integrity, paragraphs/lists and tracking |
| `test_ocr_coverage.py`, `test_desktop_coverage.py`, `test_cell_layout.py` | Native fixture coverage, complementary passes, paragraphs vs cells, fragments, labels and numeric/icon noise |
| `test_engine_integration.py`, `test_multi_region.py`, `test_watch_isolation.py` | Independent zones, changed crops, stale tasks, unchanged block retention and bounded processing |
| `test_watch_video_replay.py` | Recording-driven change detection and navigation retention; inspect where OCR is stubbed |
| `test_quick_translation_reliability.py`, `test_overlay_lifetime.py`, `test_source_monitor.py` | Manual results persist, source-state invalidation, no disappearance on ordinary focus/click changes |
| `test_hotkey_reliability.py`, `test_overlay_interaction.py` | Registration conflicts, modifier gating, drag/close/zoom/copy/collapse behavior |
| `test_watch_workflow.py`, `test_app_blocks_and_controls.py`, `test_ui.py` | New/previous/preset/fullscreen flows, blocked apps, field scrolling and settings wiring |
| `test_offline.py`, `test_provider.py`, `test_seed.py` | Real model, provider errors, caching, seeds, cancellation and translation contracts |
| `test_startup.py`, `test_windows_integration.py`, `test_preview_capture.py`, `test_appearance.py` | Native capture, startup, monitor/preview geometry and styling |

Tests are not all end-to-end: read fixtures/mocks before stating what they prove. First add a meaningful regression for a demonstrated bug, then fix it. Avoid tests that only mirror implementation constants or delete assertions to obtain a green run.

### Reproduce the desktop screenshot audit

Use the **clean source**, never the user's manually highlighted image or an image already containing Arabic overlays. Markings introduce false edges and OCR text. The preserved fixture is safer than a temporary clipboard pathname.

```powershell
.\.venv\Scripts\python.exe tools\audit_desktop_coverage.py artifacts\desktop-clean-coverage\source.png artifacts\desktop-clean-coverage
.\.venv\Scripts\python.exe tools\translate_coverage_fixture.py
.\.venv\Scripts\python.exe tools\render_coverage_preview.py
.\.venv\Scripts\python.exe tools\render_translated_fixture.py
```

Run these sequentially: translation reads `coverage.json`; rendering reads the recorded OCR/model outputs. Some helpers currently use fixed artifact paths; inspect them before substituting another screenshot. Preserve a baseline elsewhere before overwriting evidence when comparing changes.

The audit uses production Windows OCR and fullscreen partitioning. The translation helper disables cache and uses the real CPU service for all detected blocks. It exits unsuccessfully if a block raises an error. The visual helpers render actual application widgets offscreen onto the fixture. They validate native text geometry, not real-time browser control. Inspect the rendered images at full size and review source/Arabic pairs, not only the total count.

Acceptance checks should include navigation labels, tabs, body paragraphs, headings, sidebar descriptions, small controls, currency/list formatting, separate chip values, and background video text where readable. Record missed source words and layout defects. “71 processed” means those 71 blocks completed; it does not establish that every English word was detected or translated correctly.

### Scrolling and independent-area checks

```powershell
$env:ARABIC_LENS_WATCH_VIDEO = 'C:\path\to\your\local-scroll-recording.mp4'
.\.venv\Scripts\python.exe tools\analyze_watch_video.py $env:ARABIC_LENS_WATCH_VIDEO
```

The recording is user-provided and optional; it is not checked into the repository. Two video tests read `ARABIC_LENS_WATCH_VIDEO` and skip when that variable is unset or the file is unavailable. The replay exercises production scanning/change tracking with **stub OCR/translation**, so it measures isolation and call counts, not video OCR accuracy. In the recorded 29 scans, selected static navigation required one full capture/one OCR call; the moving feed required 23/six. A fullscreen navigation tile changed genuinely once in its top header and required two reads, while its unchanged label remained visible.

Required scenarios for future changes:

1. Two selected zones: scroll one, assert no new OCR/translation/removal in the static one.
2. One selected zone: move/scroll content entirely outside it, assert its translation and identifiers remain unchanged.
3. Fullscreen: change a nearby block inside the same tile, assert stable blocks are retained.
4. Click without visual/source change, including through a visible overlay: no reprocessing or disappearance.
5. Scroll source out, close/minimize/move its window, or replace text during a slow translation: stale overlay/results must not return.
6. Run equivalent setups through Create New and saved Preset; they must share behavior.
7. Repeated Alt+Q and Alt+E, including while Watch is running: selection invokes and resulting translations persist appropriately.
8. Hold/release Ctrl+Alt around mouse presses: only explicit overlay interaction is intercepted.

### Other fixture and performance tools

- `tools/evaluate_dressmaker.py`, `tools/render_dressmaker_examples.py`: game screenshot OCR and native Arabic overlay examples.
- `tools/render_document_examples.py`: paragraph/list fixtures with real OCR/model/rendering.
- `tools/render_watch_ui.py`: settings/workflow rendering.
- `tools/benchmark_cpu_translation.py`: uncached inference, process CPU/memory and cache timings.
- `tools/preseed.py`, `tools/expand_dressmaker_pack.py`, `tools/fetch_dressmaker.py`: phrase-pack maintenance. Inspect inputs/network behavior and review Arabic before shipping additions.

Benchmark cold startup, warm uncached text, cache hits, burst throughput, idle scanning and scrolling separately. Keep model settings equal when comparing batching. Measure on the target laptop before promising its resource use. Do not trade away required text coverage or source tracking to improve a timing number.

## Build, smoke test and replace the installed copy

For a normal fresh local build, `Build.ps1` makes the icon, packages the app, copies notices/README and creates the ZIP. When the installed `dist` app is running, prefer a staged build:

```powershell
.\.venv\Scripts\python.exe tools\build.py --distpath artifacts\watch-area-staged-dist --workpath artifacts\watch-area-staged-build
```

`tools/build.py` sanitizes PATH so unrelated FFmpeg/Poppler DLLs cannot contaminate dependency discovery. On Python 3.10.0 it applies a packaging-process-only bytecode workaround; it does not modify installed Python. `ArabicLens.spec` bundles PyWinRT, active data/model assets and notices, excludes retired models, selects the compatible PySide6 VC runtime DLLs, and rejects conflicting unversioned ICU dependencies.

Always smoke-test the **staged executable**, not just Python source. Use a new isolated output directory and wait for the GUI process to finish:

```powershell
$smokeDir = Join-Path (Get-Location) ('artifacts\packaged-smoke-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
$smoke = Start-Process -FilePath 'artifacts\watch-area-staged-dist\ArabicLens\ArabicLens.exe' -ArgumentList @('--smoke-test', '--data-dir', ('"' + $smokeDir + '"')) -WindowStyle Hidden -PassThru -Wait
if ($smoke.ExitCode -ne 0) { throw 'Packaged smoke test failed; inspect startup-error.log.' }
Get-Content -LiteralPath (Join-Path $smokeDir 'offline-translation.json')
```

Confirm success in the result and inspect generated English/Arabic UI images. Smoke mode catches startup failures to a file instead of displaying PyInstaller exception dialogs. Merely launching a GUI executable from PowerShell and seeing the shell return is not proof of success.

The existing [guarded deployment script](artifacts/watch-area-deploy.ps1) expects the staged paths above. Inspect it before use; despite living in `artifacts`, it is an operational helper rather than a generated report. It verifies workspace paths and the running executable path, refuses to replace a visible Settings session, stops the verified old instance, moves the live folder to a backup, installs the stage, refreshes the ZIP, restarts minimized and checks startup. It retains/restores the backup on failure paths where possible. Do not bypass its unsaved-edit safeguard or broadly kill every similarly named process.

```powershell
& .\artifacts\watch-area-deploy.ps1
```

After deployment, verify the exact executable path, running process, smoke evidence and ZIP timestamp. Preserve `%LOCALAPPDATA%\ArabicLens`. Keep the executable with its `_internal` directory; never replace only the EXE while leaving mismatched dependencies. For recursive moves/deletes, resolve absolute targets and verify containment in the intended workspace first, using native PowerShell `-LiteralPath` operations.

This developer handoff and `AGENTS.md` are repository documentation. Existing build scripts copy the user README and third-party notice; they do not currently package this handoff. A docs-only edit does not require restarting the app or rebuilding its executable.

## Installer and release updates

The distribution work adds a Windows installer alongside the portable build. Keep the installer and the application version synchronized; the runtime version used for update comparisons must be the same as the version embedded in the frozen EXE and installer. Follow [RELEASE.md](RELEASE.md) for release packaging, isolated install/upgrade verification and publishing. Keep `dist\ArabicLens\_internal` intact in development and portable builds; the installer hides that layout under the user's installed application directory and creates the normal app entry points.

The update backend is [arabic_lens/updates.py](arabic_lens/updates.py). It accepts the public repository `https://github.com/farhanr3001/ocr-translate` and checks GitHub's latest published release endpoint without credentials. The update interface is:

```python
service = UpdateService("https://github.com/farhanr3001/ocr-translate", __version__)
info = await service.check()                 # UpdateInfo or None
# Only after the person accepts Download update:
installer = await service.download(info, on_progress=lambda done, total: ...)
service.launch_installer(installer)          # then request normal app shutdown
```

Run `check` and `download` on a background event loop or worker. Their network and disk work must never block the Qt UI. The download callback receives **bytes downloaded, total bytes** and can signal UI progress. Cancelling the task removes its partial download. The main app owns prompt timing and consent: checking can be automatic, while downloading and installing only follow the user's acceptance. When no release exists, or the installed version is current/newer, `check()` returns `None`; failures raise a short `UpdateError` that should be presented without technical tracebacks.

For each public release, use a stable numeric tag such as `v0.2.0` and upload an asset named **`ArabicLens-Setup.exe`**. The GitHub asset must include its `digest` field in `sha256:<64 hex>` form, or the release must include `ArabicLens-Setup.exe.sha256` containing the exact installer's hash. The backend accepts only HTTPS release links for the configured repository, caps the installer at 1 GiB, follows HTTPS redirects, checks the exact published byte count and SHA-256, and checks its Windows `MZ` header. It stages the file in a unique system-temp update directory and will launch only a path previously verified by that service. It rehashes immediately before launch. The installer is started with Inno's `/SILENT /NORESTART /CLOSEAPPLICATIONS` switches; the calling app must then quit so Inno can replace files. The installer `[Run]` step is responsible for opening the new Arabic Lens minimized afterward. Do not register a second Windows application restart mechanism or duplicate launches can result.

The published hash and HTTPS protect against incomplete or altered transfer; they do not replace Windows code signing. Unsigned builds may still show Windows SmartScreen warnings. The updater does not push source commits to users: a tagged public release with the complete installer asset is the delivery step. Preserve `%LOCALAPPDATA%\ArabicLens` user settings, cache and history across reinstall/update; do not migrate data through the installer payload. GitHub's [latest-release API](https://docs.github.com/en/rest/releases/releases#get-the-latest-release) and [release-asset digest field](https://docs.github.com/en/rest/releases/assets#get-a-release-asset) define the feed contract.

The backend's offline HTTP/process tests are in [tests/test_updates.py](tests/test_updates.py). On 29 September 2026, its **13 tests passed**. They cover version ordering, missing/malformed/oversized release metadata, checksum companion parsing, HTTPS redirect downgrade rejection, truncated/oversized/bad downloads, cancellation cleanup, launch arguments and changed-file refusal. These use stubbed HTTP and process creation; they are not a real GitHub release or actual Inno upgrade test. Before publishing an update, test a local install, upgrading that installed version, its user data retention, desktop shortcut, app restart and uninstall on Windows. Record the exact installer build/hash/release URL and results in the release checklist.

## Troubleshooting and regression history

| Symptom | Investigate / established prevention |
| --- | --- |
| `QtCore` import DLL error / specified procedure not found | Packaging runtime DLL versions and polluted PATH/ICU discovery; preserve spec/build protections and test the staged EXE. |
| Missing `data/dressmaker.json` crashes EXE | Active data must be bundled; optional seed load must fail gracefully. |
| Alt+Q unavailable while UI capture works | Check registration results and collisions, independent startup bindings, active competing instances and settings rollback. Do not assume selection rendering is at fault. |
| Quick result flashes then vanishes | Check source HWND sampled after selection closes, revision checks, source monitor and capture exclusion. Do not fix by a longer expiry timer. |
| Clicking clears static text | Look for input/focus-driven invalidation, erroneous source identity and mouse-handler modifier races. |
| Static sidebar disappears when feed scrolls | Check per-zone state, dirty-crop scope, heartbeat/identity retention and cross-tile reconciliation. Do not reset all trackers on one crop change. |
| Only some text translates | Inspect OCR audit, filter reasons, grouping, ownership cores, region cap, pending queue and per-block failures separately. A model swap cannot recover text never submitted to it. |
| Adjacent tags become a paragraph | Container/cell boundaries, label/value splitting and line-joining rules. Test real dialogue paragraphs at the same time. |
| Tiny Arabic or oversized single-line headlines | Overlay compact-label classification, source line heights, bounded width and font fitting. Inspect actual Qt geometry. |
| `&quot;`, altered money/number values or broken lists | Provider cleanup, protected tokens, formatting restoration and cache normalization; test cached and uncached paths. |
| Indicators remain at 25% or 75% | Inspect queue/provider handoff, failures, cancellation and accepted-result signal. Never simulate percentage increments to hide stalled work. |

## Remaining limits and next-session discipline

OCR remains heuristic: stylized fonts, tiny video text, blur, occlusion, moving backgrounds and low contrast can fail. A concrete current fixture error is `GTA 6 lol` recognized as `GTA 6101`. The translator cannot safely infer the original number from that output. Some words such as “Live” need better context, and names/slang may be literal or wrong.

The app does not understand faces or gameplay HUD semantics. Placement uses geometry and sampled appearance. Dense overlays and long Arabic expansions need continued visual checks. Tracking is conservative around zoom, large jumps and changing backgrounds. Mixed-DPI coordinate mapping is implemented but needs real multi-monitor hardware verification. Standard GDI capture can fail on protected/exclusive fullscreen surfaces; recommend borderless/windowed mode rather than hooks. There is no shipped GPU backend or code-signing certificate. Release-update behavior must be verified with an actual published release and installed app before claiming it works on another laptop.

The previous attempt at interactive browser testing could not establish a verifiable browser URL through the computer-use tool. Native capture tests and fixture rendering passed; a live interactive X session was not claimed. Future agents should state their actual access and testing scope rather than infer success from screenshots.

For every substantive update, keep a checklist with the user's exact acceptance conditions, note affected modules, record commands/results and review images where layout changes. Use isolated data, narrow logs and bounded tests. Communicate findings and the next unresolved check during longer work. Before handing off, update the status/evidence links here, state whether `dist` was replaced, and identify any unresolved issue honestly. Preserve working subsystems rather than rewriting everything into one class or substituting a visual mockup for a functional test.
