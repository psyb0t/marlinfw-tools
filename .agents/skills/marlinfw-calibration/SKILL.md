---
name: marlinfw-calibration
description: "Plan and verify a measured Marlin calibration with an M503 baseline, one explicit setting command, follow-up inspection, and optional EEPROM save. Use when the user asks to calibrate Ender 3 motion, extrusion, PID, or home offsets."
user-invocable: true
---

# Calibrate a Marlin printer

## Security & safety

- Collect and save a fresh `M503` baseline before measuring or changing a
  setting.
- Never derive a calibration value from a guess. Ask for the measured result,
  calculate the single intended change, and show the exact port, command, and
  expected physical effect before `--apply --confirm-risk`.
- Verify the reported setting after the change. Use `--save --confirm-persist`
  only after that verification and a second explicit user approval.

## Calibration sequence

1. Inspect the printer and retain the `M503` response.
2. Obtain the user's physical measurement and the parameter being calibrated.
3. Calculate and display one G-code setting command.
4. Ask for current-turn approval, then apply it without `--save` using
   `--apply --confirm-risk`.
5. Inspect again and compare the relevant response line.
6. Persist with `--save --confirm-persist` only when the user explicitly
   approves the verified result.

For command families and persistence details, read
[setting writes](../marlinfw-control/references/setting-writes.md).
For Ender 3 family checks, read
[Creality Ender 3](../marlinfw-control/references/creality-ender-3.md).

## Completion

Complete calibration only when the input measurement, calculation, exact
command, Marlin acknowledgement, and follow-up reported value agree. EEPROM
persistence remains optional and requires a separate explicit approval.
