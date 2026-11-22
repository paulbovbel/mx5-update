import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from mx5_update.extract import main, parser


class ExtractCLITests(unittest.TestCase):
    def test_extract_delegates_to_bundle_helper(self):
        with (
            patch("mx5_update.extract.extract_firmware") as extract,
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(main(["vendor.zip", "--output", "firmware"]), 0)
            extract.assert_called_once_with(Path("vendor.zip"), Path("firmware"))
            self.assertIn("Validated and extracted", output.getvalue())

    def test_invalid_firmware_has_actionable_error(self):
        with (
            patch("mx5_update.extract.extract_firmware", side_effect=ValueError("Invalid firmware")),
            redirect_stderr(io.StringIO()) as error,
        ):
            self.assertEqual(main(["firmware.img", "--output", "firmware"]), 1)
            self.assertIn("Invalid firmware", error.getvalue())

    def test_interrupt_returns_130(self):
        with (
            patch("mx5_update.extract.extract_firmware", side_effect=KeyboardInterrupt),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(main(["firmware.img", "--output", "firmware"]), 130)

    def test_source_and_output_are_required(self):
        for args in ([], ["vendor.zip"], ["--output", "firmware"]):
            with (
                self.subTest(args=args), redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as exc,
            ):
                parser().parse_args(args)
            self.assertEqual(exc.exception.code, 2)

    def test_help_has_no_subcommands(self):
        self.assertNotIn("{extract,inspect}", parser().format_help())
