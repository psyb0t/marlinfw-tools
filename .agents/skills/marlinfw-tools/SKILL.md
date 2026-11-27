---
name: marlinfw-tools
description: "Inspects and carefully controls a USB-connected Marlin 3D printer (Creality Ender 3 and similar) with the bundled wrapper script: discovers stable serial paths, reads firmware, M503 settings, temperatures, position and endstops, records JSONL telemetry, lists SD card files, homes under supervision, applies one audited calibration setting, and runs a supervised first-layer SD test. Use when the user wants to read, calibrate, home or monitor a Marlin printer over serial."
license: WTFPL
homepage: https://github.com/psyb0t/marlinfw-tools
user-invocable: true
metadata:
  openclaw:
    emoji: "🖨️"
    requires:
      bins:
        - docker
permissions:
  filesystem: "Reads /dev/serial/by-id to list printers and opens the one printer device you name. Writes only the report files you tee the output into."
  shell: "The bundled wrapper scripts/marlinfw-tools.sh only. With the user's approval for each, the commands home, send and sd-print-monitor move, heat or reconfigure the physical printer."
  network: "None. The tool talks only to the printer over USB serial."
---

# Marlin printer tools

## Setup

The tool must already be installed and the printer connected over USB. Installation and details are in the project README at https://github.com/psyb0t/marlinfw-tools. The only connection value you need is the printer's stable `/dev/serial/by-id/...` path, which `discover` returns.

All operations go through `scripts/marlinfw-tools.sh`, relative to this skill's directory.

## Security & safety

- Start with `discover` and use the stable `/dev/serial/by-id/...` path it returns. Never guess `/dev/ttyUSB0` or pass the whole `/dev` tree.
- `discover`, `inspect`, `sd-files` and `record` only read printer state. Use them freely.
- `home`, `send` and `sd-print-monitor` change physical printer state. Before each one, get the user's approval in the current turn for the exact printer path, command and expected physical effect, and whether it should survive a reboot. Never infer permission from an earlier request to inspect or calibrate. The `--apply --confirm-risk` flags are an execution gate, not a substitute for that approval.
- `home` and `sd-print-monitor` also need `--confirm-supervised`: the user must be at the printer with the power switch in reach.
- Serial telemetry cannot judge nozzle clearance, extrusion, adhesion, smoke or collisions. Never report physical safety from it.
- On firmware that reports `Cap:EMERGENCY_PARSER:0`, serial `M524` cannot interrupt a blocking `M190`, `M109` or homing command. The user's physical stop is the only fast stop.
- `send` accepts only `M92`, `M201`, `M203`, `M204`, `M205`, `M206`, `M301` and `M304`. The tool rejects every other command, including motion, heating, leveling, pin control, emergency stop, EEPROM load or reset and firmware update. With `--save` it then adds `M500`.
- The only commands that move or heat the printer are the fixed sequences of `home` (`G28`, `M114`, `M119`) and `sd-print-monitor` (`M20`, `M155 S1`, `M23`, `M24`, then `M114`, `M119` and `M27` polling, and `M524`, `M104 S0`, `M140 S0`, `M155 S0` to stop and cool). Starting the SD file with `M24` makes the printer heat, home and move on its own, which is why that command needs the user at the printer.

## When to use

- Find a printer's serial path and identify its Marlin firmware and capabilities.
- Back up active settings (`M503`) or read temperatures, position and endstops.
- Record temperatures, position, endstops and SD status as JSONL while the user works.
- List the exact SD card filenames Marlin sees.
- Home once under supervision, apply one measured calibration value, or run the supervised first-layer test.

## When NOT to use

- Klipper or Moonraker printers, or a printer that should be driven through OctoPrint's network API.
- Guessing calibration values, running arbitrary G-code, flashing firmware, factory resets, or changing a printer mid-print.

## Read the printer

```bash
scripts/marlinfw-tools.sh discover

scripts/marlinfw-tools.sh inspect \
  --port /dev/serial/by-id/replace-with-printer-path \
  | tee printer-inspect.json
```

`inspect` sends `M115`, `M503`, `M105`, `M114` and `M119`. Keep `printer-inspect.json`: it is the rollback baseline for any later change. See [Marlin reports](references/marlin-reports.md) for what each section means. If the device is missing or busy, check for a data-capable USB cable and make sure no other program has the serial port open. The default baud rate is 115200 (`--baudrate` changes it).

```bash
scripts/marlinfw-tools.sh sd-files --port /dev/serial/by-id/replace-with-printer-path

scripts/marlinfw-tools.sh record --port /dev/serial/by-id/replace-with-printer-path \
  | tee printer-events.jsonl
```

`record` runs until Ctrl+C, or pass `--duration 300` for five minutes. It never starts, pauses or stops a print.

## Home

After approval and with the user at the machine, the bed and toolhead path clear and no print active:

```bash
scripts/marlinfw-tools.sh home --port /dev/serial/by-id/replace-with-printer-path \
  --apply --confirm-risk --confirm-supervised
```

It sends exactly `G28`, `M114` and `M119`. Run it once and report the returned position and endstops.

## Change one setting

1. Run `inspect` and keep the JSON as the baseline.
2. Get the user's physical measurement and the parameter it calibrates. Never derive a value from a guess.
3. Calculate one command and show the exact port, command and expected effect.
4. After approval, apply it for this power cycle only:

   ```bash
   scripts/marlinfw-tools.sh send --port /dev/serial/by-id/replace-with-printer-path \
     --command 'M92 E<measured-value>' --apply --confirm-risk
   ```

5. Run `inspect` again and compare the relevant line.
6. Only after a second, separate approval, persist it. This adds `M500` once the setting is acknowledged:

   ```bash
   scripts/marlinfw-tools.sh send --port /dev/serial/by-id/replace-with-printer-path \
     --command 'M92 E<measured-value>' --apply --confirm-risk --save --confirm-persist
   ```

Read [setting writes](references/setting-writes.md) before any `--save`, and [Creality Ender 3](references/creality-ender-3.md) before changing anything on an Ender 3 family printer.

## Supervised first-layer test

Starts one exact SD file, waits through heating and homing, records the first-layer motion, then aborts the job and turns both heaters off:

```bash
scripts/marlinfw-tools.sh sd-print-monitor --port /dev/serial/by-id/replace-with-printer-path \
  --file REPLACE.GCO --observe-seconds 60 \
  --apply --confirm-risk --confirm-supervised \
  | tee first-layer-events.jsonl
```

Use a filename exactly as `sd-files` reported it.

## Completion

- Inspection: every requested command returned a response or an explicit firmware error. Report unresolved access or unsupported commands; never fill in a guessed value.
- Temporary change: Marlin acknowledged the command and a follow-up `inspect` shows the expected value.
- Persistent change: a second approval, an acknowledged `M500`, and before-and-after reports kept.
- First-layer test: motion was detected and `M524`, `M104 S0`, `M140 S0` and `M155 S0` were all acknowledged. If cleanup is not confirmed, say which command failed and tell the user to make the printer safe by hand.
