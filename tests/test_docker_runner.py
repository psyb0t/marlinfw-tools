"""Black-box tests for the host Docker wrapper."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path(os.getenv("MARLINFW_TOOLS_RUNNER", ROOT / "marlinfw-tools.sh"))


class DockerRunnerTest(unittest.TestCase):
    def run_runner(
        self,
        *arguments: str,
        environment_overrides: dict[str, str] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], list[str], list[str]]:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            captured_arguments = temporary_path / "docker-arguments.txt"
            captured_metadata_arguments = temporary_path / "docker-metadata-arguments.txt"
            environment = {
                **os.environ,
                "DOCKER_ARGS_FILE": str(captured_arguments),
                "DOCKER_METADATA_ARGS_FILE": str(captured_metadata_arguments),
                "MARLINFW_TOOLS_IMAGE": "marlinfw-tools:fixture",
                **(environment_overrides or {}),
            }
            result = subprocess.run(
                ["bash", str(RUNNER), *arguments],
                capture_output=True,
                check=False,
                env=environment,
                text=True,
                timeout=5,
            )
            captured = (
                captured_arguments.read_text(encoding="utf-8").splitlines()
                if captured_arguments.exists()
                else []
            )
            captured_metadata = (
                captured_metadata_arguments.read_text(encoding="utf-8").splitlines()
                if captured_metadata_arguments.exists()
                else []
            )
            return result, captured, captured_metadata

    def test_discovery_has_read_only_device_listing_without_device_access(self) -> None:
        result, arguments, metadata_arguments = self.run_runner("discover")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("type=bind,source=/dev,target=/host-dev,readonly", arguments)
        self.assertNotIn("--device", arguments)
        self.assertEqual(metadata_arguments, [])
        self.assertIn("--network=none", arguments)
        self.assertIn("--read-only", arguments)
        self.assertEqual(
            arguments[-4:],
            ["marlinfw-tools:fixture", "ports", "--device-root", "/host-dev"],
        )

    def test_inspection_passes_exact_device_and_hardening_options(self) -> None:
        port = "/dev/serial/by-id/usb-fixture"
        result, arguments, metadata_arguments = self.run_runner(
            "inspect", "--port", port, "--baudrate", "250000"
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"{port}:{port}:rwm", arguments)
        self.assertIn("--device", arguments)
        self.assertIn("--cap-drop=ALL", arguments)
        self.assertIn("--security-opt=no-new-privileges:true", arguments)
        self.assertIn("--pids-limit=64", arguments)
        self.assertIn("--memory=128m", arguments)
        self.assertEqual(arguments[arguments.index("--group-add") + 1], "20")
        self.assertIn("type=bind,source=/dev,target=/host-dev,readonly", metadata_arguments)
        self.assertIn("--network=none", metadata_arguments)
        self.assertIn("--read-only", metadata_arguments)
        self.assertIn("--cap-drop=ALL", metadata_arguments)
        self.assertEqual(
            metadata_arguments[-5:],
            [
                "marlinfw-tools:fixture",
                "-Lc",
                "%g",
                "--",
                "/host-dev/serial/by-id/usb-fixture",
            ],
        )
        self.assertEqual(arguments[-5:], ["inspect", "--port", port, "--baudrate", "250000"])

    def test_device_group_is_numeric_and_required_before_docker(self) -> None:
        port = "/dev/serial/by-id/usb-fixture"

        for gid in ("0", "65535"):
            with self.subTest(gid=gid):
                result, arguments, _ = self.run_runner(
                    "inspect",
                    "--port",
                    port,
                    environment_overrides={"STAT_GID": gid},
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    arguments[arguments.index("--group-add") + 1],
                    gid,
                )

        for case, environment in (
            ("empty", {"STAT_GID": ""}),
            ("non-numeric", {"STAT_GID": "dialout"}),
            ("stat-error", {"STAT_EXIT_CODE": "1"}),
        ):
            with self.subTest(case=case):
                result, arguments, _ = self.run_runner(
                    "inspect",
                    "--port",
                    port,
                    environment_overrides=environment,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(arguments, [])

    def test_send_needs_all_confirmation_flags_and_rejects_nonstable_paths_before_docker(
        self,
    ) -> None:
        missing_apply, missing_apply_arguments, _ = self.run_runner(
            "send",
            "--port",
            "/dev/serial/by-id/usb-fixture",
            "--command",
            "M92 E101.00",
        )
        missing_risk, missing_risk_arguments, _ = self.run_runner(
            "send",
            "--port",
            "/dev/serial/by-id/usb-fixture",
            "--command",
            "M92 E101.00",
            "--apply",
        )
        missing_persist, missing_persist_arguments, _ = self.run_runner(
            "send",
            "--port",
            "/dev/serial/by-id/usb-fixture",
            "--command",
            "M92 E101.00",
            "--apply",
            "--confirm-risk",
            "--save",
        )
        bad_port, bad_port_arguments, _ = self.run_runner(
            "inspect",
            "--port",
            "/dev/ttyUSB0",
        )
        traversed_port, traversed_port_arguments, _ = self.run_runner(
            "inspect",
            "--port",
            "/dev/serial/by-id/../ttyUSB0",
        )

        self.assertEqual(missing_apply.returncode, 2)
        self.assertIn("send requires --apply", missing_apply.stderr)
        self.assertEqual(missing_apply_arguments, [])
        self.assertEqual(missing_risk.returncode, 2)
        self.assertIn("send requires --confirm-risk", missing_risk.stderr)
        self.assertEqual(missing_risk_arguments, [])
        self.assertEqual(missing_persist.returncode, 2)
        self.assertIn("--save requires --confirm-persist", missing_persist.stderr)
        self.assertEqual(missing_persist_arguments, [])
        self.assertEqual(bad_port.returncode, 2)
        self.assertIn("stable /dev/serial/by-id", bad_port.stderr)
        self.assertEqual(bad_port_arguments, [])
        self.assertEqual(traversed_port.returncode, 2)
        self.assertIn("stable /dev/serial/by-id", traversed_port.stderr)
        self.assertEqual(traversed_port_arguments, [])

    def test_confirmed_send_passes_only_the_selected_device_and_confirmation_flags(
        self,
    ) -> None:
        port = "/dev/serial/by-id/usb-fixture"
        result, arguments, _ = self.run_runner(
            "send",
            "--port",
            port,
            "--command",
            "M92 E101.00",
            "--apply",
            "--confirm-risk",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(arguments[arguments.index("--device") + 1], f"{port}:{port}:rwm")
        self.assertEqual(
            arguments[-7:],
            [
                "send",
                "--port",
                port,
                "--command",
                "M92 E101.00",
                "--apply",
                "--confirm-risk",
            ],
        )

    def test_home_requires_supervision_and_passes_only_the_selected_device(self) -> None:
        port = "/dev/serial/by-id/usb-fixture"

        for flags, error_text in (
            ((), "home requires --apply"),
            (("--apply",), "home requires --confirm-risk"),
            (
                ("--apply", "--confirm-risk"),
                "home requires --confirm-supervised",
            ),
        ):
            with self.subTest(flags=flags):
                rejected, rejected_arguments, _ = self.run_runner(
                    "home",
                    "--port",
                    port,
                    *flags,
                )

                self.assertEqual(rejected.returncode, 2)
                self.assertIn(error_text, rejected.stderr)
                self.assertEqual(rejected_arguments, [])

        result, arguments, _ = self.run_runner(
            "home",
            "--port",
            port,
            "--apply",
            "--confirm-risk",
            "--confirm-supervised",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            arguments[arguments.index("--device") + 1],
            f"{port}:{port}:rwm",
        )
        self.assertEqual(
            arguments[-6:],
            [
                "home",
                "--port",
                port,
                "--apply",
                "--confirm-risk",
                "--confirm-supervised",
            ],
        )

    def test_record_passes_polling_options_to_the_exact_selected_device(self) -> None:
        port = "/dev/serial/by-id/usb-fixture"
        result, arguments, _ = self.run_runner(
            "record",
            "--port",
            port,
            "--duration",
            "20",
            "--poll-interval",
            "1",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(arguments[arguments.index("--device") + 1], f"{port}:{port}:rwm")
        self.assertEqual(
            arguments[-7:],
            ["record", "--port", port, "--duration", "20", "--poll-interval", "1"],
        )

    def test_sd_print_monitor_requires_supervision_and_passes_exact_file(self) -> None:
        port = "/dev/serial/by-id/usb-fixture"
        for flags, error_text in (
            ((), "requires --apply"),
            (("--apply",), "requires --confirm-risk"),
            (
                ("--apply", "--confirm-risk"),
                "requires --confirm-supervised",
            ),
        ):
            with self.subTest(flags=flags):
                rejected, rejected_arguments, _ = self.run_runner(
                    "sd-print-monitor",
                    "--port",
                    port,
                    "--file",
                    "CE3TEST.GCO",
                    *flags,
                )
                self.assertEqual(rejected.returncode, 2)
                self.assertIn(error_text, rejected.stderr)
                self.assertEqual(rejected_arguments, [])

        result, arguments, _ = self.run_runner(
            "sd-print-monitor",
            "--port",
            port,
            "--file",
            "CE3TEST.GCO",
            "--apply",
            "--confirm-risk",
            "--confirm-supervised",
            "--observe-seconds",
            "20",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(arguments[arguments.index("--device") + 1], f"{port}:{port}:rwm")
        self.assertEqual(
            arguments[-10:],
            [
                "sd-print-monitor",
                "--port",
                port,
                "--file",
                "CE3TEST.GCO",
                "--apply",
                "--confirm-risk",
                "--confirm-supervised",
                "--observe-seconds",
                "20",
            ],
        )


if __name__ == "__main__":
    unittest.main()
