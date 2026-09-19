---
name: marlinfw-control
description: "Apply one verified Marlin setting through Docker and optionally persist it after verification. Use when the user explicitly approves an M92, M201, M203, M204, M205, M206, M301, or M304 command for a selected USB printer."
user-invocable: true
---

# Change one Marlin setting

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

## When to use

- Apply one calibration or motion/temperature setting the user has named.
- Persist a verified setting after confirming the printer response.

## When NOT to use

- To guess calibration values, run arbitrary G-code, or alter a printer while a
  print is active.
- To perform firmware flashing, factory reset, or emergency actions.

## Usage

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

## Completion

Complete a temporary change only when Marlin acknowledges the command and a
follow-up inspection reports the expected active value. Complete a persistent
change only after a second approval, an acknowledged `M500`, and retained
before-and-after reports. Otherwise report the failure and stop.
