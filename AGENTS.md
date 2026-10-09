# Arabic Lens continuity

Before changing this application, read [DEVELOPER_README.md](DEVELOPER_README.md) and [README.md](README.md). The developer handoff records the user's behavioral requirements, architecture, active versus retired model code, regression tests, fixture limitations, and staged build/deployment workflow.

Inspect the current code and latest user instructions; documentation is a dated snapshot, not a substitute for verification. Preserve independent Watch zones, source-driven overlay lifetime, click-through input, paragraph/value formatting, whole-entry ignore matching, and user settings/data. Maintain a task checklist for substantive work and report actual test evidence. Update the handoff when architecture, behavior or verification procedures change.

Every completed app update must be delivered to installed users: increment the version, build/test the installer, push source to GitHub, publish a newer stable release with the installer and checksum, and verify the production updater detects it from the previous version. The user explicitly authorizes this workflow. Updating only local dist is not completion.

From 0.1.2 onward, publish and test changed-file update ZIPs plus a full app-file fallback and their checksums. Normal in-app updates must apply files quietly and reopen the app, without an installer wizard. Preserve an exact previous shipped folder until delta creation/testing finishes. Keep legacy compatibility installer assets for pre-0.1.2 clients; do not claim their already installed updater understands file ZIPs.
