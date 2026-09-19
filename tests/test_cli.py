"""Black-box CLI tests against a pseudo-terminal Marlin fixture."""

from __future__ import annotations

import json
import os
import pty
import select
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Self

ROOT = Path(__file__).resolve().parents[1]


class FakeMarlinPrinter:
    """Minimal command responder using a real pseudo-terminal serial boundary."""

    def __init__(self) -> None:
        self._master, self._slave = pty.openpty()
        self.port = os.ttyname(self._slave)
        self.commands: list[str] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join(timeout=1)
        os.close(self._slave)
        os.close(self._master)

    def _serve(self) -> None:
        pending = b""
        while not self._stop.is_set():
            readable, _, _ = select.select([self._master], [], [], 0.05)
            if not readable:
                continue
            try:
                pending += os.read(self._master, 1024)
            except OSError:
                if self._stop.is_set():
                    return
                raise
            while b"\n" in pending:
                raw_command, pending = pending.split(b"\n", 1)
                command = raw_command.decode("ascii").strip()
                if not command:
                    continue
                self.commands.append(command)
                response = self._response(command)
                try:
                    os.write(self._master, response.encode("utf-8"))
                except OSError:
                    if self._stop.is_set():
                        return
                    raise

    @staticmethod
    def _response(command: str) -> str:
        responses = {
            "M115": "FIRMWARE_NAME:Marlin Fixture\nok\n",
            "M503": "echo: M92 X80.00 Y80.00 Z400.00 E93.00\nok\n",
            "M105": "ok T:200.0 /200.0 B:60.0 /60.0\n",
            "M114": "X:0.00 Y:0.00 Z:0.00 E:0.00\nok\n",
            "M119": "x_min: open\nok\n",
            "M92 E101.00": "ok\n",
            "M500": "echo:Settings Stored\nok\n",
        }
        return responses.get(command, "error:unsupported command\n")


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "MARLINFW_TOOLS_LOG_FILE": "/tmp/test.log",
    }
    return subprocess.run(
        [sys.executable, "-m", "marlinfw_tools.cli", *arguments],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=5,
    )


class MarlinCLITest(unittest.TestCase):
    def test_ports_reports_only_resolved_devices_inside_device_root(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            device_root = Path(temporary_directory)
            stable_root = device_root / "serial" / "by-id"
            stable_root.mkdir(parents=True)
            (device_root / "ttyUSB0").touch()
            (stable_root / "inside").symlink_to("../../ttyUSB0")
            (stable_root / "outside").symlink_to("/etc/passwd")

            result = run_cli("ports", "--device-root", str(device_root))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "ports": [
                    {
                        "path": "/dev/ttyUSB0",
                        "stable_path": "/dev/serial/by-id/inside",
                    }
                ]
            },
        )

    def test_invalid_log_level_returns_json_error_without_a_traceback(self) -> None:
        result = run_cli("--log-level", "loud", "ports")

        self.assertEqual(result.returncode, 2)
        self.assertIn("ConfigurationError", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_inspect_reports_all_read_only_commands_in_order(self) -> None:
        with FakeMarlinPrinter() as printer:
            result = run_cli("inspect", "--port", printer.port, "--timeout", "1")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            [item["command"] for item in payload["commands"]],
            ["M115", "M503", "M105", "M114", "M119"],
        )
        self.assertEqual(printer.commands, ["M115", "M503", "M105", "M114", "M119"])
        self.assertIn(
            "FIRMWARE_NAME:Marlin Fixture", payload["commands"][0]["response"]
        )

    def test_send_requires_apply_before_opening_serial_port(self) -> None:
        result = run_cli(
            "send", "--port", "/dev/does-not-exist", "--command", "M92 E101.00"
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("send requires --apply", result.stderr)

    def test_send_applies_then_persists_only_when_requested(self) -> None:
        with FakeMarlinPrinter() as printer:
            result = run_cli(
                "send",
                "--port",
                printer.port,
                "--command",
                "M92 E101.00",
                "--apply",
                "--confirm-risk",
                "--save",
                "--confirm-persist",
                "--timeout",
                "1",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(printer.commands, ["M92 E101.00", "M500"])
        self.assertTrue(json.loads(result.stdout)["persisted"])

    def test_blocked_or_multiline_commands_cannot_reach_printer(self) -> None:
        test_cases = (
            ("M502", "blocked"),
            ("M92 E101.00\nM500", "one line"),
            ("M92 E101.00;M500", "one line"),
        )
        for command, error_text in test_cases:
            with self.subTest(command=command):
                result = run_cli(
                    "send",
                    "--port",
                    "/dev/does-not-exist",
                    "--command",
                    command,
                    "--apply",
                    "--confirm-risk",
                )

                self.assertEqual(result.returncode, 2)
                self.assertIn(error_text, result.stderr)

    def test_timeout_is_reported_when_printer_never_acknowledges(self) -> None:
        with FakeMarlinPrinter() as printer:
            original_response = printer._response
            printer._response = lambda _command: ""
            result = run_cli("inspect", "--port", printer.port, "--timeout", "0.1")
            printer._response = original_response

        self.assertEqual(result.returncode, 2)
        self.assertIn("PrinterTimeoutError", result.stderr)

    def test_send_needs_current_risk_and_persistence_confirmations_before_serial_access(
        self,
    ) -> None:
        test_cases = (
            (("--apply",), "send requires --confirm-risk"),
            (
                ("--apply", "--confirm-risk", "--save"),
                "--save requires --confirm-persist",
            ),
        )
        for flags, error_text in test_cases:
            with self.subTest(flags=flags):
                result = run_cli(
                    "send",
                    "--port",
                    "/dev/does-not-exist",
                    "--command",
                    "M92 E101.00",
                    *flags,
                )

                self.assertEqual(result.returncode, 2)
                self.assertIn(error_text, result.stderr)

    def test_non_audited_state_changes_cannot_reach_printer(self) -> None:
        test_cases = (
            ("G1 X1", "blocked"),
            ("M104 S200", "blocked"),
            ("M211 S0", "blocked"),
            ("M501", "blocked"),
            ("M220 S200", "blocked"),
        )
        for command, error_text in test_cases:
            with self.subTest(command=command):
                result = run_cli(
                    "send",
                    "--port",
                    "/dev/does-not-exist",
                    "--command",
                    command,
                    "--apply",
                    "--confirm-risk",
                )

                self.assertEqual(result.returncode, 2)
                self.assertIn(error_text, result.stderr)


if __name__ == "__main__":
    unittest.main()
