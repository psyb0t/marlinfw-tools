---
name: marlinfw-home
description: "Home all axes on one identified Marlin printer under direct physical supervision, then report position and endstops. Use only when the user explicitly asks to home the printer."
---

# Home a Marlin printer

Use the stable device path returned by `marlinfw-inspect`. Before execution,
confirm in the current turn that no print is active, the bed and toolhead path
are clear, the user is physically present with access to the power switch, and
they approve `G28` on that exact printer.

Run only the dedicated operation:

```bash
.agents/skills/marlinfw-control/scripts/marlinfw-tools.sh home \
  --port /dev/serial/by-id/replace-with-printer-path \
  --apply --confirm-risk --confirm-supervised
```

The operation sends exactly `G28`, `M114`, and `M119`. It does not accept raw
G-code or persist settings. Stop after one cycle. Report the returned position
and endstop state, while making clear that serial data cannot prove the physical
nozzle-to-bed gap.
