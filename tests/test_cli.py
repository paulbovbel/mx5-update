import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from mx5_update.cli import main, parser
from mx5_update.fastboot import RebootError


class CLITests(unittest.TestCase):
    def test_reboot_uncertainty_is_not_reported_as_incomplete_firmware(self):
        errors = io.StringIO()
        with (
            patch("mx5_update.cli.Bundle.load"),
            patch("mx5_update.cli.USB"),
            patch("mx5_update.cli.flash", side_effect=RebootError("Reboot not acknowledged")),
            redirect_stdout(io.StringIO()),
            redirect_stderr(errors),
        ):
            self.assertEqual(main(["flash", "firmware.img", "--serial", "test"]), 1)
        self.assertIn("Firmware writes completed", errors.getvalue())
        self.assertIn("do not automatically retry", errors.getvalue())
        self.assertNotIn("incomplete update", errors.getvalue())

    def test_packaged_firmware_default(self):
        with patch.dict("os.environ", {"MX5_FIRMWARE": "/store/firmware/Update.img"}):
            args = parser().parse_args(["inspect"])
            self.assertEqual(args.bundle, Path("/store/firmware/Update.img"))

    def test_explicit_bundle_overrides_default(self):
        with patch.dict("os.environ", {"MX5_FIRMWARE": "/store/firmware/Update.img"}):
            args = parser().parse_args(["inspect", "other.img"])
            self.assertEqual(args.bundle, Path("other.img"))

    def test_missing_bundle_friendly_error(self):
        with patch.dict("os.environ", {}, clear=True), redirect_stderr(io.StringIO()):
            self.assertEqual(main(["inspect"]), 1)

    def test_no_usb_on_offline_inspect(self):
        with (
            patch("mx5_update.cli.Bundle.load", return_value=None),
            patch("mx5_update.cli.describe", return_value={}),
            patch("mx5_update.cli.USB") as usb,
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(main(["inspect", "firmware.img"]), 0)
            usb.assert_not_called()

    def test_invalid_firmware_refused_before_usb_open(self):
        with (
            patch("mx5_update.cli.Bundle.load", side_effect=ValueError("Invalid firmware")),
            patch("mx5_update.cli.USB") as usb,
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(main(["flash", "firmware.img", "--serial", "test"]), 1)
            usb.assert_not_called()

    def test_flash_needs_no_prompt_or_interactive_terminal(self):
        with (
            patch("mx5_update.cli.Bundle.load") as load,
            patch("mx5_update.cli.sys.stdin.isatty", return_value=False),
            patch("builtins.input", side_effect=AssertionError("Unexpected prompt")),
            patch("mx5_update.cli.USB") as usb,
            patch("mx5_update.cli.flash") as flash,
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(main(["flash", "firmware.img", "--serial", "test"]), 0)
            load.assert_called_once_with(Path("firmware.img"))
            usb.assert_called_once_with(serial="test")
            flash.assert_called_once()
            self.assertTrue(flash.call_args.args[0].allow_write)
            self.assertIs(flash.call_args.args[1], load.return_value)

    def test_flash_still_requires_explicit_serial(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
            parser().parse_args(["flash", "firmware.img"])
        self.assertEqual(exc.exception.code, 2)
