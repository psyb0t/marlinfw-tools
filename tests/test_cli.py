"""Black-box CLI tests against a pseudo-terminal Marlin fixture."""

from __future__ import annotations

import json
import os
import pty
import select
import signal
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Self

ROOT = Path(__file__).resolve().parents[1]


class FakeMarlinPrinter:
    """Minimal command responder using a real pseudo-terminal serial boundary."""

    def __init__(self, startup_prefix: bytes = b"") -> None:
        self._master, self._slave = pty.openpty()
        self.port = os.ttyname(self._slave)
        self.commands: list[str] = []
        self.command_times: list[float] = []
        self._startup_prefix = startup_prefix
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
        pending = self._startup_prefix
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
                self.command_times.append(time.monotonic())
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
            "M20": "Begin file list\nCE3_TE~1.GCO 152451\nEnd file list\nok\n",
            "M23 CE3_TE~1.GCO": ("File opened: CE3_TE~1.GCO Size: 152451\nFile selected\nok\n"),
            "M155 S1": "ok\n",
            "M155 S0": "ok\n",
            "M24": (
                "ok\n"
                "T:25.0 /0.0 B:50.0 /50.0 W:0\n"
                "T:180.0 /200.0 B:50.0 /50.0 W:?\n"
                "T:200.0 /200.0 B:50.0 /50.0 W:1\n"
                "T:200.0 /200.0 B:50.0 /50.0 W:0\n"
            ),
            "M524": "ok\n",
            "M104 S0": "ok\n",
            "M140 S0": "ok\n",
            "M27": "SD printing byte 512/152451\nok\n",
            "G28": "ok\n",
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
        self.assertIn("FIRMWARE_NAME:Marlin Fixture", payload["commands"][0]["response"])

    def test_send_requires_apply_before_opening_serial_port(self) -> None:
        result = run_cli("send", "--port", "/dev/does-not-exist", "--command", "M92 E101.00")

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

    def test_home_requires_supervision_and_reports_position_and_endstops(self) -> None:
        with FakeMarlinPrinter() as printer:
            result = run_cli(
                "home",
                "--port",
                printer.port,
                "--apply",
                "--confirm-risk",
                "--confirm-supervised",
                "--timeout",
                "1",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(printer.commands, ["G28", "M114", "M119"])
        self.assertEqual(
            [item["command"] for item in json.loads(result.stdout)["commands"]],
            ["G28", "M114", "M119"],
        )

    def test_sd_files_reports_firmware_file_names(self) -> None:
        with FakeMarlinPrinter() as printer:
            result = run_cli("sd-files", "--port", printer.port, "--timeout", "1")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(printer.commands, ["M20"])
        self.assertEqual(json.loads(result.stdout)["files"], ["CE3_TE~1.GCO"])

    def test_record_streams_jsonl_telemetry_until_duration_expires(self) -> None:
        with FakeMarlinPrinter() as printer:
            result = run_cli(
                "record",
                "--port",
                printer.port,
                "--duration",
                "0.05",
                "--poll-interval",
                "0.01",
                "--timeout",
                "1",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payloads = [json.loads(line) for line in result.stdout.splitlines()]
        telemetry = [payload for payload in payloads if payload["event"] == "telemetry"]
        self.assertGreaterEqual(len(telemetry), 1)
        self.assertEqual(
            [item["command"] for item in telemetry[0]["commands"]],
            ["M105", "M114", "M119", "M27"],
        )
        self.assertEqual(payloads[-1]["event"], "summary")
        self.assertEqual(payloads[-1]["operation"], "record")

    def test_sd_print_monitor_starts_exact_file_and_watches_low_z_motion(self) -> None:
        with FakeMarlinPrinter() as printer:
            original_response = printer._response
            position_reads = 0

            def response(command: str) -> str:
                nonlocal position_reads
                if command == "M114":
                    position_reads += 1
                    if position_reads == 1:
                        time.sleep(0.25)
                        return "X:0.00 Y:0.00 Z:2.00 E:0.00\nok\n"
                    return "X:0.10 Y:20.00 Z:0.30 E:1.00\nok\n"
                return original_response(command)

            printer._response = response
            result = run_cli(
                "sd-print-monitor",
                "--port",
                printer.port,
                "--file",
                "CE3_TE~1.GCO",
                "--first-layer-timeout",
                "2.5",
                "--observe-seconds",
                "0.03",
                "--poll-interval",
                "0.01",
                "--apply",
                "--confirm-risk",
                "--confirm-supervised",
                "--timeout",
                "0.1",
            )
            printer._response = original_response

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            printer.commands[:4],
            ["M20", "M155 S1", "M23 CE3_TE~1.GCO", "M24"],
        )
        m24_index = printer.commands.index("M24")
        first_poll_index = printer.commands.index("M114")
        self.assertGreaterEqual(
            printer.command_times[first_poll_index] - printer.command_times[m24_index],
            1.0,
        )
        self.assertNotIn("M105", printer.commands)
        self.assertEqual(
            printer.commands[-4:],
            ["M524", "M104 S0", "M140 S0", "M155 S0"],
        )
        summary = json.loads(result.stdout.splitlines()[-1])
        telemetry = [json.loads(line) for line in result.stdout.splitlines()[:-1]]
        heater_lines = [
            command["response"][0]
            for event in telemetry
            for command in event["commands"]
            if command["command"] == "AUTO_REPORT"
        ]
        self.assertTrue(any("W:?" in line for line in heater_lines))
        self.assertTrue(any("W:0" in line for line in heater_lines))
        self.assertEqual(summary["event"], "summary")
        self.assertTrue(summary["first_layer_detected"])
        self.assertFalse(summary["interrupted"])
        self.assertTrue(summary["stopped_and_cooled"])
        self.assertEqual(summary["file"], "CE3_TE~1.GCO")

    def test_sd_print_monitor_stops_and_cools_after_thermal_fault(self) -> None:
        with FakeMarlinPrinter() as printer:
            original_response = printer._response

            def response(command: str) -> str:
                if command == "M24":
                    return "ok\nError:Thermal Runaway, system stopped! Heater_ID: 0\n"
                return original_response(command)

            printer._response = response
            result = run_cli(
                "sd-print-monitor",
                "--port",
                printer.port,
                "--file",
                "CE3_TE~1.GCO",
                "--first-layer-timeout",
                "0.2",
                "--apply",
                "--confirm-risk",
                "--confirm-supervised",
                "--timeout",
                "0.2",
            )
            printer._response = original_response

        self.assertEqual(result.returncode, 2)
        self.assertIn("Thermal Runaway", result.stderr)
        self.assertIn("Thermal Runaway", result.stdout)
        self.assertEqual(
            printer.commands[-4:],
            ["M524", "M104 S0", "M140 S0", "M155 S0"],
        )

    def test_sd_print_monitor_preserves_operation_and_cleanup_failures(self) -> None:
        with FakeMarlinPrinter() as printer:
            original_response = printer._response

            def response(command: str) -> str:
                if command == "M24":
                    return "ok\nError:Heating failed, system stopped! Heater_ID: bed\n"
                if command == "M524":
                    return "error:abort unavailable\n"
                return original_response(command)

            printer._response = response
            result = run_cli(
                "sd-print-monitor",
                "--port",
                printer.port,
                "--file",
                "CE3_TE~1.GCO",
                "--first-layer-timeout",
                "0.2",
                "--apply",
                "--confirm-risk",
                "--confirm-supervised",
                "--timeout",
                "0.2",
            )
            printer._response = original_response

        self.assertEqual(result.returncode, 2)
        self.assertIn("Heating failed", result.stderr)
        self.assertIn("abort unavailable", result.stderr)
        self.assertEqual(
            printer.commands[-4:],
            ["M524", "M104 S0", "M140 S0", "M155 S0"],
        )

    def test_sd_print_monitor_times_out_without_final_hotend_residency(self) -> None:
        with FakeMarlinPrinter() as printer:
            original_response = printer._response

            def response(command: str) -> str:
                if command == "M24":
                    return "ok\nT:25.0 /0.0 B:50.0 /50.0 W:0\nT:200.0 /200.0 B:50.0 /50.0 W:?\n"
                return original_response(command)

            printer._response = response
            result = run_cli(
                "sd-print-monitor",
                "--port",
                printer.port,
                "--file",
                "CE3_TE~1.GCO",
                "--first-layer-timeout",
                "0.2",
                "--apply",
                "--confirm-risk",
                "--confirm-supervised",
                "--timeout",
                "0.2",
            )
            printer._response = original_response

        self.assertEqual(result.returncode, 2)
        self.assertIn("final hotend residency", result.stderr)
        self.assertNotIn("M114", printer.commands)
        self.assertEqual(
            printer.commands[-4:],
            ["M524", "M104 S0", "M140 S0", "M155 S0"],
        )

    def test_sd_print_monitor_fails_if_sd_job_ends_before_first_layer(self) -> None:
        with FakeMarlinPrinter() as printer:
            original_response = printer._response

            def response(command: str) -> str:
                if command == "M27":
                    return "Not SD printing\nok\n"
                return original_response(command)

            printer._response = response
            result = run_cli(
                "sd-print-monitor",
                "--port",
                printer.port,
                "--file",
                "CE3_TE~1.GCO",
                "--first-layer-timeout",
                "2.5",
                "--apply",
                "--confirm-risk",
                "--confirm-supervised",
                "--timeout",
                "0.2",
            )
            printer._response = original_response

        self.assertEqual(result.returncode, 2)
        self.assertIn("stopped before first-layer", result.stderr)
        self.assertEqual(
            printer.commands[-4:],
            ["M524", "M104 S0", "M140 S0", "M155 S0"],
        )

    def test_sd_print_monitor_drains_inflight_query_before_interrupt_cleanup(self) -> None:
        with FakeMarlinPrinter() as printer:
            original_response = printer._response

            def response(command: str) -> str:
                if command == "M114":
                    time.sleep(0.5)
                    return "X:0.00 Y:0.00 Z:2.00 E:0.00\nok\n"
                return original_response(command)

            printer._response = response
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "marlinfw_tools.cli",
                    "sd-print-monitor",
                    "--port",
                    printer.port,
                    "--file",
                    "CE3_TE~1.GCO",
                    "--first-layer-timeout",
                    "5",
                    "--apply",
                    "--confirm-risk",
                    "--confirm-supervised",
                    "--timeout",
                    "0.1",
                ],
                cwd=ROOT,
                env={
                    **os.environ,
                    "PYTHONPATH": str(ROOT),
                    "MARLINFW_TOOLS_LOG_FILE": "/tmp/test.log",
                },
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            command_deadline = time.monotonic() + 4
            while "M114" not in printer.commands and time.monotonic() < command_deadline:
                time.sleep(0.01)
            self.assertIn("M114", printer.commands)
            process.send_signal(signal.SIGINT)
            stdout, stderr = process.communicate(timeout=5)
            printer._response = original_response

        self.assertEqual(process.returncode, 0, stderr)
        summary = json.loads(stdout.splitlines()[-1])
        self.assertTrue(summary["interrupted"])
        self.assertFalse(summary["first_layer_detected"])
        self.assertTrue(summary["stopped_and_cooled"])
        self.assertEqual(
            printer.commands[-4:],
            ["M524", "M104 S0", "M140 S0", "M155 S0"],
        )

    def test_sd_print_monitor_rejects_unsafe_or_missing_file_without_starting(self) -> None:
        test_cases = (
            ("../CE3TEST.GCO", "basename"),
            ("MISSING.GCO", "not present"),
        )
        for filename, error_text in test_cases:
            with self.subTest(filename=filename):
                with FakeMarlinPrinter() as printer:
                    result = run_cli(
                        "sd-print-monitor",
                        "--port",
                        printer.port,
                        "--file",
                        filename,
                        "--apply",
                        "--confirm-risk",
                        "--confirm-supervised",
                        "--timeout",
                        "1",
                    )

                self.assertEqual(result.returncode, 2)
                self.assertIn(error_text, result.stderr)
                self.assertNotIn("M24", printer.commands)

    def test_sd_print_monitor_requires_confirmations_before_serial_access(self) -> None:
        test_cases = (
            ((), "requires --apply"),
            (("--apply",), "requires --confirm-risk"),
            (
                ("--apply", "--confirm-risk"),
                "requires --confirm-supervised",
            ),
        )
        for flags, error_text in test_cases:
            with self.subTest(flags=flags):
                result = run_cli(
                    "sd-print-monitor",
                    "--port",
                    "/dev/does-not-exist",
                    "--file",
                    "CE3TEST.GCO",
                    *flags,
                )

                self.assertEqual(result.returncode, 2)
                self.assertIn(error_text, result.stderr)

    def test_home_resynchronizes_before_first_command_after_serial_noise(self) -> None:
        with FakeMarlinPrinter(startup_prefix=b"v?") as printer:
            result = run_cli(
                "home",
                "--port",
                printer.port,
                "--apply",
                "--confirm-risk",
                "--confirm-supervised",
                "--timeout",
                "1",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(printer.commands, ["v?", "G28", "M114", "M119"])

    def test_unknown_command_response_fails_even_when_followed_by_ok(self) -> None:
        with FakeMarlinPrinter() as printer:
            original_response = printer._response
            printer._response = lambda _command: 'echo:Unknown command: "broken M115"\nok\n'
            result = run_cli("inspect", "--port", printer.port, "--timeout", "1")
            printer._response = original_response

        self.assertEqual(result.returncode, 2)
        self.assertIn("PrinterCommandError", result.stderr)
        self.assertIn("Unknown command", result.stderr)

    def test_unrelated_firmware_warning_does_not_abort_homing_readback(self) -> None:
        with FakeMarlinPrinter() as printer:
            original_response = printer._response

            def response(command: str) -> str:
                if command == "G28":
                    return 'echo:Unknown command: "M420 S1"\nok\n'
                return original_response(command)

            printer._response = response
            result = run_cli(
                "home",
                "--port",
                printer.port,
                "--apply",
                "--confirm-risk",
                "--confirm-supervised",
                "--timeout",
                "1",
            )
            printer._response = original_response

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(printer.commands, ["G28", "M114", "M119"])
        self.assertIn("M420 S1", result.stdout)

    def test_home_rejects_each_missing_confirmation_before_serial_access(self) -> None:
        test_cases = (
            ((), "home requires --apply"),
            (("--apply",), "home requires --confirm-risk"),
            (
                ("--apply", "--confirm-risk"),
                "home requires --confirm-supervised",
            ),
        )
        for flags, error_text in test_cases:
            with self.subTest(flags=flags):
                result = run_cli(
                    "home",
                    "--port",
                    "/dev/does-not-exist",
                    *flags,
                )

                self.assertEqual(result.returncode, 2)
                self.assertIn(error_text, result.stderr)

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
            ("G28", "blocked"),
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
