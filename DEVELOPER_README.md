# Arabic Lens — developer and AI handoff

Last reviewed **23 November 2026**. This document preserves the product decisions, implementation map, verification workflow and remaining limitations for the next developer or AI assistant. Read it alongside [README.md](README.md). Code and current test results take precedence if this snapshot becomes stale.

In 0.1.14 settings save at the point of editing. Overlay changes update the shared preview renderer immediately and restyle displayed overlays without recapturing or translating their source. The toolbox stays open while either translation tool runs, and its confirmed reset restores the complete overlay settings object. Replace mode honors the configured background opacity and checks capture exclusion per window. A failed exclusion retries once after showing the native window and uses adjacent placement for that overlay if Windows still refuses.

## Start here

Arabic Lens translates visible English into **Modern Standard Arabic** using ordinary Windows screen capture, Windows OCR, and a bundled English–Arabic translation model. It is a general desktop accessibility utility for text in applications, websites, videos and games.

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

### Seeing beneath capture-visible overlays; solid backgrounds (0.1.17)

0.1.16 kept Replace in place on PCs that refuse capture exclusion, but the engine then blanked its own overlays and treated the covered English as unknown, so overlays never retired when that English scrolled away or vanished (photo from the build 22000 laptop: stale Arabic stacked over a chat). `Engine._masked` now asks `windows.WindowBeneathCapture` for the application window beneath each capture-visible overlay: the topmost visible window of another process that is not input-transparent or cloaked, rendered with `PrintWindow(PW_RENDERFULLCONTENT)` (one render per window reused for 0.2 s; an all-black render, which GPU windows produce intermittently, is retried once). Rectangles crossing a window edge are assembled from each window. `fill_own_overlays` pastes those pixels only if a 10 px ring around the overlay (excluding all our overlays) matches the live screen within a mean difference of 10; otherwise it falls back to blanking and the region stays protected (exclusive fullscreen, protected video, a window that changed between render and capture). With a verified fill, nothing is protected, so every engine decision is the same as on a PC whose Windows accepts exclusion. Measured here: 12–25 ms per full-window render. Progress outlines/badges and the developer region outline windows also report their drawn rectangles when their exclusion is refused (`overlay.outline_capture_rects`, `TranslationProgress.capture_rects`, `Application.debug_capture_rects`).

`tests/test_native_covered_text.py` runs real capture/OCR/model against a separate-process window with exclusion refused: the overlay stays while its English is there, leaves when the English disappears and the new English is translated. With `WindowBeneathCapture.pixels` disabled it fails exactly as on the laptop. `tools/live_scenarios.py` honours `ARABIC_LENS_REFUSE_EXCLUSION=1` for parity comparisons. A full both-modes scenario comparison was started but stopped at the user's request; only part of the normal-mode pass ran (chat-overlap, wrapped-sentence and a desktop-dependent fullscreen subtitle check failed there, not compared against 0.1.16).

Overlay backgrounds default to 100% opacity (was 78%; game-matched style 90% → 100%). Settings schema 9 migrates a saved 78 to 100 and keeps any other chosen value.

### Replace stays in place when capture exclusion is refused; toolbox visible to sharing (0.1.16)

On the second laptop (Windows 11 21H2, build 22000) 0.1.15 logged `Capture exclusion refused (Windows error 8 ...)`: `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` fails with ERROR_NOT_ENOUGH_MEMORY for the translucent, click-through (layered) overlay windows, while the ordinary toolbox window is accepted. The same failure is reported publicly for transparent Qt overlays on Windows 10 22H2 (LunaTranslator issue 2634); Microsoft documents no cause. The old fallback moved every Replace overlay beside the text at the full default size, which looked like boxes "organised all over the screen". At the user's direction, Replace now keeps its normal in-place placement and size when exclusion is refused. The engine already blanks capture-visible overlays out of its captures (`Engine._masked` / `fill_own_overlays`) and treats text ≥50% beneath them as unknown, not gone, so overlays neither OCR themselves nor flicker. Trade-off on such machines: a change to text completely hidden under an overlay is noticed only when its surroundings change. The first refusal is still logged once. A non-layered "solid" overlay retry was prototyped and dropped (Qt's input transparency always makes the window layered; unverifiable on the affected build).

The toolbox is no longer excluded from capture (RustDesk/screen sharing showed it as a black box). Its area stays masked from Watch/Quick OCR via `Toolbox.capture_bounds`, so text physically behind the toolbox is not read. `tests/test_quick_translation_reliability.py` moves the toolbox off the fixture text for that reason.

### Replace placement over the taskbar (0.1.15)

A photo from the second laptop showed Replace placing the Arabic for the taskbar's "Search" box above the taskbar instead of over it. `OverlayManager.show` clamped Replace boxes to `availableGeometry()` (screen minus taskbar), so any source inside the taskbar or another reserved edge was pushed out of place on every machine. Replace now clamps to the full `screen.geometry()`; Below/Above still keep clear of the taskbar. `tests/test_overlay_lifetime.py::test_replace_covers_text_inside_the_taskbar_in_place` failed on 0.1.14 and passes now. Placement was also checked with Qt simulating 125% and 150% scaling (source and overlay physical rectangles agree within a few pixels; `test_hold_drag_collapse_expand_and_individual_close` assumes 100% scaling and fails at simulated scale with or without this change). The capture-exclusion fallback (Replace → Below when `SetWindowDisplayAffinity` is refused) is unchanged, but its first occurrence now logs the Windows error code and build to `app.log`; if the laptop still shows beside-the-text placement after updating, that log line identifies the cause. Background suite 258 passed/two optional skips; staged visible and offscreen smoke, a live 0.1.14→0.1.15 delta (2 files, single reopen, model unchanged, data kept) and a guarded clean install all passed. Evidence: `artifacts/release-0115/verification.json`.

### Watch tooltips and Quick Translate dismissal (0.1.13)

Fullscreen Watch gives newly changed small regions priority over broad motion. Moving tiles use an initial OCR pass with targeted recovery for bright labels on dark cards. The detailed OCR audit runs after the tile settles. The normal stability policy remains for edited text and general paragraphs. Short labels on visually bounded backings can start offline translation early, including compounds absent from the English dictionary. Before placing the result, Watch verifies the source pixels, checks pale glyphs against dark animated backings where applicable, or rereads a small region. Each tile keeps its own scene and dirty rectangles. A transient capture error is retried on a later Watch tick.

Alt+Q opens a selection or dismisses a visible Quick Translate group, including late results from the same request. It leaves Watch running. Translate Again and its shortcut were retired from Home, the toolbox, the tray and Shortcuts. Named saved regions still use manual capture. The small-row audit can reread a fractured 13–14 px row to recover bold text lost by the first recognition pass.

Verification used the user's 77.7-second Minecraft recording at its original screen resolution, the reported bold-text screenshot, and regression tests for Watch isolation, source retirement and manual capture. The recording was replayed into the production pipeline with offscreen Qt widgets. It supplies real game pixels and hover/scroll timing. Capture failure recovery has a separate regression test. Private recordings and per-label trace files remain under `artifacts/minecraft-0113` and are excluded from publication.

For 19 manually reviewed menu and tooltip cues, final Watch showed an Arabic overlay from the correctly recognized label in time for 11, versus zero in the clean 0.1.12 replay and one in the first baseline run. The 11 matched results had a 542 ms median display delay and a 417 ms maximum delay to retirement after the reviewed cue ended. The runs decoded all 4,661 frames after the initial frame and used 142 CPU-seconds each including replay overhead. Both versions stayed enabled in replay. Several short labels and stylized menu entries still failed recognition. A separate PaddleOCR sample read some of the pixel-font labels better but took 375–1,154 ms per sampled full frame, before translation. The release keeps Windows OCR.

The background suite passed 255 tests with two optional replay skips and the desktop-interactive fixture excluded. The staged and isolated installed executable passed the packaged OCR and overlay smoke tests. File updates from 0.1.12 and 0.1.5 reopened the application once and preserved settings and the model. The full fallback matched the staged payload.

### Startup readiness (0.1.12)

`Application` schedules `Engine.prepare` after setting up the UI, including on minimized startup. It runs a synthetic image through the existing Windows OCR provider under the normal OCR lock, and one synthetic sentence directly through the built-in provider's existing worker. No desktop capture, user cache, history, results, or external provider is involved. Quick Translate and Watch reuse the same initialized instances. Normal requests still create the engines if needed, and switching back to the built-in provider prepares it when it has not been used. The app has no preparation timer or scan loop when its tools are idle.

CTranslate2's optional MKL packed matrices are disabled by default before import. In the local benchmark, packing increased private commitment substantially. The same model, tokenizer and decoding settings produced identical output on the short, long and numeric examples in the benchmark. The first OCR-plus-uncached-translation sample took 442 ms with lazy initialization and 66–67 ms after low-memory preparation. The minimized packaged app used 219 MiB of working set and 430 MiB of private commitment, up from 97 MiB and 281 MiB in 0.1.11. Both registered zero process CPU time over the measured ten-second settled idle interval. These measurements are local and exclude desktop capture and overlay paint from the latency calculation.

The background suite passed 252 tests with two optional video skips and the desktop-interactive selection fixture excluded. The staged and installed background smoke tests recognized English and produced an Arabic overlay. Exact-baseline 0.1.11 and 0.1.5 delta updates reopened once and preserved the model and settings. The full fallback reconstructed the staged payload. See `artifacts/readiness-0112` for the release checklist, measurements and test logs. The motion-specific PaddleOCR adapter remains a separate prototype.

### Closely spaced text and live edits (0.1.11)

- [x] Reproduced the small-text split on the supplied AnyDesk screenshot. Windows OCR now returns both complete lines in the original image and in a tight crop at the same pixel scale.
- [x] Verify separate rows and intact click-through Replace placement with seven rendered font sizes from 10–32 px. Verify eight appended rows at 12, 20 and 32 px, including wide gaps and clock values.
- [x] Passed all 27 steps of an 80 WPM replay at 12, 20 and 32 px. Each case appended eight varied lines across two large gaps and replaced a middle line. The rendered Arabic widgets covered their source boxes, stayed separate, preserved digits, and kept unaffected overlay IDs. Each final state was ready within 916 ms of its final keystroke in this replay.
- [x] Background suite passed 252 tests with two optional video skips. The desktop-interactive selection fixture was excluded to keep test windows off the desktop.
- [x] Staged and installed OCR, model and overlay smoke checks passed. Both matched deltas applied the exact final executable and reopened once while preserving settings and the model. The full fallback matched the staged payload. Updated the workspace portable copy.
- [x] Published [v0.1.11](https://github.com/farhanr3001/ocr-translate/releases/tag/v0.1.11) from `3902a8c`. Production updater verified the public 6,098,433-byte delta from 0.1.10 and 6,105,732-byte delta from 0.1.5. See `artifacts/compact-0111` for the offscreen screenshot replay, font-size matrix, typewriter results and release verification. The size matrix read both supplied screenshot crops correctly, with some OCR errors below 11 px on the synthetic fonts.

A horizontal pixel gradient locates actual narrow text rows for a localized 3×/4× reread when the existing OCR splits a row or misses part of it. Covering overlays use the measured pitch of nearby rows and can refit an existing widget when another row arrives. Watch checks small changes briefly after visible edits and preserves an intact neighboring line even when a subsequent OCR read combines it with a line being typed. Suspect clock digits are accepted only when enlarged reads agree and preserve the other characters.

### Toolbox and live Overlay settings (0.1.10)

- [x] Verified the native resize messages for all edges and corners, both window modes, shared Watch choices and persisted toolbox pin.
- [x] Verified fixed preview placement while scrolling, initial placement and color, live style changes, reset and on-disk persistence without Apply. Reviewed offscreen renders in English and Arabic.
- [x] Verified per-area removal, redraw and confirmation in Watch setup.
- [x] Moved the initial asynchronous update check to 750 ms. Verified that the toolbox counts as a visible window for update notifications.
- [x] The staged and installed EXEs passed background OCR, offline translation and overlay smoke checks. Silent install and guarded uninstall preserved existing data. The live delta reopened the app once and kept the model file and saved Overlay and toolbox settings. It removed the retired data pack. Verified both package payloads and checksums. The full fallback applies its payload without removing unlisted files from older installations.
- [x] Replaced the workspace portable folder and published [v0.1.10](https://github.com/farhanr3001/ocr-translate/releases/tag/v0.1.10) from `cb66046`. The 0.1.9 updater found and downloaded the verified 6,099,270-byte delta. The 0.1.10 updater reported current. Evidence is in `artifacts/ui-0110`.
- [x] Added a 6,099,270-byte delta for 0.1.5 to the same release after a user reported a slow fallback download (201,563,798 bytes). An exact shipped 0.1.5 copy upgraded quietly, reopened once, preserved settings and kept the model. The original 0.1.5 updater selected the new GitHub asset, downloaded it and verified its checksum and resulting file hashes. Evidence is in `artifacts/ui-0110/from-015`.

The compact toolbox is the initial view on a normal launch or tray reopen. It exposes the same Watch startup choice as Settings. Pinning persists and keeps the toolbox above other apps while open. Both control windows hide during region capture. The main window still uses native edge/corner hit testing. Overlay controls update the renderer immediately and debounce disk saves; shutdown also saves pending values. Replace preview fits a sample line using the same renderer as actual overlays. Match source appearance uses a neutral dark sample in the preview and the captured region on screen.

The background suite passed 234 tests with two optional video skips and the desktop-interactive selection fixture excluded. The packaged command `--smoke-test --minimized --data-dir <isolated path>` uses a Qt-rendered English sample, Windows OCR, the bundled model and the actual overlay widget without showing a test window. It sets `offscreen_pixels` in the report to distinguish that test from the visible desktop capture exercised by `--smoke-test`.

### Consecutive video subtitles (0.1.9)

- [x] Give a retired Watch row an explicit, bounded OCR retry. Use a shorter change cadence for narrow subtitle-shaped selections and permit early verification of unpunctuated text in that path.
- [x] Verify matching words via localized Windows OCR if exact pixel verification fails on a moving background. Keep the original region and revision checks.
- [x] Background suite passed 231 tests, with two optional skips. Windows OCR confirmed the same words across three synthetic subtitle changes and rejected the preceding words when the next subtitle appeared. The provided screenshot informed the test; the actual video and its timing remain unverified.
- [x] Verified silent install, minimized startup and guarded uninstall. The 0.1.8 copy applied the delta, reopened once and retained user data and the exact model file. Verified the full app-file fallback and both ZIP payloads and checksums. Replaced `dist/ArabicLens` without launching it.
- [x] Published [v0.1.9](https://github.com/farhanr3001/ocr-translate/releases/tag/v0.1.9), source `a471654`. The production updater found, downloaded and verified the two-file, 6,086,185-byte delta from 0.1.8 and reported 0.1.9 current.
- [x] Replayed four captions over a changing synthetic background with the Watch loop, Windows OCR and warmed bundled model. The first caption used pixels from the supplied screenshot. With 750 ms and 1,500 ms caption holds, 0.1.9 emitted full Arabic results for all four before replacement (222–389 ms across both runs). The 0.1.8 engine emitted none on the same frames. The longer run also briefly emitted a partial first line. These timings end at the engine's translation signal. They do not measure visible paint or performance on the user's video. Evidence and runner are in `artifacts/watch-019`.

Sample-based text style filtering was investigated separately. A glyph comparison experiment could distinguish several fonts at the sampled size and took roughly half a millisecond per clean line, but similar fonts and size changes produced overlapping match scores. Do not use those scores as a hard production filter. An optional Watch-only setting would need to demonstrate that it preserves wanted captions over moving backgrounds while reducing unwanted translations. OCR would still run before the comparison.

### Watch overlay responsiveness (0.1.8)

- [x] Confirm strong changes to shown Watch text using two samples. Check for scrolling before retirement, keep ordinary OCR confirmation when evidence is ambiguous, and limit the additional capture budget to one eligible Watch zone per tick.
- [x] Clear confirmed Watch retirements immediately and start completed edits through the existing early job. Verify the OCR source row before swapping overlays. Quick Translate and translation rules are unchanged.
- [x] Prototype chat and typewriter captures passed exact completed-line output, disappearance, and chat scroll checks. The user requested no further desktop test windows during integration; the integrated visual run was stopped. Background suite passed 228 tests with two optional skips, excluding the visible native selection fixture. Five focused tests passed, including completed-edit scheduling and preserving a scrolled line.
- [x] Verified silent install, minimized startup and guarded uninstall. The copied 0.1.7 build applied the live delta, reopened once, and retained data and the exact model file. Both update packages passed checksum and payload verification. The final build replaced `dist/ArabicLens` without launching it.
- [x] Published [v0.1.8](https://github.com/farhanr3001/ocr-translate/releases/tag/v0.1.8), source `7db429b`. The production updater found and verified the two-file, 6,085,937-byte delta and reported 0.1.8 current. Evidence is in `artifacts/watch-018`.

### Watch scheduling, 21 November 2026 (0.1.7)

- [x] Preserve model, OCR grouping, Quick Translate, and overlay removal policy. Start offline Watch translation early for new complete lines at default stability. Before display, verify the original OCR row against a fresh capture and relocate it if the exact row scrolled. Ordinary Watch scheduling remains available when verification fails.
- [x] Preserve the distinct experimental and production modes in `tools/watch_speed_ab.py`. Prototype evidence is recorded in `artifacts/watch-speed/verified-comparison.json`.
- [x] Integrated live fixture passed with panes swapped. Stable subtitle appeared at 204 ms versus 683 ms; all six lines at 307 ms versus 882 ms. Chat passed exact output, coverage, duplicate and position checks. The experimental pane cleared, while the unchanged baseline retained an orphan. See `artifacts/watch-017/live-02/report.json`.
- [x] Final suite passed 226 tests, with two optional video-fixture skips. Guarded installer and live 0.1.6→0.1.7 delta tests both passed native screen translation, data preservation and single reopen for the delta. The final build replaced `dist/ArabicLens`.
- [x] Published [v0.1.7](https://github.com/farhanr3001/ocr-translate/releases/tag/v0.1.7), source `c0d99ee`. The production updater found and hash-verified the two-file 6,084,447-byte delta from 0.1.6, and reported 0.1.7 current. Evidence is under `artifacts/watch-017`.

### Settings redesign, 20 November 2026 (0.1.5)

- [x] Tone down the settings surfaces and title bar.
- [x] Keep the live position preview, presets, placement, and scroll following visible. Put detailed styling and behavior controls behind Advanced tuning.
- [x] Run the focused UI and appearance tests (5 passed).
- [x] Review packaged screenshots of Overlay in English and Home in Arabic. The initial Overlay preview can show Below while the Position field is set to Replace. Changing the position refreshes the preview.
- [x] Publish and verify the installer and updater. The guarded clean install/uninstall passed, including a native screen-to-overlay test. The live 0.1.4 delta test reopened once and preserved data and the model. Production updater discovery, download and payload verification passed. See `artifacts/ui-015` for local reports and `artifacts/publication-0.1.5.json` for the six-asset release.
- [ ] Evaluate one or more sampled subtitle styles against unrelated text and size changes before exposing a Watch filter.
- [ ] Benchmark time to first and last overlay for dense Quick Translate selections and time to removal when text disappears.
- [ ] Compare exact Windows text and OCR for recognition accuracy before choosing optional models. Evaluate English–Arabic model quality and latency before offering downloads.

### Watch/Quick overhaul, 21 November 2026 (0.1.6)

- [x] Watch rewritten around `arabic_lens/scene.py` (OCR reconciliation: grow/edit in place, absorb fragments, scroll matching, history line split, typing settle, full-res last-keystroke verify). Removed `_region`/`_read_dirty_zone`/RegionTracker use from the engine.
- [x] Hard line breaks in `text.group_lines` (terminator, first-word-fits, capitalised + area width); speaker lines start blocks.
- [x] `arabic_lens/chat.py`: speaker prefixes kept verbatim, slang/emote/nickname protection (offline `keep=`), elongation collapse, OCR name/message re-join. Clock times isolated whole in `formatting.display_values` (fixed 23:33 -> 33:23).
- [x] Quick: caret-tolerant anchors, fuzzy OCR confirmation (`same_words`), capture-visible fallback (mask own overlays, Replace->Below), late results re-tracked, optional timed mode (`overlay.quick_lifetime`/`quick_seconds`, auto reading time). Watch toggles no longer clear Quick overlays (`watch_cleared`).
- [x] Live checks `tools/live_scenarios.py OUT all` (editor/popup/chat fixtures): all typewriter, wrap, rewrite, popup, quick*, chat_slow/medium/fast scenarios passed on the last runs.
- [x] HUD/game-layout scenarios (`tests/fixtures/hud_window.py`): animated scene, static HUD values, changing quest objectives, pop-up notification, boxed dialogue typewriter, borderless one-line subtitle with a multi-word speaker ("Jimmy Jon:"). Passed in full-screen Watch (normal and tiled large window, focus pinned to the game) and multi-area Watch: one overlay per part, no drift, replacements and removals on time. Fixed on the way: cross-tile fuzzy dedupe (`same_place_text`), covered-segment retirement outside read strips, multi-word speakers.
- [x] Rewrote the 18 tests that used removed internals, keeping their behavioural promises (zone isolation, no static re-reads, click/hover keeps words, scroll debounce, video noise, document real-OCR paths). Shared `watch_engine` fixture in `tests/conftest.py`. New `tests/test_scene_and_chat.py` (26 tests: typing growth, ghosts, replacement, OCR miss, scroll identity, history split, settle, grouping, speakers incl. multi-word, slang/elongation, OCR name re-join, clock display, Replace-width limit, reading time).
- [x] HUD follow-ups from live review: Replace overlays never grow over neighbouring values ("Health 85 / 100": value positions recorded by OCR, `row_limit`, `limit_right`); numbers inside a phrase stay in it ("Level 7 Ranger"); text inside a detected panel may grow to the panel edge instead of wrapping. Area-width line-break rule only for short following lines (kept wrapped paragraphs whole in wide captures).
- [x] Settings › Overlay › Positioning: "Quick Translate overlay" (Until the text changes / For a set time) and "Seconds (0 = automatic)", Arabic strings, UI test; checked visually in English and Arabic.
- [x] Live-review follow-ups (chat): one Arabic size per Watch area/Quick selection (upper quartile of OCR line heights; no per-line scaling, longer text wraps at the same size); covering boxes match line pitch (no overlap at rest); speaker colon in RTL order (name/time isolated, colon in Arabic flow); OCR-split handles ("Happy9 234"); speaker lines with nothing to translate still get a uniform overlay; emotes/emoji/icon glyphs stripped before translation; 1.5 s full-resolution audit re-reads lines whose pixels changed below the preview threshold (cleared a stale "find t" ghost). `tools/live_scenarios.py` saves `composite.png` (screen + overlays).
- [x] Version bumped to 0.1.6 (source, resource, manifest). Verified exact 0.1.5 baseline (all 369 files match the published full ZIP) preserved at `artifacts/release-016/baseline-0.1.5`.
- [x] Disappearing chat messages: `chat_moderated` (moderator deletion mid-chat, capped history dropping the oldest) and `chat_cleared` scenarios; removed messages lose their translations within 2 s, the rest keep theirs. Drawn Watch areas now bind translations to the window beneath the area (not whichever app has focus, which wrongly removed them when that app moved). Blank pixels never protect a line from removal (cleared transient misread ghosts).
- [x] Release checks: full suite 225 passed (2 optional video skips). Live scenarios: every scenario passed in its latest individual run; the final combined run was stopped at the user's request after 21 of 25 scenarios (61 checks passed, one marginal: fast chat overlapped briefly in 5/27 scrolling snapshots vs a 15% target, none at rest). Staged and clean-installed 0.1.6 passed the screen smoke test; guarded install/uninstall preserved data and the real registration. A running copy of the exact 0.1.5 build received the 3-file 0.1.5 delta through the real helper, reopened exactly once, kept the model file byte-identical and passed the screen test. Evidence: `artifacts/release-016/verification.json`, `installed-test/`, `delta-live/`, `staged-smoke/`, `artifacts/live-scenarios-016/`.
- [x] Published v0.1.6 (source `1372b89`); production updater verified from 0.1.5 (`artifacts/release-016/public/verification.json`).
- Known limits: OCR occasionally glues words ("dontjp") or splits handles; a still frame cannot tell a lowercase continuation from a manual newline (Watch history can); a capitalised dictionary-word speaker that is also a label word ("Captain Price") is translated; full-screen Watch follows the focused window by design.

### Silent overlay drops, 19 November 2026 (0.1.4)

Report: a second user's Quick Translate saved the Arabic result to History but showed no overlay. Three silent exits after the history write were fixed: (1) `OverlayManager.show` closed the overlay when `SetWindowDisplayAffinity` was refused; it now shows it and reports the limitation; (2) in `_manual_translate`, a lost visual anchor skipped the result; it now shows it if `_source_unchanged` pixel-check passes, else emits `selection_changed`; (3) `show_translation` now reports a rejected manual result. The exact cause on that machine is still unconfirmed. Suite: 190 passed, 2 skipped; packaged/installed smoke incl. screen pipeline passed; delta 0.1.3 to 0.1.4 (2 files) applied to a copy of the shipped folder and the production updater detected v0.1.4 from 0.1.3 (`artifacts/selection-014-public/verification.json`). An in-place running-app update test was not repeated. `Publish-Release.ps1` was fixed for Windows PowerShell 5.1 (credential request BOM; notes sent as string). Note `artifacts/selection-013-baseline` was empty; `dist/ArabicLens` was the 0.1.3 baseline.

### Selected-area reliability, 18 November 2026 (0.1.3)

A remote report from Steam over AnyDesk described no overlay, also confirmed on the physical laptop. The bundled model is present and the typed translator working is evidence against a missing translation model; it does not verify Windows OCR or capture. The exact affected-laptop cause remains unconfirmed without its error/status or logs.

Inspection reproduced an independent selection bug: `schedule_capture` retained the pre-selection foreground HWND even when another window was under the selected rectangle, and tried to restore that old window first. It now resolves the selected window before focus restoration and rebinds the request to it. An initially stale manual source emits `selection_changed` rather than silently returning. Manual errors report to Settings, a temporary unbound notice, and a tray notification when Settings is hidden; an invalid source HWND must not suppress the failure explanation. Normal translation overlays retain source-driven lifetime and capture exclusion.

Native regression `tests/test_native_selection_ownership.py` launches controlled windows in a separate process and exercises real GDI capture, Windows OCR, bundled model and a visible overlay. It closes the unrelated previous window and verifies the selected source/overlay survives. `tests/fixtures/manual_selection_window.py` is its controlled fixture, not game automation. Targeted tests also cover missing-English-OCR errors and stale source notices. Windows OCR remains an OS dependency, separate from the bundled translation model; the local test machine lists ar-SA and en-GB recognizers. Do not describe this as proof that OCR is installed on the affected laptop. WDA_EXCLUDEFROMCAPTURE can also hide overlays from AnyDesk, but the report explicitly confirmed no local overlay, so remote capture exclusion alone was ruled out.

`--smoke-test` now also creates its own English fixture, uses real packaged capture/OCR/translation, verifies a visible Arabic overlay and writes `screen-translation.json`. It no longer treats a successful typed-model test as sufficient. Both `offline-translation.json` and `screen-translation.json` must report success before shipping. This deliberate developer test can briefly show its own fixture/overlay; normal startup is unchanged. Final suite: 189 passed, two optional video skips; the native test initially needed topmost fixture windows and deferred-delete cleanup to avoid occlusion by earlier test windows. The final suite passed after isolating the fixture.

### Workspace storage and cleanup

On 5 November, the checkout was audited for redundant storage. Duplicate test application folders, retired translation/Argos model assets, conversion downloads, old installer/update downloads, PyInstaller work files and rebuildable distribution ZIPs were selected for removal. Small regression reports, screenshots, fixtures, checklists and operational scripts remain. Historical reports are evidence of past runs; deleted test installations and package downloads must be regenerated before re-testing. The live `dist/ArabicLens` folder remains the exact current shipped baseline for the next delta. The latest installer/checksum, active `cpu-en-ar` model, `.venv`, Git history and `artifacts/installer-tools/InnoSetup` compiler are retained.

Use `Cleanup-Workspace.ps1` to preview known disposable targets and inspect `artifacts/cleanup-plan.json`; `-Apply` removes them after containment, link, protected-path and running-app checks. Run cleanup after finished release testing/deployment, not during a build or before generating deltas from the preceding baseline. Keep only the live baseline rather than retaining copies of entire test installations. Build fresh distribution ZIPs for a new release; already published assets remain downloadable from GitHub. Housekeeping changes do not change the installed app and do not require a version bump or new binary release. Cleanup measurements and protected-file verification are recorded under `artifacts/cleanup-*.json`.

Measured result: 9,362,093,713 → 1,818,209,877 bytes (8.72 → 1.69 GiB), with 7.03 GiB reclaimed; artifacts fell to 90,861,702 bytes (~87 MiB). All 374 protected files, including the complete portable baseline, active models, latest installer, compiler and regression fixtures, retained their hashes. The preserved packaged executable passed a fresh real offline translation smoke test (`artifacts/cleanup-verification-smoke/offline-translation.json`). User settings/cache/history outside the checkout were not touched. These are cleanup/smoke checks, not a newly run full regression suite.

Version 0.1.2 introduces app-only file updates. `updates.py` prefers `ArabicLens-Update-<installed-version>.zip`, then `ArabicLens-Update-full.zip`; legacy clients still discover `ArabicLens-Setup.exe`. `file_update.py` validates paths, package/file hashes, target/base versions and baseline files before staging outside the install folder. A hidden PowerShell helper waits for app exit, backs up changed/deleted files, applies them, reopens the app and rolls back on replacement/start failure. Unchanged model/runtime files are excluded from deltas. Full fallback downloads more but avoids Setup. Python source runs cannot apply packaged file updates. Standard per-user/portable folders must be writable.

Build packages with `tools/build_file_update.py CURRENT OUTPUT VERSION --baseline PREVIOUS --base-version PREVIOUS_VERSION`; also build a full fallback without baseline arguments. Publish both ZIPs and checksum sidecars alongside installer/checksum. Keep an exact preceding shipped portable folder available until all delta packages are built. Test real file application/reopen/data preservation and failure rollback, not just package extraction. Do not claim that an already installed pre-0.1.2 client can understand ZIP updates: its one compatibility update still uses Inno, with silent UI hidden by the new installer. No GitHub release asset should be overwritten.

0.1.2 verification: final full suite 184 passed/two optional skips; 29 focused updater tests passed. The final 0.1.1→0.1.2 file package contains three changed files (6,064,846 bytes), excludes the model, waits for app exit and reopens exactly one app. Real translation and isolated data preservation passed. A locked README after EXE replacement triggered rollback, restoring the original EXE and reopening the old app. Evidence is under `artifacts/seamless-live-test-release`, `seamless-rollback-test-final`, and `seamless-final-regressions.log`. Helper hashes use .NET directly because Windows PowerShell's Get-FileHash was unavailable in one inherited module environment. Backups/payloads are cleaned after successful reopen; cleanup failure must never trigger rollback. Full fallback packages also exclude unchanged files from the replacement plan after verifying them.

The legacy /SILENT compatibility test initially caught Inno re-showing its form after Hide callbacks. The installer now makes that silent form fully transparent and absent from the taskbar before first show, while retaining normal interactive installation. A native visibility/alpha probe passed the corrected 0.1.1→0.1.2 compatibility upgrade, single reopen, translation, uninstall and data-preservation checks (`artifacts/seamless-compatibility-transparent`). The preferred new fallback installer command is /VERYSILENT /SUPPRESSMSGBOXES; ordinary new updates use file ZIPs, not Inno.

**Installer-test isolation correction:** changing LOCALAPPDATA and /DIR does not isolate Inno's HKCU uninstall registration. Tests briefly displaced the real installed app's entry; its verified 0.1.1 registration was restored directly without changing app files/data. For every future installer test, dot-source `tools/installer_registration_guard.ps1` and run `Invoke-InstallerTestGuard { ... }` around the whole install/upgrade/uninstall sequence. It snapshots and restores the existing application registry values in finally. Do not run the old unguarded artifact scripts directly on an account with Arabic Lens installed.

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

- Normal translation overlays have **no expiry timer**. A legacy duration field is not permission to bring expiration back. Temporary error/status notices may expire. The single exception is the user's explicit Quick Translate choice **For a set time** (`overlay.quick_lifetime='timer'`, `quick_seconds`, 0 = automatic reading time); the default remains until the text changes.
- One Arabic size per Watch area or Quick selection (from the area's typical OCR line height, capped by the overlay font setting). Never scale individual lines to fit; a longer translation uses spare width, then wraps at the same size.
- Chat/dialogue speakers ("Name: ", "23:33 Name: ", "Jimmy Jon: ") are kept verbatim; in RTL display time and name are separate LTR isolates with the colon in the Arabic flow. Emotes, emoji and icon glyphs never reach translation.
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
| Quick Translate, **Alt+Q** | Select and release to translate. Esc cancels. The next press dismisses a visible Quick result and a further press starts a new selection. |
| Watch, **Alt+W** | Start according to the selected startup option, or turn Watch off. |
| Add Watch area, **Alt+Shift+W** | Add a selected area to the active Watch workflow. |
| Hide, **Alt+H** | Hide current translations and invalidate pending results. |
| Translator page | User enters English and receives Arabic through the configured Translation setup. |
| Translation setup | Built-in switch beside its title; external-provider setup mutually exclusive. Preserve an already configured provider during upgrades. |
| System tray | Watch on/off, Quick, Repeat, pause, Settings, History and Exit; Settings close does not terminate the utility. |
| Ignore List | English/Arabic reference columns, bilingual search, add/edit/remove/defaults; only complete standalone labels ignored. |
| Block apps | Choose open/installed desktop apps or browse to an executable; normalized executable-path matching. Watch skips blocked apps. Manual Quick remains available. |
| History/cache | Optional searchable history and bounded persistent cache; separate clear actions. |
| Overlay customization | Font, size, colors, opacity, padding, corner radius, width, outline, shadow, placement, fade, fixed preview and defaults. |
| Match source appearance | Optional sampled styling overrides the regular appearance based on background and contrast. |
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

Since 0.1.6 each Watch unit (a drawn area, or a full-screen tile) owns a `TextScene` (`arabic_lens/scene.py`). Every OCR read of changed full-width line strips is reconciled into the scene: a growing/edited line keeps its segment id (overlay updated in place, no fade), entirely different words at the same place are replaced at once, fragments covered by a freshly read block are retired, scrolled lines keep identity by text+column match, and a line OCR merely missed survives only while its pixels are unchanged and not blank. `split_by_history` keeps a line known to be complete separate from text typed beneath it. Translation waits until a segment's text is settled and its pixels match the last read (`due`, `settle_delay`), so partial words are not translated per keystroke and finished lines are not held back by typing elsewhere. After each read a full-resolution re-check of those strips catches final keystrokes below the preview threshold; every 1.5 s an audit re-reads any known line whose pixels changed. Drawn areas bind translations to the window beneath the area (`window_at_rect`), not the focused app. If Windows refuses capture exclusion, the engine masks the app's own overlay rectangles (`own_overlays`) and Replace placement falls back to Below. The former RegionTracker/detector Watch path is retired (class kept only for its own unit tests). `tools/live_scenarios.py OUT all` drives the real app against editor, popup, chat and game-HUD fixtures and writes PASS/FAIL plus `composite.png` (screen with overlays painted on).

Older description of the preview pipeline (still accurate for previews and tiling): each zone keeps its own preview/baselines, OCR image, text blocks, pending work and identifiers. Small previews are polled at about 250 ms under current defaults; `scan_ms` defaults to 500 in settings but the processing loop caps the polling interval at 250 ms. Read the code before equating a settings value to observed cadence.

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

History is optional, defaults to 500 entries, and includes source, Arabic, time and application metadata. The phrase-pack fixture tests cache insertion without overwriting existing translations. The app does not install that fixture or seed application-specific phrases at startup. Existing user cache entries are retained.

Standalone handles may deliberately remain unchanged. Protected abbreviations and reviewed short terminology avoid mistranslations such as treating NFL as an unrelated organization. Completion and Arabic output are not quality scores: slang, names and wrong OCR can still translate incorrectly.

### Overlay and progress rendering

Production rendering uses QTextDocument with RTL layout and Arabic-capable fonts. Default placement is Replace, anchored to source geometry. Replace boxes take the area's line size (`Translation.line_height`), grow only into free space (`row_limit`; never over neighbouring values such as "85 / 100"; inside a detected panel up to its edge; always at least the English width), and single/multi-line boxes never shrink type. Compact labels and multiline paragraphs have different sizing rules; keep bounded expansion and readable minimum sizing. Dense content can still crowd or overlap and requires visual review, not just string assertions.

Capture exclusion prevents the app from OCRing its own translations and progress outlines; where Windows refuses it, the engine masks visible overlays and the toolbox (never excluded since 0.1.16) out of its captures instead. Windows input-transparent/no-focus flags protect normal desktop interaction. Modifier-held controls restore temporary interaction, then return immediately to click-through behavior on release.

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
7. Repeated Alt+Q, including while Watch is running: the first press selects text, the next dismisses the Quick result, and another press starts a new selection. Watch overlays stay visible.
8. Hold/release Ctrl+Alt around mouse presses: only explicit overlay interaction is intercepted.

### Other fixture and performance tools

- `tools/render_document_examples.py`: paragraph/list fixtures with real OCR/model/rendering.
- `tools/render_watch_ui.py`: settings/workflow rendering.
- `tools/benchmark_cpu_translation.py`: uncached inference, process CPU/memory and cache timings.
- `tests/fixtures/screen_phrase_pack.json`: historical test phrases used in cache regression tests.

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
