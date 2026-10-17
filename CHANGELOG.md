# Changelog

## 0.2.0

- The four agent skills (`marlinfw-inspect`, `marlinfw-control`, `marlinfw-home`, `marlinfw-calibration`) are now one skill, `marlinfw-tools`, with the wrapper script and references inside it. It installs from the psyb0t marketplace in Claude Code and Codex, and from ClawHub in OpenClaw.
- The wrapper's default image is `psyb0t/marlinfw-tools:latest` on Docker Hub, which CI now builds and publishes for linux/amd64 and linux/arm64. The previous default, `ghcr.io/psyb0t/marlinfw-tools:latest`, was never published.
- `AGENTS.md` is committed; `CLAUDE.md` and `.claude` are local, gitignored symlinks to it and `.agents`.
- Added the WTFPL license, README badges and an Agent integrations section, and documented image selection, device access, rollback baselines and every guarded operation.

## 0.1.0

- Add Docker-only Marlin inspection, telemetry recording, SD-card listing, supervised homing, and guarded first-layer monitoring.
- Add audited calibration setting writes with explicit persistence confirmation and EEPROM verification.
- Add Ender 3 safety guidance, firmware capability reporting, structured JSONL events, and Docker fixture coverage.
