import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from check_firmware_pins import check_pins, read_pins

SCRIPT = Path(__file__).parents[1] / "scripts" / "mx5-flash"


class FlashScriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.firmware = self.root / "firmware"
        self.firmware.mkdir()
        self.sysfs = self.root / "sysfs"
        self.sysfs.mkdir()
        self.device = self.sysfs / "1-1"
        self.device.mkdir()
        for name, value in [("idVendor", "0763"), ("idProduct", "301a"), ("serial", "MX5TEST")]:
            (self.device / name).write_text(value + "\n")
        self.script = self.root / "mx5-flash"
        source = SCRIPT.read_text()
        self.assertEqual(source.count("/sys/bus/usb/devices"), 1)
        # Only the test copy uses fake sysfs; production has no bypass switch.
        self.script.write_text(source.replace("/sys/bus/usb/devices", str(self.sysfs)))
        self.log = self.root / "calls.jsonl"
        binaries = self.root / "bin"
        self.binaries = binaries
        binaries.mkdir()
        fixture = Path(__file__).parent / "fixtures" / "cli_tool.py"
        for name in ("fastboot", "sha256sum"):
            binary = binaries / name
            binary.write_text(f"#!{sys.executable}\n" + fixture.read_text())
            binary.chmod(0o755)
        self.env = dict(os.environ, PATH=f"{binaries}:{os.environ['PATH']}", MX5_TEST_LOG=str(self.log))
        self.env.pop("MX5_FIRMWARE_DIR", None)

    def run_script(self, args=None):
        return subprocess.run(
            [shutil.which("bash"), str(self.script), *(args if args is not None else [
                str(self.firmware),
            ])],
            env=self.env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=10, check=False,
        )

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def device_commands(self):
        return [call for call in self.calls() if call["tool"] == "fastboot" and call["args"] != ["devices"]]

    def test_success_checks_pinned_hashes_then_runs_exact_sequence(self):
        # A local manifest is not trusted by the script.
        (self.firmware / "SHA256SUMS").write_text("untrusted manifest")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertEqual(calls[0]["tool"], "sha256sum")
        self.assertEqual(calls[0]["args"], ["--check", "--strict"])
        self.assertNotIn("untrusted", calls[0]["input"])
        self.assertEqual([line.split()[1] for line in calls[0]["input"].splitlines()], [
            "splash.img", "recoverysplash.img", "rootfs.img",
        ])
        self.assertEqual(calls[1]["args"], ["devices"])
        self.assertEqual([call["args"] for call in self.device_commands()], [
            ["-s", "MX5TEST", "oem", "inmusic-unlock-magic-7de5fbc22b8c524e"],
            ["-s", "MX5TEST", "-S", "0", "--skip-reboot", "flash", "splash", "splash.img"],
            ["-s", "MX5TEST", "-S", "0", "--skip-reboot", "flash", "recoverysplash", "recoverysplash.img"],
            ["-s", "MX5TEST", "erase", "rootfs"],
            ["-s", "MX5TEST", "-S", "0", "--skip-reboot", "flash", "rootfs", "rootfs.img"],
            ["-s", "MX5TEST", "reboot"],
        ])

    def test_failed_checksum_never_invokes_fastboot(self):
        self.env["MX5_TEST_CHECKSUM_STATUS"] = "1"
        self.assertNotEqual(self.run_script().returncode, 0)
        self.assertEqual([call["tool"] for call in self.calls()], ["sha256sum"])

    def use_real_checksums(self):
        # Replace pins only in the private test copy; Fastboot remains a fake.
        source = self.script.read_text()
        for name, pin in read_pins(self.script).items():
            payload = name.encode()
            (self.firmware / name).write_bytes(payload)
            source = source.replace(pin, hashlib.sha256(payload).hexdigest())
        self.script.write_text(source)
        (self.binaries / "sha256sum").unlink()
        self.assertIsNotNone(shutil.which("sha256sum", path=self.env["PATH"]))

    def test_real_checksums_accept_matching_images(self):
        self.use_real_checksums()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.calls()), 7)
        self.assertTrue(all(call["tool"] == "fastboot" for call in self.calls()))

    def test_real_checksums_reject_modified_or_missing_images(self):
        self.use_real_checksums()
        for name in read_pins(self.script):
            image = self.firmware / name
            original = image.read_bytes()
            for modification in ("modified", "missing"):
                with self.subTest(name=name, modification=modification):
                    if modification == "modified":
                        image.write_bytes(b"modified")
                    else:
                        image.unlink()
                    self.assertNotEqual(self.run_script().returncode, 0)
                    self.assertEqual(self.calls(), [])
                    image.write_bytes(original)

    def test_build_pin_check_accepts_only_matching_images(self):
        self.use_real_checksums()
        check_pins(self.script, self.firmware)
        (self.firmware / "rootfs.img").write_bytes(b"modified")
        with self.assertRaisesRegex(ValueError, "rootfs.img"):
            check_pins(self.script, self.firmware)
        self.assertEqual(self.calls(), [])

    def test_failure_at_each_write_stage_stops_before_reboot(self):
        for failure in range(1, 6):
            with self.subTest(failure=failure):
                if self.log.exists():
                    self.log.unlink()
                self.env["MX5_TEST_FAIL_AT"] = str(failure)
                result = self.run_script()
                self.assertNotEqual(result.returncode, 0)
                calls = self.device_commands()
                self.assertEqual(len(calls), failure)
                self.assertFalse(any("reboot" in call["args"] for call in calls))
                self.assertIn("keep the MX5 powered", result.stderr)

    def test_reboot_failure_reports_completed_writes_and_does_not_retry(self):
        self.env["MX5_TEST_FAIL_AT"] = "6"
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("All three writes completed", result.stderr)
        self.assertEqual(len(self.calls()), 8)  # Checksum, discovery, and six device commands.

    def test_wrong_model_or_mode_never_runs_device_commands(self):
        for name, value in [("idVendor", "18d1"), ("idProduct", "401a")]:
            with self.subTest(name=name):
                original = (self.device / name).read_text()
                (self.device / name).write_text(value)
                self.assertNotEqual(self.run_script().returncode, 0)
                (self.device / name).write_text(original)
                self.assertEqual(self.device_commands(), [])

    def test_duplicate_sysfs_serial_never_runs_device_commands(self):
        shutil.copytree(self.device, self.sysfs / "1-2")
        self.assertNotEqual(self.run_script().returncode, 0)
        self.assertEqual(self.device_commands(), [])

    def test_discovers_serial_instead_of_assuming_it(self):
        (self.device / "serial").write_text("AUTODETECTED\n")
        self.env["MX5_TEST_DEVICES"] = "AUTODETECTED\tfastboot\n"
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(all(call["args"][:2] == ["-s", "AUTODETECTED"] for call in self.device_commands()))

    def test_accepts_standard_and_observed_interface_labels(self):
        for label in ("fastboot", " Android Fastboot"):
            with self.subTest(label=label):
                self.env["MX5_TEST_DEVICES"] = f"MX5TEST\t{label}\n"
                result = self.run_script()
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_empty_multiple_or_invalid_device_list_never_runs_device_commands(self):
        for devices in (
            "", "MX5TEST\tfastboot\nOTHER\tfastboot\n", "tcp:host\tfastboot\n",
            "MX5TEST\tadb\n", "MX5TEST\tfastboot extra\n", "MX5TEST\n",
        ):
            with self.subTest(devices=devices):
                self.env["MX5_TEST_DEVICES"] = devices
                self.assertNotEqual(self.run_script().returncode, 0)
                self.assertEqual(self.device_commands(), [])

    def test_failed_device_listing_never_runs_device_commands(self):
        self.env["MX5_TEST_DEVICES_STATUS"] = "1"
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Failed to list", result.stderr)
        self.assertEqual(self.device_commands(), [])

    def test_discovered_serial_must_match_sysfs(self):
        self.env["MX5_TEST_DEVICES"] = "OTHER\tfastboot\n"
        self.assertNotEqual(self.run_script().returncode, 0)
        self.assertEqual(self.device_commands(), [])

    def test_invalid_arguments_do_not_run_any_tools(self):
        for args in [[], ["EXTRA", str(self.firmware)]]:
            with self.subTest(args=args):
                self.assertEqual(self.run_script(args).returncode, 2)
                self.assertEqual(self.calls(), [])

    def test_help_is_offline(self):
        self.assertEqual(self.run_script(["--help"]).returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_nix_default_firmware_directory(self):
        self.env["MX5_FIRMWARE_DIR"] = str(self.firmware)
        self.assertEqual(self.run_script([]).returncode, 0)
