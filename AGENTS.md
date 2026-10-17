# marlinfw-tools

This repository provides Docker-only tools and agent skills for Marlin-based
3D printers. The host needs Docker, Make, and access to the printer's USB
serial device. Project code must not require a host Python installation.

## Source layout

- `.agents/` is the canonical agent integration surface.
- `.claude` and `CLAUDE.md` are local, gitignored symlinks to `.agents` and
  this file for Claude Code. Create them with `ln -s .agents .claude` and
  `ln -s AGENTS.md CLAUDE.md`. Do not create divergent copies.
- `.agents/skills/*/scripts/` invokes the image. It does not contain Marlin
  protocol logic.
- `marlinfw_tools/` owns serial protocol logic.

## Printer safety

- Address devices by a stable path under `/dev/serial/by-id/`. Never guess
  `/dev/ttyUSB0` or pass the whole `/dev` tree to a control command.
- Commands that only inspect state must be the default.
- Read-only inspection needs no approval. Before a state-changing command, an
  agent must obtain the user's current-turn approval for the exact printer,
  command, expected physical effect, and whether it will persist after reboot.
- `send` requires `--apply --confirm-risk`. These flags are an execution gate,
  not a substitute for that direct user approval.
- Persist a setting only after collecting and saving a fresh `M503` report,
  verifying the temporary change, and obtaining a second approval. `--save`
  also requires `--confirm-persist`.
- The generic writer only supports its audited setting families. It blocks
  emergency stop, quickstop, EEPROM load or reset, firmware update, raw pin
  control, motion, heating, homing, and arbitrary G-code. Add a separately
  reviewed, printer-specific tool before expanding that surface.
- Normal tests use a pseudo-terminal printer fixture. They never connect to a
  real serial device.

## Verification

Run `make format`, `make lint`, and the smallest relevant `make test-*` target
after a change. Use `make test` before handing off a complete slice. Build the
image with `make build` and exercise the documented Docker wrapper against the
fixture, not a real printer. A real-printer check is read-only unless the user
has granted the exact command approval above.
