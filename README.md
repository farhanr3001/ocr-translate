# Arabic Lens

A Windows tray application that translates visible English into Modern Standard Arabic.
Arabic text appears in a subtle, click-through overlay. Recognition runs locally.
The application uses standard desktop capture and never injects into games, reads game
memory, automates input, or modifies rendering.

For developers and AI assistants, read the [developer handoff](DEVELOPER_README.md)
for the complete architecture, behavioral requirements, test procedures, build/deployment
workflow and known limitations. This is a general desktop translator; games are one use case.

## Start

Download the installer from [GitHub Releases](https://github.com/farhanr3001/ocr-translate/releases/latest).

On another Windows laptop, run `ArabicLens-Setup.exe`, then open **Arabic Lens** from
the Desktop or Start Menu shortcut. The installer contains the translator and all
of its support files. For portable use, extract `ArabicLens-Windows-x64.zip` and
run `ArabicLens.exe` inside its `ArabicLens` folder. Keep the `_internal` folder
beside the executable. `Launch.cmd` is for running a source checkout during development.
Windows 10 2004+ / Windows 11, x64, with English OCR installed, is required.

1. Open Arabic Lens. Translation is already included and works offline.
2. Choose English or العربية using the interface-language dropdown, if desired.
3. Open your game or application and press **Alt+W** to draw Watch areas, or select **Watch fullscreen** first to translate the focused monitor immediately. **Alt+Q** translates a selection once.

No account, API key, internet connection, server or separate model download is needed.
The HPLT English-to-Arabic model is bundled as an approximately 86 MB int8 model
and runs only on the CPU with two processing threads at reduced worker priority;
it is loaded only when uncached text needs translating. A reviewed Dressmaker phrase
pack supplies fast cache hits, but is not the complete game script. Pack updates add
missing entries without overwriting your translations. Translation quality can vary.
No GPU is used for translation. The reviewed pack has 165 entries from eight
official screenshots and 62 trailer frames. It does not contain unseen game text.
Uncached slang, idioms and noisy OCR can still produce literal or incorrect Arabic.

## Install and update

For another laptop, send **`ArabicLens-Setup.exe`**. The installer keeps the app's support
files under `%LOCALAPPDATA%\Programs\Arabic Lens`, adds a Start Menu entry and offers
a Desktop shortcut. The user opens Arabic Lens from the shortcut, without managing an
`_internal` folder. It appears in Windows Installed Apps for normal uninstalling.
The portable ZIP remains useful for development or running without installation.

The installed app can check public GitHub Releases in the background. When a newer
published version is found, it offers **Download update**; accepting downloads a verified
installer, installs it, and reopens Arabic Lens. A tray notification leads to the prompt
when Settings is closed. Checking is optional in General settings, and downloads do not
start without consent. Settings, cache and history stay in `%LOCALAPPDATA%\ArabicLens`
across updates. A code change on the developer's PC reaches another laptop only after
a new installer is published as a GitHub Release. The app itself remains free and
offline for translation; internet is used only for update checks/downloads or an
optional external translation provider.

**Translation → Translation setup** keeps the built-in translator switch beside
its name. Optional providers remain under **Use an external translation service**.
The two switches are mutually exclusive. **Translator** is a separate section
where you can enter English and see Arabic using the selected setup.
Configured providers are preserved on upgrade; unconfigured
older installations switch to built-in translation automatically. External services
may charge for requests. Only recognized text is sent to them, never screenshots.
Built-in translation sends nothing. The window uses a themed title bar with normal
dragging, maximize/restore, minimize and close-to-tray controls, plus resizing from every edge and corner.

| Shortcut | Action |
| --- | --- |
| Alt+W | Toggle Watch Mode |
| Alt+Shift+W | Add another Watch area |
| Alt+Q | Drag to translate; release submits; Esc cancels |
| Alt+E | Translate the previous screen region again |
| Alt+H | Hide current translations and cancel pending results |

All shortcuts can be changed. Click a field, press the combination, then Apply. Windows and
other applications can reserve combinations; Arabic Lens checks availability and retains
the previous bindings on conflict. Win, Ctrl, Alt and Shift are supported with letters,
numbers and function keys. Selection stays within one display per capture.

Closing Settings keeps the app in the tray. Double-click its tray icon to reopen Settings;
right-click for translation actions, pause, history or exit. Save up to 20 regions from
**Ignore List → Saved regions**. Saved rectangles are screen positions, not game-relative
coordinates; recapture them if the game moves or display layout changes.

**Ignore List → Block apps → Add app** lets you choose an open app or an installed
desktop app, search the list, or browse to an executable. Click **Apply changes** to
save. Watch Mode skips capture, OCR and translation for blocked executables, and
clears old overlays when you switch into one. Quick Translate remains available
manually. Matching uses the executable path, regardless of the window title.
App discovery runs only while using the picker; it never launches listed apps.

Scrolling over a settings field does not change its value; use the field, arrows,
slider or dropdown explicitly. **Overlay → Restore overlay defaults** resets the
appearance and behaviour together, updates the preview, and saves on Apply.
Paragraph breaks and list rows are preserved. Quick Capture waits briefly for the selection window to release focus; manual
OCR/translation failures show a short message near the selected area rather than
silently leaving you with no result. Changed or disappeared sources invalidate obsolete
output; changing focus alone does not remove an unchanged translation.

## Watch Mode

The main page provides everyday controls. Timing, sensitivity and diagnostics are
under **Advanced tuning**, with a button to restore recommended defaults. Useful
single words are eligible; common menu labels and OCR noise remain filtered.
Choose **Watch fullscreen**, **Create New**, **Use Previous**, or **Show Presets** beneath Enable Watch.
Watch fullscreen starts immediately on the focused application's monitor. Its
small independent change tiles skip unchanged text without extra OCR work.
Create New hides Settings and lets you draw several screen areas; the small ✓ at
the top starts Watch, and × cancels. Use Previous starts with the latest areas.
Show Presets opens a compact list. Press + to name a preset, optionally bring an
open game or app forward, draw its areas and press ✓ to save. The chosen app is
only a focus aid during setup: presets do not lock translation to its executable.
Starting a preset also makes those areas the new Previous selection. Presets stay
saved until you delete them. **Use entire window** restores full-window Watch.
Areas are screen locations; reselect them after moving or resizing a window.

Each selected area has its own preview and text tracker. Watch checks small previews
every 250 ms and lets changed text settle before OCR. Scrolling in one area does not
recapture or recognize an unchanged area. Translations remain visible until their
source text changes, scrolls out, or the source app closes.

The focused window (or its monitor, if configured) is sampled at a modest interval. A
320×180 preview is checked first. Unchanged previews skip full-size capture, text
detection and OCR; a small check continues at the configured scan interval so new
text can wake processing (the current Watch loop caps that interval at 250 ms). The initial stable frame recognizes the selected area; later
frames recognize only changed crops. Unchanged text blocks keep their translations even
when another part of a fullscreen tile changes. OCR lines are grouped into paragraphs
and separate UI cells before filtering and translation. Normalized text uses a
memory/SQLite cache. Superseded region work is cancelled, and concurrent region work
is bounded. Windows OCR supplies bounding boxes but no confidence, so the app uses
text checks and selective contrast/upscaling retries.

**Show Translation boxes** optionally highlights detected blocks: 25% detected,
50% queued, 75% submitted for translation, and 100% completed. These are processing
stages, not time estimates or a guarantee that every word was detected. An amber
exclamation mark indicates failed/unavailable work. The setting is off by default.
The Ignore List shows English labels beside editable Arabic references; only the
complete English entry controls ignoring, so a sentence containing that word still translates.

Overlays are excluded from capture to prevent recognition feedback, do not take focus,
and let clicks pass through. By default they cover the source English at its position.
Adjacent UI cells keep separate overlays; label/value cells preserve the original values.
Paragraph gaps and individual list rows retain their source positions. Numbers
within paragraphs are included in the Arabic message using exact Western digits,
currency signs, grouping separators and decimal points. Simple label/value UI cells
can translate just the label, leaving a separate displayed game value untouched.
Other placement choices anchor near source text and avoid other overlay rectangles.
Manual captures have no expiry timer: source tracking follows scrolling and removes
the translation when the English disappears. Four appearance presets and a live RTL
preview are included. Developer diagnostics are opt-in. An independent 75 ms
source-window check removes only translations attached to a window that closes,
minimizes, hides, or moves/resizes. Clicking or changing focus alone does not remove
translations. Late results are rejected. These checks use desktop window state only,
without game hooks.

**Follow text when scrolling** tracks bounded source-image patches on changed frames.
Unchanged frames skip full capture and matching. An unchanged patch that scrolls
moves its overlay without more OCR or translation; changed, clipped or unmatched
source text loses its overlay. Tracking is conservative: moving backgrounds,
large horizontal jumps, zooming and font/layout changes may hide a translation
instead of following it. Watch Mode can detect stable new text again.

Enable **Match game appearance** to sample cell backgrounds and use a warm paper style
for Dressmaker dialogue. This setting overrides your regular appearance while enabled.
Hold **Ctrl+Alt** and hover over an overlay to drag it, close just that translation,
collapse/expand it, change its text size with **A− / A+**, or copy its Arabic text using
the copy icon beside the zoom buttons. Controls are compact; the close control is
a 28px circle outside
the upper-right corner. A brief checkmark confirms copying. Release the keys to return
to click-through gameplay. The hold combination is configurable under Overlay.

Public screenshot and trailer-frame checks can be reproduced with
`tools/evaluate_dressmaker.py` and `tools/render_dressmaker_examples.py`. Example images
come from real Windows OCR, reviewed cached translations and the native Qt renderer.
These are screenshot fixture tests, not a claim of testing inside a running game.
`tools/render_document_examples.py` reproduces paragraph/list examples from the
attached fixtures using real Windows OCR, the CPU model and Qt, without displaying
test windows on the desktop.

## Data and privacy

Settings, bounded cache/history, and rotating diagnostic logs live in
`%LOCALAPPDATA%\ArabicLens`. API credentials are protected with Windows DPAPI for the
current user. History is optional (500 entries by default), cache defaults to 5,000 entries,
and the recent memory cache holds 256. Clear either from Settings. Screenshots are never
persisted in normal operation. Logs contain error codes/types, not keys or captured text.
Developer diagnostics show captured text only when explicitly enabled.

## Development

Python 3.10 x64 is the pinned development runtime. Run `Setup.ps1`, then:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe main.py
.\Build.ps1
```

The portable build produces `dist\ArabicLens\ArabicLens.exe` and a ZIP. Keep the executable
with its `_internal` folder. Builds are unsigned. No elevated privileges are required by
the application. A `--data-dir` option isolates development data. `--smoke-test` renders
English/Arabic screenshots locally, tests the bundled CPU translator and exits.

Modules separate capture/active-window monitoring, region detection/tracking, replaceable
OCR and translation providers, cache/history, settings/localization, hotkeys, selection,
overlay management and UI. Tests include real Windows OCR/capture plus deterministic
pipeline and HTTP-provider tests.

## Current limits

Watch detection is heuristic and needs testing/tuning across real games, especially
stylized text, animated backgrounds and HDR. It cannot identify faces or HUD semantics;
positioning avoids source/other overlay rectangles and display edges. Standard GDI capture
can fail or return black in exclusive fullscreen/protected surfaces; use Borderless
Windowed. Capture-excluded overlays require Windows 10 2004+. Mixed-DPI mapping is implemented, but must be validated on real multi-monitor
hardware. This is an initial working build, not a claim of universal game compatibility.

Technical references: [Windows capture exclusion](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowdisplayaffinity),
[PyWinRT](https://pywinrt.readthedocs.io/en/stable/types.html),
[Qt window flags](https://doc.qt.io/qtforpython-6/PySide6/QtCore/Qt.html),
[Azure translation API](https://learn.microsoft.com/en-us/azure/ai-services/translator/text-translation/reference/v3/translate).
