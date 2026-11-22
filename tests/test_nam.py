import hashlib
import lzma
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_bundle import fdt, fixture

from mx5_update.bundle import EXPECTED_SIZES, Bundle, BundleError, read_fdt
from mx5_update.mods import nam


def render(nodes):
    def node(path):
        children = [
            node(candidate) for candidate in nodes
            if candidate and candidate.rsplit("/", 1)[0] == path
        ]
        return path.rsplit("/", 1)[-1], nodes[path], children
    return fdt(node(""))


class NamTests(unittest.TestCase):
    def test_structural_reader_accepts_only_expected_rootfs_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stock, modified = root / "stock", root / "modified"
            stock.write_bytes(fixture())
            nodes = read_fdt(stock.read_bytes())
            payload = lzma.compress(b"mods")
            nodes["/images/rootfs"]["data"] = payload
            nodes["/images/rootfs/hash"]["value"] = hashlib.sha1(payload).digest()
            nodes[""]["timestamp"] = bytes(4)
            modified.write_bytes(render(nodes))
            with patch.dict(EXPECTED_SIZES, {key: 4 for key in EXPECTED_SIZES}):
                self.assertEqual(nam.extract_patched_rootfs(stock, modified), b"mods")
            # The ordinary reader must still refuse this modified bundle.
            with self.assertRaisesRegex(BundleError, "SHA-256"):
                Bundle.load(modified)
            for path, key, value in (
                ("", "compatible", b"inmusic,mg01\0"),
                ("/images/splash", "data", b"corrupted"),
                ("/images/rootfs/hash", "value", bytes(20)),
                ("/images/rootfs", "compression", b"gzip\0"),
            ):
                previous = nodes[path][key]
                nodes[path][key] = value
                modified.write_bytes(render(nodes))
                with self.subTest(key=key), self.assertRaises(BundleError):
                    nam.extract_patched_rootfs(stock, modified)
                nodes[path][key] = previous

    def test_launcher_contract_and_instance_count(self):
        for instances in (2, 4):
            script = (
                "# --- NAM mod ---\n"
                "\tsystemd-inhibit --what=handle-power-key env LD_PRELOAD=/usr/Evil/libnam_preload.so"
                " NAM_HOOK_SLOT_GONK_ADDR=0x123"
                + (" NAM_HOOK_SLOT_GONK_V2_ADDR=0x456" if instances == 4 else "")
                + " /usr/Evil/Evil\n\texitCode=$?\n"
            ).encode()
            nam.validate_launcher(script, instances)
            with self.assertRaises(BundleError):
                nam.validate_launcher(script, 4 if instances == 2 else 2)
            with self.assertRaises(BundleError):
                nam.validate_launcher(script.replace(b"env LD_PRELOAD", b"LD_PRELOAD"), instances)
        with self.assertRaises(BundleError):
            nam.validate_launcher(b"stock launcher", 2)

    def test_payload_architecture_and_glibc_compatibility(self):
        data = bytearray(52)
        data[:7] = b"\x7fELF\x01\x01\x01"
        struct.pack_into("<H", data, 16, 3)
        struct.pack_into("<H", data, 18, 40)
        struct.pack_into("<I", data, 36, 0x5000400)
        nam.validate_library(bytes(data) + b"GLIBC_2.31\0")
        for invalid in (
            b"bad", bytes(data) + b"GLIBC_2.33\0",
            bytes(data) + b"GLIBC_2.32.1\0",
            bytes(data[:36]) + bytes(16),
        ):
            with self.assertRaises(BundleError):
                nam.validate_library(invalid)
