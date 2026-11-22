import subprocess
import unittest
from unittest.mock import patch

from mx5_update.artifact import specialize_flasher
from mx5_update.bundle import BundleError
from mx5_update.filesystem import run
from mx5_update.mods import bridge


class BridgeTests(unittest.TestCase):
    def test_plan_rejects_missing_extra_paths_nam_and_wrong_modes(self):
        plan = {
            name: (b"data", 0o100644 if name.endswith(".qml") else 0o100755)
            for name in bridge.WRITES
        }
        bridge.validate_plan(plan, None)
        for invalid, nam in (
            ({}, None), ({**plan, "/unexpected": (b"bad", 0o100755)}, None),
            (plan, "NAM"), ({**plan, "/usr/Evil/Scripts/evil": (b"x", 0o100777)}, None),
        ):
            with self.subTest(nam=nam), self.assertRaises(BundleError):
                bridge.validate_plan(invalid, nam)
        combined = {**plan, bridge.NAM_INFO: (b"provenance", 0o100644)}
        bridge.validate_plan(combined, "NAM launcher", with_nam=True)
        with self.assertRaises(BundleError):
            bridge.validate_plan(combined, None, with_nam=True)

    def test_specialization_changes_only_pins(self):
        stock = {"rootfs.img": "a" * 64}
        patched = {"rootfs.img": "b" * 64}
        source = "before\n<<'CHECKSUMS'\n" + "a" * 64 + "  rootfs.img\nCHECKSUMS\nafter\n"
        result = specialize_flasher(source, stock, patched)
        self.assertEqual(result, source.replace("a" * 64, "b" * 64))
        for invalid in (source.replace("a" * 64, "c" * 64), source + source):
            with self.assertRaises(BundleError):
                specialize_flasher(invalid, stock, patched)

    def test_failed_tool_raises_explicit_error(self):
        with patch("mx5_update.filesystem.subprocess.run") as command:
            command.return_value = subprocess.CompletedProcess([], 1, b"", b"bad filesystem")
            with self.assertRaisesRegex(BundleError, "bad filesystem"):
                run("e2fsck", "-fn", "fixture")
