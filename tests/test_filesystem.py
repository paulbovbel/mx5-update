import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mx5_update.bundle import BundleError
from mx5_update.filesystem import Filesystem


class FilesystemTests(unittest.TestCase):
    def test_zero_exit_debugfs_error_does_not_bypass_readback(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            fs = Filesystem(work / "rootfs")
            with (
                patch("mx5_update.filesystem.subprocess.run") as command,
                patch.object(fs, "read", return_value=b"unchanged"),
                self.assertRaisesRegex(BundleError, "read-back"),
            ):
                command.return_value = subprocess.CompletedProcess([], 0, b"", b"write failed")
                fs.apply({"/usr/Evil/Scripts/evil": (b"new", 0o100755)}, work)

    def test_record_rejects_wrong_mode_owner_and_missing_file(self):
        fs = Filesystem(Path("fixture"))
        for stat in (
            b"Mode:  0777 User: 0 Group: 0",
            b"Mode:  0755 User: 1000 Group: 0",
            b"Mode:  0755 User: 0 Group: 1000",
        ):
            with (
                self.subTest(stat=stat),
                patch.object(fs, "read", return_value=b"new"),
                patch("mx5_update.filesystem.run", return_value=stat),
                self.assertRaisesRegex(BundleError, "metadata"),
            ):
                fs.record("/fixture", 0o100755)
        with patch.object(fs, "read", return_value=b""), self.assertRaisesRegex(BundleError, "empty"):
            fs.record("/fixture", 0o100755)

    def test_success_checks_each_file_and_records_previous_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            fs = Filesystem(work / "rootfs")
            with (
                patch("mx5_update.filesystem.subprocess.run") as command,
                patch.object(fs, "read", side_effect=[b"old", b"new"]),
                patch.object(fs, "record", return_value={"path": "/fixture", "sha256": "new-hash"}),
            ):
                command.return_value = subprocess.CompletedProcess([], 0, b"", b"")
                records = fs.apply({"/fixture": (b"new", 0o100755)}, work)
            self.assertEqual(len(records[0]["before_sha256"]), 64)
