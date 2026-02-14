# emuinput

Host-side Python package and on-device helper scaffolding for robust touch and keyboard-style input injection in Android emulators.

Current focus:
- MuMu first (primary)
- BlueStacks later (secondary)

This repository scaffold defines:
- Python package modules for ADB orchestration, controller API, protocol framing, easing profiles, and key typing
- Native helper daemon (`uinputd`) using `/dev/uinput` for touch + key event injection
- Script entry points for Android builds and local dev testing
