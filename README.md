# marlinfw-tools

Talk straight to a Marlin 3D printer from a locked-down Docker box. Read the
whole damn machine. Change one setting when you mean it. Keep vendor clouds,
mystery desktop blobs, and random host Python shit out of the loop.

The host needs Docker, Make, and a data-capable USB connection to the printer.
The image brings its own serial client. It gets one exact printer device, no
network, and no writable root filesystem. It does not get your whole `/dev`
tree just because that was easier for some lazy script author.

## Get in

Build the local image:

```bash
make build
export MARLINFW_TOOLS_IMAGE=marlinfw-tools:dev
```

Find the stable serial path without opening or controlling the printer:

```bash
.agents/skills/marlinfw-control/scripts/marlinfw-tools.sh discover
```

Dump firmware identity, active settings, temperatures, position, and endstops:

```bash
.agents/skills/marlinfw-control/scripts/marlinfw-tools.sh inspect \
  --port /dev/serial/by-id/replace-with-printer-path
```

Change one verified setting for the current power cycle:

```bash
.agents/skills/marlinfw-control/scripts/marlinfw-tools.sh send \
  --port /dev/serial/by-id/replace-with-printer-path \
  --command 'M92 E<measured-value>' \
  --apply --confirm-risk
```

Replace `<measured-value>` with a real measurement. Do not cargo-cult some
number from a forum post. Add `--save --confirm-persist` only after another
inspection and a second explicit approval. That sends `M500` after the setting
command and makes the change survive a reboot.

## No yolo button

Reading is free. The inspection path sends only `M115`, `M503`, `M105`, `M114`,
and `M119`.

Writing is deliberately annoying. It needs direct approval for the exact
command plus `--apply --confirm-risk`. Saving needs another inspection, another
approval, and `--confirm-persist`. The generic writer accepts a short list of
reviewed calibration settings. It tells movement, heating, homing, endstop
bypass, EEPROM reset, firmware flashing, raw pin control, emergency commands,
and arbitrary G-code to fuck off.

Docker gets no network, no capabilities, a read-only filesystem, and only the
chosen `/dev/serial/by-id/...` device. Freedom means owning the machine. It does
not mean letting an unattended agent smash the nozzle into the bed.

## Know which bastard you plugged in

Start with [Creality Ender 3 safety](.agents/skills/marlinfw-control/references/creality-ender-3.md).
"Ender 3" is a product family, not a fucking hardware target. Confirm the exact
model, board marking, display, firmware reported by `M115`, and enabled
capabilities before changing anything. This toolbox does not flash firmware.

## Break the fake printer

```bash
make lint
make test
make test-real PORT=/dev/serial/by-id/replace-with-printer-path
```

`make test` uses a pseudo-terminal printer fixture. It never contacts a real
printer. `make test-real` is an explicit read-only inspection command.

## Give the robots tools, not the kingdom

`.agents/` contains the real skills. `.claude` points at the same shit so Claude
Code and Codex get one set of instructions instead of two stale copies.

Available skills:

- `marlinfw-inspect` reads the printer without moving or heating anything.
- `marlinfw-control` changes one approved setting and can save it after proof.
- `marlinfw-calibration` turns actual measurements into reversible changes.
