# Arabic Lens installer and release guide

Arabic Lens is distributed as **one file**, `ArabicLens-Setup.exe`. The installer places the complete application in `%LOCALAPPDATA%\Programs\Arabic Lens` for the current Windows user. The `_internal` directory is necessary at runtime but stays inside that program folder; the recipient uses the **Arabic Lens** Start Menu or desktop shortcut. Installation needs no administrator password. Windows Installed Apps includes an uninstaller. User settings, translation cache and history stay separately in `%LOCALAPPDATA%\ArabicLens` across upgrades and uninstall.

The installer source is [installer/ArabicLens.iss](installer/ArabicLens.iss). Its `AppId` is stable and must not be regenerated for future releases. Inno Setup's installer detects the existing installation and replaces its program files in place. The desktop shortcut task is selected by default; a user can deselect it, and upgrades retain the saved choice. This is a per-user install, so every Windows account that wants Arabic Lens installs it for itself.

## Build a release

Every completed app change must reach installed users: increment the version, test and publish the new installer/checksum, push its source, and verify the public feed with the previous installed version. A local dist replacement or source push alone is insufficient. This is the user's standing authorized workflow.

1. Change `APP_VERSION` in `arabic_lens/version.py` to the new numeric version, for example `0.2.0`. Update the two text version fields and both four-number tuples in `assets/version.txt`, plus `assemblyIdentity` in `assets/app.manifest` to `0.2.0.0`. `Build-Installer.ps1` rejects inconsistent source, resource, manifest or frozen EXE versions. The compiled EXE must already contain the new version before the installer is built.
2. Run the appropriate subsystem tests, then the full suite: `.\.venv\Scripts\python.exe -m pytest -q --disable-warnings`. Read [DEVELOPER_README.md](DEVELOPER_README.md) for native capture tests and fixture limitations. Preserve a separate record of any skipped/blocked checks.
3. Build the app in a staged directory to avoid replacing the running developer copy:

   ```powershell
   .\.venv\Scripts\python.exe tools\build.py --distpath artifacts\release-stage\dist --workpath artifacts\release-stage\build
   Copy-Item README.md artifacts\release-stage\dist\ArabicLens\README.md -Force
   Copy-Item THIRD_PARTY.md artifacts\release-stage\dist\ArabicLens\THIRD_PARTY.md -Force
   ```

4. Run the staged executable with `--smoke-test --data-dir` pointing to a new, isolated directory and **wait** for its process to exit. Verify exit code zero and `offline-translation.json` reports success. A normal GUI launch returning control to PowerShell does not prove startup succeeded.
5. Build the single-file installer from that tested stage:

   ```powershell
   .\Build-Installer.ps1 -SourceDir artifacts\release-stage\dist\ArabicLens -OutputDir dist
   ```

   This produces `dist\ArabicLens-Setup.exe` and `dist\ArabicLens-Setup.exe.sha256`. [Inno Setup 6 or 7](https://jrsoftware.org/isdl.php) supplies `ISCC.exe`; it is a build tool and is not sent to users. The build script checks that the source contains the active bundled model, application, README and notices.

6. Test the new installer in an isolated directory with a silent install and `/NOLAUNCH`, then run that installed EXE in `--smoke-test` mode with isolated data. Install over the same test directory again to check the stable upgrade identity; uninstall that test copy and confirm its separate test data survives. Use Windows Installed Apps or the generated `unins000.exe`. Do not test by replacing the developer's active `dist\ArabicLens` folder or deleting `%LOCALAPPDATA%\ArabicLens`. When testing the normal silent relaunch, use a separate `LOCALAPPDATA` environment for the test app and setup, and verify the old process exits while exactly one new process starts. In PowerShell, `Start-Process -Wait` can also wait for the app launched by Setup, making a successful install appear hung; use the returned process object's `.WaitForExit(timeout)` and inspect Setup's exit code and log.

The official Inno Setup compiler is available from [jrsoftware.org](https://jrsoftware.org/isdl.php); its [download verification guide](https://jrsoftware.org/isdl-verify.php) explains publisher signatures. The build machine currently uses signed Inno Setup 6.7.3. The resulting Arabic Lens installer itself is **not code-signed** until the project owner signs it with a trusted signing certificate. Do not claim an unsigned file avoids Windows publisher/SmartScreen prompts.

## Publish an update

The in-app updater checks published releases at `https://github.com/farhanr3001/ocr-translate`. A source-code push alone does **not** update an installed application. Publish a GitHub Release with a strictly newer numeric tag (`v0.2.0`, for example) and attach **exactly named** assets `ArabicLens-Setup.exe` and `ArabicLens-Setup.exe.sha256` from the same tested build. The sidecar contains the installer SHA-256, and the updater verifies the downloaded installer before it starts Setup. The installer version, frozen EXE version and release tag must agree.

The app can check for a new release, tell the user about it and, after their choice, download and launch the verified installer. Its silent path is `/SILENT /NORESTART /CLOSEAPPLICATIONS`; the old app exits, Inno Setup replaces the installed files and the installer opens the updated app minimized. The script uses one `[Run]` launch; avoid adding `/RESTARTAPPLICATIONS`, which could create a second launch if the app later registers with Windows Restart Manager. If Setup fails, keep the existing installation and show a clear recovery path rather than pretending the update succeeded. Test this real sequence after changing updater or installer behavior.

An example release command, after authentication and final verification, is:

```powershell
gh release create v0.2.0 dist\ArabicLens-Setup.exe dist\ArabicLens-Setup.exe.sha256 -R farhanr3001/ocr-translate --title 'Arabic Lens 0.2.0' --notes 'Installer update'
```

Choose a real release note describing the changes. Publish only after the Git source state matches the installer and the install/smoke tests have passed. Keep old release assets available so existing users have a recovery path. Do not publish test screenshots, recorded desktop video, local settings, history or API credentials as release assets.

## Recorded verification (29 September 2026)

The first installer built from the prior 0.1.0 frozen application was **152.1 MiB** with SHA-256 `e20253a6faf8367021fed2bfe1fe00010582b41c72b5eca31709ea05c6f0a190`. An isolated silent installation, same-version reinstall and silent uninstall all returned exit code 0. Installation contained `ArabicLens.exe`, `_internal` model files, notices and an uninstaller. The installed executable's bundled-model smoke test returned `success: true` and produced Arabic. The reinstall retained one uninstall entry. A separate running-app upgrade showed Restart Manager closing the old process, one logged `--minimized` launch, and exactly one replacement process from the test install path. Uninstall removed that EXE and registry entry while isolated translation data remained. Evidence is in `artifacts/installer-test` and `artifacts/installer-build.log`. Repeat this on the final updater-enabled frozen build before publication.

## Final release verification (9 October 2026)

The updater-enabled installer is **152.2 MiB**, SHA-256 `a32ead8efa67d874b6e295d2e5a5b17422c186b4f6f4f68158849889cd58e2ff`, published with its checksum at [v0.1.0](https://github.com/farhanr3001/ocr-translate/releases/tag/v0.1.0). The full regression suite passed 156 tests; two optional video tests skipped because their local fixture was unavailable. The exact final installer passed isolated install, real Arabic translation, running-app reinstall, single automatic reopen, uninstall and user-data preservation. Test evidence is generated locally under `artifacts/installer-final-test`, `artifacts/distribution-final-tests.log` and `artifacts/installer-final-build.log`; these private/generated files are intentionally excluded from Git.

The production updater also checked the real public feed and downloaded/verified this 159,570,169-byte installer. A simulated older installed version found 0.1.0; the current 0.1.0 correctly found no newer release. The developer portable folder and ZIP were replaced with the tested build. Its unpacked payload is approximately 407.6 MiB.

Version 0.1.1 fixes resizing from all edges and corners while retaining the themed title bar. Its installer is 159,556,491 bytes, SHA-256 `52cdd7f5a62d9f7d262bc9b1765b87fbcd3c23c80f6877f6375a58634b6ee84b`. The native regression suite passed 171 tests (two optional video tests skipped); staged translation passed. An isolated upgrade from the actual published 0.1.0 installer to 0.1.1 passed, replaced the running app with exactly one reopened process, and preserved user data through uninstall. Evidence: `artifacts/resize-release-install-test/verification.json`.

Published at [v0.1.1](https://github.com/farhanr3001/ocr-translate/releases/tag/v0.1.1), source commit `2db43ae8dbcdd3aa73fda359a7643fae3c583949`. The production updater detected 0.1.1 from 0.1.0, downloaded all installer bytes and verified its checksum; a 0.1.1 check correctly reported no newer version. Evidence: `artifacts/resize-public-verification/result.json`. The portable folder/ZIP were also replaced with 0.1.1. Automatic checks run 12 seconds after startup and every 24 hours; General's manual check can discover a release while the app is already running.
