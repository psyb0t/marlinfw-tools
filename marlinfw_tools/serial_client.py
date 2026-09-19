"""Small, line-oriented Marlin serial client."""

from __future__ import annotations

import re
import time
from collections.abc import Iterable
from dataclasses import dataclass

import serial

from marlinfw_tools.errors import (
    CommandValidationError,
    PrinterCommandError,
    PrinterTimeoutError,
)

_MAX_COMMAND_LENGTH = 96
_COMMAND_PATTERN = re.compile(r"^[GMT][0-9]+(?:\.[0-9]+)?(?:\s+[A-Z][^\s;]*)*$")
_BLOCKED_COMMANDS = frozenset(
    {
        "G0",
        "G1",
        "G28",
        "G29",
        "G30",
        "G38",
        "M17",
        "M18",
        "M42",
        "M84",
        "M104",
        "M109",
        "M112",
        "M140",
        "M190",
        "M211",
        "M220",
        "M221",
        "M290",
        "M303",
        "M410",
        "M420",
        "M421",
        "M428",
        "M500",
        "M501",
        "M502",
        "M997",
    }
)
_APPROVED_SETTING_COMMANDS = frozenset(
    {"M92", "M201", "M203", "M204", "M205", "M206", "M301", "M304"}
)


@dataclass(frozen=True)
class CommandResult:
    """One acknowledged Marlin command and the response lines it produced."""

    command: str
    response: list[str]


def validate_command(command: str) -> str:
    """Normalize and validate one safe, single-line G-code command."""
    normalized = command.strip().upper()
    if not normalized:
        raise CommandValidationError("command is required")
    if len(normalized) > _MAX_COMMAND_LENGTH:
        raise CommandValidationError(
            f"command exceeds {_MAX_COMMAND_LENGTH} characters"
        )
    if "\n" in normalized or "\r" in normalized or ";" in normalized:
        raise CommandValidationError("command must be one line without comments")
    if not _COMMAND_PATTERN.fullmatch(normalized):
        raise CommandValidationError("command is not a supported G-code shape")
    return normalized


def ensure_writable_command(command: str) -> str:
    """Accept only audited calibration-setting commands from the generic writer."""
    normalized = validate_command(command)
    command_code = normalized.split(maxsplit=1)[0]
    if command_code in _BLOCKED_COMMANDS:
        raise CommandValidationError(f"{command_code} is blocked by this tool")
    if command_code not in _APPROVED_SETTING_COMMANDS:
        raise CommandValidationError(
            f"{command_code} is not an approved setting command"
        )
    return normalized


class MarlinSerialClient:
    """Send one command at a time and wait for Marlin's `ok` acknowledgement."""

    def __init__(self, port: str, baudrate: int, timeout_seconds: float) -> None:
        if not port.startswith("/dev/"):
            raise CommandValidationError("port must be an absolute path under /dev")
        if baudrate <= 0:
            raise CommandValidationError("baudrate must be positive")
        if timeout_seconds <= 0:
            raise CommandValidationError("timeout must be positive")
        self._port = port
        self._baudrate = baudrate
        self._timeout_seconds = timeout_seconds

    def execute_many(self, commands: Iterable[str]) -> list[CommandResult]:
        """Open the port once and execute all requested commands serially."""
        connection = serial.Serial(
            port=None, baudrate=self._baudrate, timeout=0.2, write_timeout=1
        )
        connection.dtr = False
        connection.rts = False
        connection.port = self._port
        try:
            connection.open()
            time.sleep(0.25)
            connection.reset_input_buffer()
            return [self._execute(connection, command) for command in commands]
        except serial.SerialException as error:
            raise PrinterCommandError(f"serial connection failed: {error}") from error
        finally:
            connection.close()

    def _execute(self, connection: serial.Serial, command: str) -> CommandResult:
        normalized = validate_command(command)
        try:
            connection.write(f"{normalized}\n".encode("ascii"))
            connection.flush()
        except serial.SerialException as error:
            raise PrinterCommandError(f"serial write failed: {error}") from error

        deadline = time.monotonic() + self._timeout_seconds
        response: list[str] = []
        while time.monotonic() < deadline:
            try:
                raw_line = connection.readline()
            except serial.SerialException as error:
                raise PrinterCommandError(f"serial read failed: {error}") from error
            if not raw_line:
                continue
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            response.append(line)
            lowered = line.lower()
            if lowered == "ok" or lowered.startswith("ok "):
                return CommandResult(command=normalized, response=response)
            if lowered.startswith("error:"):
                raise PrinterCommandError(f"printer rejected {normalized}: {line}")
        raise PrinterTimeoutError(
            f"printer did not acknowledge {normalized} before timeout"
        )
