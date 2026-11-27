# Changelog

## 0.2.3

- The skill now covers only using the tool on a connected printer: finding the printer, inspecting it, recording telemetry, listing SD files, supervised homing, single setting writes and the first-layer monitor. Its Setup section says the tool must already be installed and points to the README. The Docker and image details are out of the skill, and its frontmatter permissions describe what the commands read and write.
- `references/device-access.md` is removed. The skill keeps its two practical points inline: use a data-capable USB cable with no other program holding the serial port, and the default baud rate is 115200.

## 0.2.2

- The skill now says which commands change the printer. `home`, `send` and `sd-print-monitor` move, heat or reconfigure it, and each needs the user's approval first. The skill lists the exact commands `home` and `sd-print-monitor` send, including the stop-and-cool sequence that ends the SD test, and says `send` accepts only `M92`, `M201`, `M203`, `M204`, `M205`, `M206`, `M301` and `M304`, enforced by the image rather than the wrapper script. The wrapper's usage text and the Ender 3 reference say the same, and the reference no longer claims the tool never sends `G28` or the heater commands.
- The skill frontmatter describes the read-only `/dev` mount that `discover` and the device group lookup use, and the one printer device passed read-write.
- The copy of the skill published to ClawHub names the exact release image by digest instead of `latest`. The repository files keep `latest`.
- The wrapper's usage text no longer shows a doubled backslash after the `home` and `send` lines.
- The pipeline runs lint and the tests through the shared code workflow. A tag's image promotion no longer repeats the vulnerability scan or the Docker Hub description update that the `main` run already did, and the image job states its Docker Hub visibility and description settings.

## 0.2.1

- A release tag no longer rebuilds the image. The default branch builds and tests each commit once and pushes it as `sha-<commit>` as well as `latest`; a tag waits for that run, re-points the release tag at the same image by digest, and cuts the GitHub release from the tag's notes.

## 0.2.0

- The four agent skills (`marlinfw-inspect`, `marlinfw-control`, `marlinfw-home`, `marlinfw-calibration`) are now one skill, `marlinfw-tools`, with the wrapper script and references inside it. It installs from the psyb0t marketplace in Claude Code and Codex, and from ClawHub in OpenClaw.
- The wrapper's default image is `psyb0t/marlinfw-tools:latest` on Docker Hub, which CI now builds and publishes for linux/amd64 and linux/arm64. The previous default, `ghcr.io/psyb0t/marlinfw-tools:latest`, was never published.
- `AGENTS.md` is committed; `CLAUDE.md` and `.claude` are local, gitignored symlinks to it and `.agents`.
- Added the WTFPL license, README badges and an Agent integrations section, and documented image selection, device access, rollback baselines and every guarded operation.

## 0.1.0

- Add Docker-only Marlin inspection, telemetry recording, SD-card listing, supervised homing, and guarded first-layer monitoring.
- Add audited calibration setting writes with explicit persistence confirmation and EEPROM verification.
- Add Ender 3 safety guidance, firmware capability reporting, structured JSONL events, and Docker fixture coverage.
