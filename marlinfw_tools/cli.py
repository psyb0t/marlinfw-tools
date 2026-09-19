"""CLI entry point for a container-scoped Marlin serial device."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from marlinfw_tools.errors import MarlinToolError
from marlinfw_tools.logging_config import configure_logging
from marlinfw_tools.serial_client import (
    CommandResult,
    MarlinSerialClient,
    ensure_writable_command,
)

logger = logging.getLogger(__name__)

_INSPECTION_COMMANDS = ("M115", "M503", "M105", "M114", "M119")


def build_parser() -> argparse.ArgumentParser:
    """Build the public command-line parser."""
    parser = argparse.ArgumentParser(
        description="Read one Marlin printer and change only the shit you approved"
    )
    parser.add_argument(
        "--log-level", default=os.getenv("MARLINFW_TOOLS_LOG_LEVEL", "INFO")
    )
    parser.add_argument(
        "--log-file",
        default=os.getenv("MARLINFW_TOOLS_LOG_FILE", "/tmp/marlinfw-tools.log"),
    )
    subparsers = parser.add_subparsers(dest="operation", required=True)

    ports = subparsers.add_parser(
        "ports", help="Find stable serial paths without touching a printer"
    )
    ports.add_argument("--device-root", default="/dev")

    inspect = subparsers.add_parser(
        "inspect", help="Dump the standard read-only Marlin report"
    )
    _add_serial_arguments(inspect)

    send = subparsers.add_parser(
        "send", help="Send one measured and explicitly approved setting"
    )
    _add_serial_arguments(send)
    send.add_argument("--command", required=True)
    send.add_argument("--apply", action="store_true")
    send.add_argument("--confirm-risk", action="store_true")
    send.add_argument("--save", action="store_true")
    send.add_argument("--confirm-persist", action="store_true")

    return parser


def _add_serial_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--port", required=True)
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--timeout", type=float, default=8.0)


def list_ports(device_root: str) -> list[dict[str, str]]:
    """List stable `/dev/serial/by-id` entries from a read-only host device mount."""
    device_root_path = Path(device_root).resolve()
    stable_root = device_root_path / "serial" / "by-id"
    if not stable_root.exists():
        return []
    ports: list[dict[str, str]] = []
    for entry in sorted(stable_root.iterdir()):
        if not entry.is_symlink():
            continue
        try:
            resolved = entry.resolve(strict=True)
            relative = resolved.relative_to(device_root_path)
        except (OSError, ValueError):
            logger.warning("ignored serial symlink outside device root")
            continue
        ports.append(
            {
                "path": f"/dev/{relative}",
                "stable_path": f"/dev/serial/by-id/{entry.name}",
            }
        )
    return ports


def command_results_to_json(
    results: Sequence[CommandResult],
) -> list[dict[str, object]]:
    """Convert command results into the stable public JSON shape."""
    return [
        {"command": result.command, "response": result.response} for result in results
    ]


def run(arguments: argparse.Namespace) -> dict[str, object]:
    """Execute the requested operation and return only public result data."""
    if arguments.operation == "ports":
        return {"ports": list_ports(arguments.device_root)}

    client = MarlinSerialClient(arguments.port, arguments.baudrate, arguments.timeout)
    if arguments.operation == "inspect":
        logger.info("inspection started", extra={"port": arguments.port})
        results = client.execute_many(_INSPECTION_COMMANDS)
        logger.info(
            "inspection completed",
            extra={"port": arguments.port, "commands": len(results)},
        )
        return {"commands": command_results_to_json(results)}

    if not arguments.apply:
        raise MarlinToolError("send requires --apply")
    if not arguments.confirm_risk:
        raise MarlinToolError("send requires --confirm-risk after direct user approval")
    if arguments.save and not arguments.confirm_persist:
        raise MarlinToolError(
            "--save requires --confirm-persist after verified follow-up inspection"
        )
    command = ensure_writable_command(arguments.command)
    commands = [command]
    if arguments.save:
        commands.append("M500")
    logger.warning(
        "user-confirmed printer setting started",
        extra={"port": arguments.port, "command": command, "persist": arguments.save},
    )
    results = client.execute_many(commands)
    logger.info(
        "user-confirmed printer setting completed",
        extra={"port": arguments.port, "command": command, "persist": arguments.save},
    )
    return {"commands": command_results_to_json(results), "persisted": arguments.save}


def main(argv: Sequence[str] | None = None) -> int:
    """Run the public CLI and preserve machine-readable output."""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        configure_logging(arguments.log_level, arguments.log_file)
        result = run(arguments)
    except MarlinToolError as error:
        logger.error(
            "printer operation failed", extra={"error_type": type(error).__name__}
        )
        print(
            json.dumps({"error": str(error), "type": type(error).__name__}),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
