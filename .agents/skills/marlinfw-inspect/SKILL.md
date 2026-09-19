---
name: marlinfw-inspect
description: "Inspect a USB-connected Marlin or Ender 3 printer through Docker. Use when the user asks to discover a stable serial path, identify firmware or capabilities, back up active settings, or read temperatures, position, or endstops without changing printer state."
user-invocable: true
---

# Inspect a Marlin printer

## Security & safety

- Start with `discover`, then use the returned stable `/dev/serial/by-id/...`
  path. Do not guess `/dev/ttyUSB0`.
- `inspect` is read-only. It sends `M115`, `M503`, `M105`, `M114`, and `M119`.
- Do not move axes, heat hardware, start a print, or change settings. Use
  `marlinfw-control` only when the user explicitly requests a specific change.

## When to use

- Identify Marlin firmware and enabled capabilities.
- Save a current settings report before calibration or a firmware change.
- Check temperatures, current position, and endstop state.

## When NOT to use

- Klipper or Moonraker printers. Use a Moonraker-specific tool instead.
- A printer controlled through OctoPrint's network API when no direct serial
  access is intended.

## Usage

Build the local image once from the repository root:

```bash
make build
export MARLINFW_TOOLS_IMAGE=marlinfw-tools:dev
```

Discover stable serial paths:

```bash
.agents/skills/marlinfw-control/scripts/marlinfw-tools.sh discover
```

Inspect one printer:

```bash
.agents/skills/marlinfw-control/scripts/marlinfw-tools.sh inspect \
  --port /dev/serial/by-id/replace-with-printer-path
```

Read [device access](references/device-access.md) before diagnosing an absent
or busy serial device. Read [Marlin reports](references/marlin-reports.md) to
interpret the JSON result. For Ender 3 family identification and control
boundaries, read [Creality Ender 3 safety](../marlinfw-control/references/creality-ender-3.md).

## Completion

Complete the inspection only when the result contains a response or explicit
firmware-level error for every requested read-only command. Report unresolved
serial access or unsupported-command errors. Do not substitute a guessed value.
