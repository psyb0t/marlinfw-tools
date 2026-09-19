---
name: marlinfw-control
description: "Inspect, record, or explicitly control one Marlin printer through the repository's Docker wrapper. Use for SD listings, JSONL telemetry, a supervised first-layer SD test, or one approved calibration setting."
user-invocable: true
---

# Operate one Marlin printer

## Security & safety

- Before changing anything, run `marlinfw-inspect` and retain the fresh `M503`
  output as the rollback baseline.
- Ask the user in the current turn for approval of the exact port, command,
  expected physical effect, and whether it should survive reboot. Do not infer
  permission from an earlier request to inspect or calibrate.
- A change needs both `--apply` and `--confirm-risk`. These flags do not replace
  the direct approval above.
- Persist only after a follow-up inspection proves the temporary change. Ask
  again before using `--save --confirm-persist`, which sends `M500`.
- Never use this wrapper for emergency stop, quickstop, EEPROM load or reset,
  firmware flash, raw pin manipulation, movement, heating, homing, or arbitrary
  G-code. Those commands are blocked. The writer only accepts M92, M201, M203,
  M204, M205, M206, M301, and M304.
- Validate the exact command against the installed firmware. Marlin builds can
  omit individual features and settings.
- `record` and `sd-files` are read-only. `sd-print-monitor` starts and aborts a
  real print, changes heater targets, and needs fresh approval plus physical
  supervision.
- Never infer physical safety from serial telemetry. It cannot judge nozzle
  clearance, extrusion, adhesion, smoke, or collisions.
- On firmware with `Cap:EMERGENCY_PARSER:0`, serial `M524` cannot preempt a
  blocking `M190`, `M109`, or homing command. Keep the printer's physical stop
  or power control within reach.

## When to use

- Apply one calibration or motion/temperature setting the user has named.
- Persist a verified setting after confirming the printer response.
- List exact SD filenames, record telemetry during manual work, or run an
  explicitly approved first-layer test that stops and cools itself.

## When NOT to use

- To guess calibration values, run arbitrary G-code, or alter a printer while a
  print is active.
- To perform firmware flashing, factory reset, or emergency actions.

## Usage

List the exact root-level SD filenames:

```bash
.agents/skills/marlinfw-control/scripts/marlinfw-tools.sh sd-files \
  --port /dev/serial/by-id/replace-with-printer-path
```

Apply a setting for this power cycle only:

```bash
.agents/skills/marlinfw-control/scripts/marlinfw-tools.sh send \
  --port /dev/serial/by-id/replace-with-printer-path \
  --command 'M92 E<measured-value>' \
  --apply --confirm-risk
```

Persist the same verified setting to EEPROM:

```bash
.agents/skills/marlinfw-control/scripts/marlinfw-tools.sh send \
  --port /dev/serial/by-id/replace-with-printer-path \
  --command 'M92 E<measured-value>' \
  --apply --confirm-risk --save --confirm-persist
```

Read [setting writes](references/setting-writes.md) before using `--save`.
Read [Creality Ender 3](references/creality-ender-3.md) before touching an
Ender 3 family printer.

Record JSONL until interrupted:

```bash
.agents/skills/marlinfw-control/scripts/marlinfw-tools.sh record \
  --port /dev/serial/by-id/replace-with-printer-path \
  | tee printer-events.jsonl
```

Run the fixed supervised first-layer sequence:

```bash
.agents/skills/marlinfw-control/scripts/marlinfw-tools.sh sd-print-monitor \
  --port /dev/serial/by-id/replace-with-printer-path \
  --file REPLACE.GCO --observe-seconds 60 \
  --apply --confirm-risk --confirm-supervised \
  | tee first-layer-events.jsonl
```

## Completion

Complete a temporary change only when Marlin acknowledges the command and a
follow-up inspection reports the expected active value. Complete a persistent
change only after a second approval, an acknowledged `M500`, and retained
before-and-after reports. Otherwise report the failure and stop.

Complete an SD monitor run only when first-layer motion was detected and
`M524`, `M104 S0`, `M140 S0`, and `M155 S0` were all acknowledged. Preserve
the JSONL evidence. If cleanup is not confirmed, say exactly which command
failed and require the operator to make the printer safe physically.
