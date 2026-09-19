"""CLI entry point for a container-scoped Marlin serial device."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from marlinfw_tools.errors import MarlinToolError
from marlinfw_tools.logging_config import configure_logging
from marlinfw_tools.serial_client import (
    CommandResult,
    MarlinSerialClient,
    TelemetrySample,
    ensure_writable_command,
)

logger = logging.getLogger(__name__)

_INSPECTION_COMMANDS = ("M115", "M503", "M105", "M114", "M119")
_HOME_COMMANDS = ("G28", "M114", "M119")
_DEFAULT_POLL_INTERVAL_SECONDS = 1.0
_DEFAULT_FIRST_LAYER_TIMEOUT_SECONDS = 900.0
_DEFAULT_OBSERVE_SECONDS = 60.0
_MAX_RECORD_DURATION_SECONDS = 86_400.0
_MAX_POLL_INTERVAL_SECONDS = 60.0
_MAX_FIRST_LAYER_TIMEOUT_SECONDS = 3_600.0
_MAX_OBSERVE_SECONDS = 300.0


def build_parser() -> argparse.ArgumentParser:
    """Build the public command-line parser."""
    parser = argparse.ArgumentParser(
        description="Read one Marlin printer and change only the shit you approved"
    )
    parser.add_argument("--log-level", default=os.getenv("MARLINFW_TOOLS_LOG_LEVEL", "INFO"))
    parser.add_argument(
        "--log-file",
        default=os.getenv("MARLINFW_TOOLS_LOG_FILE", "/tmp/marlinfw-tools.log"),
    )
    subparsers = parser.add_subparsers(dest="operation", required=True)

    ports = subparsers.add_parser(
        "ports", help="Find stable serial paths without touching a printer"
    )
    ports.add_argument("--device-root", default="/dev")

    inspect = subparsers.add_parser("inspect", help="Dump the standard read-only Marlin report")
    _add_serial_arguments(inspect)

    sd_files = subparsers.add_parser("sd-files", help="List root files on printer media")
    _add_serial_arguments(sd_files)

    record = subparsers.add_parser(
        "record",
        help="Stream printer telemetry until Ctrl+C or an optional duration",
    )
    _add_serial_arguments(record)
    record.add_argument("--duration", type=float, default=0.0)
    record.add_argument(
        "--poll-interval",
        type=float,
        default=_DEFAULT_POLL_INTERVAL_SECONDS,
    )

    home = subparsers.add_parser("home", help="Home all axes under physical supervision")
    _add_serial_arguments(home, default_timeout=60.0)
    home.add_argument("--apply", action="store_true")
    home.add_argument("--confirm-risk", action="store_true")
    home.add_argument("--confirm-supervised", action="store_true")

    send = subparsers.add_parser("send", help="Send one measured and explicitly approved setting")
    _add_serial_arguments(send)
    send.add_argument("--command", required=True)
    send.add_argument("--apply", action="store_true")
    send.add_argument("--confirm-risk", action="store_true")
    send.add_argument("--save", action="store_true")
    send.add_argument("--confirm-persist", action="store_true")

    sd_print_monitor = subparsers.add_parser(
        "sd-print-monitor",
        help="Start one SD print, watch its first layer, then abort and cool",
    )
    _add_serial_arguments(sd_print_monitor)
    sd_print_monitor.add_argument("--file", required=True)
    sd_print_monitor.add_argument(
        "--first-layer-timeout",
        type=float,
        default=_DEFAULT_FIRST_LAYER_TIMEOUT_SECONDS,
    )
    sd_print_monitor.add_argument(
        "--observe-seconds",
        type=float,
        default=_DEFAULT_OBSERVE_SECONDS,
    )
    sd_print_monitor.add_argument(
        "--poll-interval",
        type=float,
        default=_DEFAULT_POLL_INTERVAL_SECONDS,
    )
    sd_print_monitor.add_argument("--apply", action="store_true")
    sd_print_monitor.add_argument("--confirm-risk", action="store_true")
    sd_print_monitor.add_argument("--confirm-supervised", action="store_true")

    return parser


def _add_serial_arguments(
    parser: argparse.ArgumentParser,
    default_timeout: float = 8.0,
) -> None:
    parser.add_argument("--port", required=True)
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--timeout", type=float, default=default_timeout)


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
    return [{"command": result.command, "response": result.response} for result in results]


def emit_telemetry_sample(sample: TelemetrySample) -> None:
    """Write one flush-safe JSONL telemetry event to stdout."""
    print(
        json.dumps(
            {
                "event": "telemetry",
                "time": datetime.now(UTC).isoformat(timespec="milliseconds"),
                "elapsed_seconds": sample.elapsed_seconds,
                "commands": command_results_to_json(sample.commands),
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )


def _validated_poll_interval(value: float) -> float:
    if value <= 0 or value > _MAX_POLL_INTERVAL_SECONDS:
        raise MarlinToolError(
            f"poll interval must be greater than 0 and at most {_MAX_POLL_INTERVAL_SECONDS}"
        )
    return value


def _validated_positive_duration(value: float, maximum: float, name: str) -> float:
    if value <= 0 or value > maximum:
        raise MarlinToolError(f"{name} must be greater than 0 and at most {maximum}")
    return value


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

    if arguments.operation == "sd-files":
        result, files = client.list_sd_files()
        return {
            "command": command_results_to_json([result])[0],
            "files": files,
        }

    if arguments.operation == "record":
        poll_interval = _validated_poll_interval(arguments.poll_interval)
        if arguments.duration < 0 or arguments.duration > _MAX_RECORD_DURATION_SECONDS:
            raise MarlinToolError(
                "duration must be 0 for Ctrl+C recording or between 0 and "
                f"{_MAX_RECORD_DURATION_SECONDS}"
            )
        duration = arguments.duration or None
        logger.info(
            "telemetry recording started",
            extra={"port": arguments.port, "duration_seconds": duration},
        )
        recording = client.record(duration, poll_interval, emit_telemetry_sample)
        logger.info(
            "telemetry recording stopped",
            extra={
                "port": arguments.port,
                "samples": recording.samples,
                "interrupted": recording.interrupted,
            },
        )
        return {
            "event": "summary",
            "operation": "record",
            "samples": recording.samples,
            "interrupted": recording.interrupted,
        }

    if arguments.operation == "home":
        if not arguments.apply:
            raise MarlinToolError("home requires --apply")
        if not arguments.confirm_risk:
            raise MarlinToolError("home requires --confirm-risk after direct user approval")
        if not arguments.confirm_supervised:
            raise MarlinToolError("home requires --confirm-supervised with an operator present")
        logger.warning(
            "user-confirmed supervised homing started",
            extra={"port": arguments.port},
        )
        results = client.execute_many(_HOME_COMMANDS)
        logger.info(
            "user-confirmed supervised homing completed",
            extra={"port": arguments.port},
        )
        return {"commands": command_results_to_json(results), "homed": True}

    if arguments.operation == "sd-print-monitor":
        if not arguments.apply:
            raise MarlinToolError("sd-print-monitor requires --apply")
        if not arguments.confirm_risk:
            raise MarlinToolError(
                "sd-print-monitor requires --confirm-risk after direct user approval"
            )
        if not arguments.confirm_supervised:
            raise MarlinToolError(
                "sd-print-monitor requires --confirm-supervised with an operator present"
            )
        poll_interval = _validated_poll_interval(arguments.poll_interval)
        first_layer_timeout = _validated_positive_duration(
            arguments.first_layer_timeout,
            _MAX_FIRST_LAYER_TIMEOUT_SECONDS,
            "first-layer timeout",
        )
        observe_seconds = _validated_positive_duration(
            arguments.observe_seconds,
            _MAX_OBSERVE_SECONDS,
            "observation duration",
        )
        logger.warning(
            "user-confirmed SD first-layer test started",
            extra={"port": arguments.port, "file": arguments.file},
        )
        monitored = client.monitor_sd_print(
            arguments.file,
            first_layer_timeout,
            observe_seconds,
            poll_interval,
            emit_telemetry_sample,
        )
        logger.info(
            "SD first-layer test stopped and cooled",
            extra={
                "port": arguments.port,
                "file": monitored.filename,
                "samples": monitored.samples,
            },
        )
        return {
            "event": "summary",
            "operation": "sd-print-monitor",
            "file": monitored.filename,
            "samples": monitored.samples,
            "first_layer_detected": monitored.first_layer_detected,
            "interrupted": monitored.interrupted,
            "stopped_and_cooled": monitored.stopped_and_cooled,
        }

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
        logger.error("printer operation failed", extra={"error_type": type(error).__name__})
        print(
            json.dumps({"error": str(error), "type": type(error).__name__}),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
