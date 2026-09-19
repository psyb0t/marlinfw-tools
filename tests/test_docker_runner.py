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
        self, *arguments: str
    ) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            captured_arguments = temporary_path / "docker-arguments.txt"
            environment = {
                **os.environ,
                "DOCKER_ARGS_FILE": str(captured_arguments),
                "MARLINFW_TOOLS_IMAGE": "marlinfw-tools:fixture",
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
            return result, captured

    def test_discovery_has_read_only_device_listing_without_device_access(self) -> None:
        result, arguments = self.run_runner("discover")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("type=bind,source=/dev,target=/host-dev,readonly", arguments)
        self.assertNotIn("--device", arguments)
        self.assertIn("--network=none", arguments)
        self.assertIn("--read-only", arguments)
        self.assertEqual(
            arguments[-4:],
            ["marlinfw-tools:fixture", "ports", "--device-root", "/host-dev"],
        )

    def test_inspection_passes_exact_device_and_hardening_options(self) -> None:
        port = "/dev/serial/by-id/usb-fixture"
        result, arguments = self.run_runner(
            "inspect", "--port", port, "--baudrate", "250000"
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"{port}:{port}:rwm", arguments)
        self.assertIn("--device", arguments)
        self.assertIn("--cap-drop=ALL", arguments)
        self.assertIn("--security-opt=no-new-privileges:true", arguments)
        self.assertIn("--pids-limit=64", arguments)
        self.assertIn("--memory=128m", arguments)
        self.assertEqual(
            arguments[-5:], ["inspect", "--port", port, "--baudrate", "250000"]
        )

    def test_send_needs_all_confirmation_flags_and_rejects_nonstable_paths_before_docker(
        self,
    ) -> None:
        missing_apply, missing_apply_arguments = self.run_runner(
            "send",
            "--port",
            "/dev/serial/by-id/usb-fixture",
            "--command",
            "M92 E101.00",
        )
        missing_risk, missing_risk_arguments = self.run_runner(
            "send",
            "--port",
            "/dev/serial/by-id/usb-fixture",
            "--command",
            "M92 E101.00",
            "--apply",
        )
        missing_persist, missing_persist_arguments = self.run_runner(
            "send",
            "--port",
            "/dev/serial/by-id/usb-fixture",
            "--command",
            "M92 E101.00",
            "--apply",
            "--confirm-risk",
            "--save",
        )
        bad_port, bad_port_arguments = self.run_runner(
            "inspect",
            "--port",
            "/dev/ttyUSB0",
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

    def test_confirmed_send_passes_only_the_selected_device_and_confirmation_flags(
        self,
    ) -> None:
        port = "/dev/serial/by-id/usb-fixture"
        result, arguments = self.run_runner(
            "send",
            "--port",
            port,
            "--command",
            "M92 E101.00",
            "--apply",
            "--confirm-risk",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            arguments[arguments.index("--device") + 1], f"{port}:{port}:rwm"
        )
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


if __name__ == "__main__":
    unittest.main()
