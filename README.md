# marlinfw-tools

[![CI](https://github.com/psyb0t/marlinfw-tools/actions/workflows/pipeline.yml/badge.svg?branch=main)](https://github.com/psyb0t/marlinfw-tools/actions/workflows/pipeline.yml)
[![version](https://raw.githubusercontent.com/psyb0t/marlinfw-tools/badges/version.svg)](https://github.com/psyb0t/marlinfw-tools/releases)
[![license](https://raw.githubusercontent.com/psyb0t/marlinfw-tools/badges/license.svg)](LICENSE)
[![Docker Pulls](https://img.shields.io/docker/pulls/psyb0t/marlinfw-tools?style=flat-square)](https://hub.docker.com/r/psyb0t/marlinfw-tools)

Talk straight to a Marlin 3D printer from a locked-down Docker box. Read the
whole damn machine. Change one setting when you mean it. Keep vendor clouds,
mystery desktop blobs, and random host Python shit out of the loop.

The runtime needs Docker and a data-capable USB connection to the printer.
Make is only needed to build or test from source. The image brings its own
serial client. It gets one exact printer device, no network, and no writable
root filesystem. It does not get your whole `/dev` tree just because that was
easier for some lazy script author.

## Get in

The wrapper defaults to `psyb0t/marlinfw-tools:latest` from Docker Hub. To
build and use the local source checkout instead:

```bash
make build
export MARLINFW_TOOLS_IMAGE=marlinfw-tools:dev
```

`MARLINFW_TOOLS_IMAGE` can point at any compatible image tag. The shell
wrapper calls its discovery operation `discover`; it maps that to the image's
read-only `ports` subcommand.

Find the stable serial path without opening or controlling the printer:

```bash
.agents/skills/marlinfw-tools/scripts/marlinfw-tools.sh discover
```

Dump firmware identity, active settings, temperatures, position, and endstops:

```bash
.agents/skills/marlinfw-tools/scripts/marlinfw-tools.sh inspect \
  --port /dev/serial/by-id/replace-with-printer-path \
  | tee printer-inspect.json
```

Keep that JSON report before changing any persistent setting. It is the
rollback baseline, not disposable noise.

Record temperatures, position, endstops, and SD status until `Ctrl+C`:

```bash
.agents/skills/marlinfw-tools/scripts/marlinfw-tools.sh record \
  --port /dev/serial/by-id/replace-with-printer-path \
  | tee printer-events.jsonl
```

Add `--duration 300` for a five-minute recording. Recording is read-only. It
does not start, pause, or stop a print, and `Ctrl+C` only closes the recorder.

List the exact filenames Marlin exposes from the SD card:

```bash
.agents/skills/marlinfw-tools/scripts/marlinfw-tools.sh sd-files \
  --port /dev/serial/by-id/replace-with-printer-path
```

Start one exact SD file, wait through heating and homing, record one minute of
detected first-layer motion, then abort the job and switch both heater targets
off:

```bash
.agents/skills/marlinfw-tools/scripts/marlinfw-tools.sh sd-print-monitor \
  --port /dev/serial/by-id/replace-with-printer-path \
  --file CE3_TE~1.GCO \
  --observe-seconds 60 \
  --apply --confirm-risk --confirm-supervised \
  | tee first-layer-events.jsonl
```

That command changes machine state and requires a person at the printer. The
event stream proves temperatures, coordinates, endstops, SD progress, and the
acknowledged stop/cool commands. It cannot see extrusion quality, nozzle
clearance, adhesion, smoke, or a mechanical crash. Watch the machine and use
its physical controls or power switch if it behaves badly.

The tested Ender-3 firmware reports a residency countdown as `W:<seconds>`
while `M190` and `M109` block the command queue. The monitor waits past the
final hotend `W:0` before polling. Its firmware reports
`Cap:EMERGENCY_PARSER:0`, so `M524` cannot jump ahead of a blocking heat or
homing command. No host script can fix that firmware limitation.

Home all axes once, with somebody physically watching the machine:

```bash
.agents/skills/marlinfw-tools/scripts/marlinfw-tools.sh home \
  --port /dev/serial/by-id/replace-with-printer-path \
  --apply --confirm-risk --confirm-supervised
```

Change one verified setting for the current power cycle:

```bash
.agents/skills/marlinfw-tools/scripts/marlinfw-tools.sh send \
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

Homing has its own fixed command. It needs separate confirmation that somebody
is watching the printer, and it reports position and endstops afterward.

The guarded SD monitor has its own fixed start, watch, abort, and cool
sequence. It never writes EEPROM. A successful summary means all four cleanup
commands were acknowledged. Any missing acknowledgement is an error, not a
fake success.

Docker gets no network, no capabilities, a read-only filesystem, and only the
chosen `/dev/serial/by-id/...` device. Freedom means owning the machine. It does
not mean letting an unattended agent smash the nozzle into the bed.

## Know which bastard you plugged in

Start with [Creality Ender 3 safety](.agents/skills/marlinfw-tools/references/creality-ender-3.md).
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

One [skill](.agents/skills/marlinfw-tools) covers inspection, recording, SD
listing, supervised homing, single calibration writes, and the first-layer
monitor. It carries the same approval rules as this README and runs everything
through the bundled wrapper. It works in any agent that reads
`.agents/skills/` (such as [peen](https://github.com/psyb0t/peen)), and installs
natively in the clients below.

### Claude Code

```bash
claude plugin marketplace add psyb0t/agents
claude plugin install marlinfw-tools@psyb0t
```

### Codex

```bash
codex plugin marketplace add psyb0t/agents
codex plugin add marlinfw-tools@psyb0t
```

### OpenClaw

The skill is published to ClawHub on every release:

```bash
openclaw skills install @psyb0t/marlinfw-tools
```

## License

[WTFPL](LICENSE).
