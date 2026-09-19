# Docker device access

`discover` receives `/dev` as a read-only bind mount solely to list stable
serial symlinks. It does not receive Docker `--device` access and cannot open
or control a printer.

`inspect` and `send` require an explicit path below `/dev/serial/by-id/`. The
wrapper passes that exact path through Docker `--device`; it does not pass the
whole host device tree. Keep the printer connected through a data-capable USB
cable and ensure no other host program has claimed the serial port.

The default baud rate is 115200. Use `M115` from inspection to identify the
firmware before assuming that a setting or report command exists.
