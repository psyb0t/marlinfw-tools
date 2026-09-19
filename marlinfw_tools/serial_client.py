"""Small, line-oriented Marlin serial client."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import serial

from marlinfw_tools.errors import (
    CommandValidationError,
    MarlinToolError,
    PrinterCommandError,
    PrinterTimeoutError,
)

_MAX_COMMAND_LENGTH = 96
_SERIAL_SETTLE_SECONDS = 0.25
_SERIAL_QUIET_SECONDS = 0.25
_SERIAL_SYNC_TIMEOUT_SECONDS = 2.0
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
_TELEMETRY_COMMANDS = ("M105", "M114", "M119", "M27")
_PRINT_TELEMETRY_COMMANDS = ("M114", "M119", "M27")
_STOP_AND_COOL_COMMANDS = ("M524", "M104 S0", "M140 S0", "M155 S0")
_SD_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~-]{0,254}$")
_POSITION_PATTERN = re.compile(
    r"\bX:(?P<x>-?\d+(?:\.\d+)?)\s+"
    r"Y:(?P<y>-?\d+(?:\.\d+)?)\s+"
    r"Z:(?P<z>-?\d+(?:\.\d+)?)"
)
_TEMPERATURE_REPORT_PATTERN = re.compile(
    r"\bT:(?P<hotend>-?\d+(?:\.\d+)?)\s*/(?P<hotend_target>-?\d+(?:\.\d+)?)"
    r".*\bB:(?P<bed>-?\d+(?:\.\d+)?)\s*/(?P<bed_target>-?\d+(?:\.\d+)?)"
)
_HEATER_WAIT_PATTERN = re.compile(r"\bW:(?P<remaining>\?|\d+)(?=\s|$)")
_FIRST_LAYER_MAX_Z = 0.31
_MOTION_POSITION_EPSILON = 0.01
_HEATER_RELEASE_GRACE_SECONDS = 1.1
_PRINT_COMMAND_DRAIN_GRACE_SECONDS = 5.0
_FIRMWARE_FAULT_MARKERS = (
    "heating failed",
    "kill() called",
    "maxtemp",
    "mintemp",
    "printer halted",
    "thermal runaway",
)


@dataclass(frozen=True)
class CommandResult:
    """One acknowledged Marlin command and the response lines it produced."""

    command: str
    response: list[str]


@dataclass(frozen=True)
class TelemetrySample:
    """One ordered telemetry snapshot from a live serial session."""

    elapsed_seconds: float
    commands: list[CommandResult]


@dataclass(frozen=True)
class RecordingResult:
    """Completed or operator-interrupted telemetry recording."""

    samples: int
    interrupted: bool


@dataclass(frozen=True)
class SDPrintMonitorResult:
    """Result of a guarded first-layer SD print test."""

    filename: str
    samples: int
    first_layer_detected: bool
    interrupted: bool
    stopped_and_cooled: bool


def validate_command(command: str) -> str:
    """Normalize and validate one safe, single-line G-code command."""
    normalized = command.strip().upper()
    if not normalized:
        raise CommandValidationError("command is required")
    if len(normalized) > _MAX_COMMAND_LENGTH:
        raise CommandValidationError(f"command exceeds {_MAX_COMMAND_LENGTH} characters")
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
        raise CommandValidationError(f"{command_code} is not an approved setting command")
    return normalized


def validate_sd_filename(filename: str) -> str:
    """Accept one root-level Marlin media filename without command injection."""
    normalized = filename.strip()
    if not normalized:
        raise CommandValidationError("SD filename is required")
    if "/" in normalized or "\\" in normalized or normalized in {".", ".."}:
        raise CommandValidationError("SD filename must be a root-level basename")
    if not _SD_FILENAME_PATTERN.fullmatch(normalized):
        raise CommandValidationError("SD filename contains unsupported characters")
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
        with self._connection() as connection:
            return [self._execute(connection, command) for command in commands]

    def list_sd_files(self) -> tuple[CommandResult, list[str]]:
        """Return the root media listing reported by Marlin."""
        with self._connection() as connection:
            result = self._execute(connection, "M20")
        return result, self._parse_sd_files(result)

    def record(
        self,
        duration_seconds: float | None,
        poll_interval_seconds: float,
        on_sample: Callable[[TelemetrySample], None],
    ) -> RecordingResult:
        """Record polled printer state until timeout or operator interruption."""
        samples = 0
        interrupted = False
        with self._connection() as connection:
            started_at = time.monotonic()
            deadline = started_at + duration_seconds if duration_seconds is not None else None
            try:
                while deadline is None or samples == 0 or time.monotonic() < deadline:
                    sample = self._collect_telemetry(connection, started_at)
                    on_sample(sample)
                    samples += 1
                    if deadline is None:
                        time.sleep(poll_interval_seconds)
                    else:
                        self._wait_for_next_poll(deadline, poll_interval_seconds)
            except KeyboardInterrupt:
                interrupted = True
        return RecordingResult(samples=samples, interrupted=interrupted)

    def monitor_sd_print(
        self,
        filename: str,
        first_layer_timeout_seconds: float,
        observe_seconds: float,
        poll_interval_seconds: float,
        on_sample: Callable[[TelemetrySample], None],
    ) -> SDPrintMonitorResult:
        """Start one exact SD file, observe its first layer, then abort and cool."""
        selected_filename = validate_sd_filename(filename)
        samples = 0
        first_layer_detected = False
        interrupted = False
        stopped_and_cooled = False
        with self._connection() as connection:
            listing = self._execute(connection, "M20")
            files = self._parse_sd_files(listing)
            matching_filename = next(
                (
                    candidate
                    for candidate in files
                    if candidate.casefold() == selected_filename.casefold()
                ),
                None,
            )
            if matching_filename is None:
                raise CommandValidationError(
                    f"SD file is not present in the root listing: {selected_filename}"
                )
            self._execute(connection, "M155 S1")
            self._execute_sd_file_selection(connection, matching_filename)
            started_at = time.monotonic()
            first_layer_deadline = started_at + first_layer_timeout_seconds
            observation_deadline: float | None = None
            operation_error: BaseException | None = None
            try:
                self._execute(connection, "M24")
                samples += self._wait_for_heaters(
                    connection,
                    started_at,
                    first_layer_deadline,
                    on_sample,
                )
                while True:
                    now = time.monotonic()
                    if observation_deadline is not None and now >= observation_deadline:
                        break
                    if not first_layer_detected and now >= first_layer_deadline:
                        raise PrinterTimeoutError(
                            "first-layer motion was not detected before timeout"
                        )
                    active_deadline = observation_deadline or first_layer_deadline
                    sample = self._collect_print_telemetry(
                        connection,
                        started_at,
                        active_deadline + _PRINT_COMMAND_DRAIN_GRACE_SECONDS,
                    )
                    on_sample(sample)
                    samples += 1
                    now = time.monotonic()
                    if self._is_sd_print_inactive(sample):
                        raise PrinterCommandError(
                            "SD print stopped before first-layer monitoring completed"
                        )
                    if not first_layer_detected and self._is_low_z_motion(sample):
                        first_layer_detected = True
                        observation_deadline = now + observe_seconds
                    self._wait_for_next_poll(active_deadline, poll_interval_seconds)
            except KeyboardInterrupt:
                interrupted = True
            except MarlinToolError as error:
                operation_error = error
            cleanup_errors = self._stop_and_cool(connection)
            stopped_and_cooled = not cleanup_errors
            if operation_error is not None:
                if cleanup_errors:
                    raise PrinterCommandError(
                        f"print monitoring failed: {operation_error}; "
                        "stop/cool cleanup was incomplete: "
                        + "; ".join(str(error) for error in cleanup_errors)
                    ) from operation_error
                raise operation_error
            if cleanup_errors:
                raise PrinterCommandError("stop/cool cleanup was incomplete") from cleanup_errors[0]
        return SDPrintMonitorResult(
            filename=matching_filename,
            samples=samples,
            first_layer_detected=first_layer_detected,
            interrupted=interrupted,
            stopped_and_cooled=stopped_and_cooled,
        )

    @contextmanager
    def _connection(self) -> Iterator[serial.Serial]:
        connection = serial.Serial(port=None, baudrate=self._baudrate, timeout=0.2, write_timeout=1)
        connection.dtr = False
        connection.rts = False
        connection.port = self._port
        try:
            connection.open()
            self._synchronize(connection)
            yield connection
        except serial.SerialException as error:
            raise PrinterCommandError(f"serial connection failed: {error}") from error
        finally:
            connection.close()

    def _collect_telemetry(
        self,
        connection: serial.Serial,
        started_at: float,
    ) -> TelemetrySample:
        commands = [self._execute(connection, command) for command in _TELEMETRY_COMMANDS]
        return TelemetrySample(
            elapsed_seconds=round(time.monotonic() - started_at, 3),
            commands=commands,
        )

    def _collect_print_telemetry(
        self,
        connection: serial.Serial,
        started_at: float,
        deadline: float,
    ) -> TelemetrySample:
        commands = [
            self._execute(connection, command, deadline=deadline)
            for command in _PRINT_TELEMETRY_COMMANDS
        ]
        return TelemetrySample(
            elapsed_seconds=round(time.monotonic() - started_at, 3),
            commands=commands,
        )

    def _wait_for_heaters(
        self,
        connection: serial.Serial,
        started_at: float,
        deadline: float,
        on_sample: Callable[[TelemetrySample], None],
    ) -> int:
        samples = 0
        release_candidate_at: float | None = None
        while time.monotonic() < deadline:
            line = self._read_line(connection)
            if line is None:
                if (
                    release_candidate_at is not None
                    and time.monotonic() - release_candidate_at >= _HEATER_RELEASE_GRACE_SECONDS
                ):
                    return samples
                continue
            sample = TelemetrySample(
                elapsed_seconds=round(time.monotonic() - started_at, 3),
                commands=[CommandResult(command="AUTO_REPORT", response=[line])],
            )
            on_sample(sample)
            samples += 1
            self._raise_for_firmware_fault("M155 S1", line)
            match = _TEMPERATURE_REPORT_PATTERN.search(line)
            if match is None:
                continue
            hotend_target = float(match.group("hotend_target"))
            bed_target = float(match.group("bed_target"))
            if hotend_target <= 0 or bed_target <= 0:
                continue
            wait_match = _HEATER_WAIT_PATTERN.search(line)
            if wait_match is None:
                continue
            remaining = wait_match.group("remaining")
            if remaining == "?" or int(remaining) > 0:
                release_candidate_at = None
                continue
            if release_candidate_at is None:
                release_candidate_at = time.monotonic()
        raise PrinterTimeoutError(
            "final hotend residency did not finish before first-layer timeout"
        )

    @staticmethod
    def _read_line(connection: serial.Serial) -> str | None:
        try:
            raw_line = connection.readline()
        except serial.SerialException as error:
            raise PrinterCommandError(f"serial read failed: {error}") from error
        if not raw_line:
            return None
        line = raw_line.decode("utf-8", errors="replace").strip()
        return line or None

    @staticmethod
    def _wait_for_next_poll(deadline: float, poll_interval_seconds: float) -> None:
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            return
        time.sleep(min(poll_interval_seconds, remaining_seconds))

    @staticmethod
    def _parse_sd_files(result: CommandResult) -> list[str]:
        files: list[str] = []
        in_listing = False
        for line in result.response:
            normalized = line.strip()
            if normalized.casefold() == "begin file list":
                in_listing = True
                continue
            if normalized.casefold() == "end file list":
                break
            if not in_listing or not normalized:
                continue
            files.append(normalized.split(maxsplit=1)[0])
        return files

    def _execute_sd_file_selection(
        self,
        connection: serial.Serial,
        filename: str,
    ) -> CommandResult:
        selected_filename = validate_sd_filename(filename)
        return self._exchange(connection, f"M23 {selected_filename}")

    @staticmethod
    def _is_low_z_motion(sample: TelemetrySample) -> bool:
        position_result = next(
            (result for result in sample.commands if result.command == "M114"),
            None,
        )
        if position_result is None:
            return False
        for line in position_result.response:
            match = _POSITION_PATTERN.search(line)
            if match is None:
                continue
            x = float(match.group("x"))
            y = float(match.group("y"))
            z = float(match.group("z"))
            has_xy_motion = abs(x) > _MOTION_POSITION_EPSILON or abs(y) > _MOTION_POSITION_EPSILON
            return has_xy_motion and z <= _FIRST_LAYER_MAX_Z
        return False

    @staticmethod
    def _is_sd_print_inactive(sample: TelemetrySample) -> bool:
        status_result = next(
            (result for result in sample.commands if result.command == "M27"),
            None,
        )
        if status_result is None:
            return False
        return any("not sd printing" in line.casefold() for line in status_result.response)

    def _stop_and_cool(self, connection: serial.Serial) -> list[MarlinToolError]:
        errors: list[MarlinToolError] = []
        for command in _STOP_AND_COOL_COMMANDS:
            try:
                self._execute(connection, command)
            except MarlinToolError as error:
                errors.append(error)
        return errors

    @staticmethod
    def _synchronize(connection: serial.Serial) -> None:
        time.sleep(_SERIAL_SETTLE_SECONDS)
        connection.reset_input_buffer()
        try:
            connection.write(b"\n")
            connection.flush()
        except serial.SerialException as error:
            raise PrinterCommandError(f"serial synchronization failed: {error}") from error

        deadline = time.monotonic() + _SERIAL_SYNC_TIMEOUT_SECONDS
        quiet_deadline = time.monotonic() + _SERIAL_QUIET_SECONDS
        while time.monotonic() < deadline:
            try:
                raw_line = connection.readline()
            except serial.SerialException as error:
                raise PrinterCommandError(f"serial synchronization failed: {error}") from error
            now = time.monotonic()
            if raw_line:
                quiet_deadline = now + _SERIAL_QUIET_SECONDS
                continue
            if now >= quiet_deadline:
                return
        raise PrinterTimeoutError("printer serial startup did not become quiet")

    def _execute(
        self,
        connection: serial.Serial,
        command: str,
        deadline: float | None = None,
    ) -> CommandResult:
        normalized = validate_command(command)
        return self._exchange(connection, normalized, deadline=deadline)

    def _exchange(
        self,
        connection: serial.Serial,
        normalized: str,
        deadline: float | None = None,
    ) -> CommandResult:
        try:
            connection.write(f"{normalized}\n".encode("ascii"))
            connection.flush()
        except serial.SerialException as error:
            raise PrinterCommandError(f"serial write failed: {error}") from error

        response_deadline = deadline or (time.monotonic() + self._timeout_seconds)
        response: list[str] = []
        interrupted = False
        while time.monotonic() < response_deadline:
            try:
                raw_line = connection.readline()
            except KeyboardInterrupt:
                interrupted = True
                continue
            except serial.SerialException as error:
                raise PrinterCommandError(f"serial read failed: {error}") from error
            if not raw_line:
                continue
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            response.append(line)
            lowered = line.lower()
            self._raise_for_firmware_fault(normalized, line)
            if lowered == "ok" or lowered.startswith("ok "):
                if interrupted:
                    raise KeyboardInterrupt
                return CommandResult(command=normalized, response=response)
            if lowered.startswith("error:"):
                raise PrinterCommandError(f"printer rejected {normalized}: {line}")
            if (
                lowered.startswith(("unknown command:", "echo:unknown command:"))
                and normalized in line.upper()
            ):
                raise PrinterCommandError(f"printer rejected {normalized}: {line}")
        raise PrinterTimeoutError(f"printer did not acknowledge {normalized} before timeout")

    @staticmethod
    def _raise_for_firmware_fault(command: str, line: str) -> None:
        lowered = line.lower()
        if any(marker in lowered for marker in _FIRMWARE_FAULT_MARKERS):
            raise PrinterCommandError(f"printer fault while running {command}: {line}")
