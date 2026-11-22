import hashlib
import lzma
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from mx5_update.bundle import (
    EXPECTED_SIZES,
    Bundle,
    BundleError,
    decompress,
    extract_container,
    read_fdt,
)


def fdt(nodes):
    names = bytearray()
    offsets = {}
    tree = bytearray()

    def word(*values):
        tree.extend(struct.pack(">" + "I" * len(values), *values))

    def aligned(data):
        tree.extend(data)
        tree.extend(bytes((-len(tree)) % 4))

    def node(name, properties, children):
        word(1)
        aligned(name.encode() + b"\0")
        for key, value in properties.items():
            if key not in offsets:
                offsets[key] = len(names)
                names.extend(key.encode() + b"\0")
            word(3, len(value), offsets[key])
            aligned(value)
        for child in children:
            node(*child)
        word(2)

    node(*nodes)
    word(9)
    return (
        struct.pack(">10I", 0xD00DFEED, 56 + len(tree) + len(names),
                    56, 56 + len(tree), 40, 17, 16, 0, len(names), len(tree))
        + bytes(16) + tree + names
    )


def fixture(*, compatible=b"inmusic,hg04\0", bad_hash=False, extra=False):
    images = []
    for name in EXPECTED_SIZES:
        payload = lzma.compress(b"test")
        checksum = hashlib.sha1(payload).digest()
        images.append((
            name,
            {"partition": name.encode() + b"\0", "compression": b"xz\0", "data": payload},
            [("hash", {"algo": b"sha1\0", "value": bytes(20) if bad_hash else checksum}, [])],
        ))
    if extra:
        images.append(("uboot", {}, []))
    return fdt(("", {
        "compatible": compatible, "description": b"Test image\0",
        "inmusic,devices": bytes.fromhex("0763301a"),
    }, [("images", {}, images)]))


class BundleTests(unittest.TestCase):
    def load(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Update.img"
            path.write_bytes(data)
            with (
                patch("mx5_update.bundle.KNOWN_SHA256", hashlib.sha256(data).hexdigest()),
                patch.dict(EXPECTED_SIZES, {key: 4 for key in EXPECTED_SIZES}),
            ):
                return Bundle.load(path)

    def test_valid_bundle(self):
        bundle = self.load(fixture())
        self.assertEqual([item.partition for item in bundle.images], list(EXPECTED_SIZES))

    def test_reject_other_model(self):
        with self.assertRaises(BundleError):
            self.load(fixture(compatible=b"inmusic,other\0"))

    def test_reject_bad_image_hash(self):
        with self.assertRaises(BundleError):
            self.load(fixture(bad_hash=True))

    def test_reject_extra_partitions(self):
        with self.assertRaises(BundleError):
            self.load(fixture(extra=True))

    def test_reject_unpinned_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Update.img"
            path.write_bytes(fixture())
            with self.assertRaisesRegex(BundleError, "SHA-256"):
                Bundle.load(path)

    def test_fdt_reject_truncation(self):
        data = fixture()
        for length in [0, 39, 55, len(data) - 1]:
            with self.subTest(length=length), self.assertRaises(BundleError):
                read_fdt(data[:length])

    def test_fdt_reject_out_of_bounds_sections(self):
        data = bytearray(fixture())
        struct.pack_into(">I", data, 12, len(data) + 100)
        with self.assertRaises(BundleError):
            read_fdt(bytes(data))

    def test_fdt_reject_duplicate_properties(self):
        # Replace the name offset of compatible with description's name offset.
        data = bytearray(fixture())
        struct.pack_into(">I", data, 72, len("compatible") + 1)
        with self.assertRaises(BundleError):
            read_fdt(bytes(data))

    def test_fdt_reject_unknown_token(self):
        data = bytearray(fixture())
        struct.pack_into(">I", data, 56, 100)
        with self.assertRaises(BundleError):
            read_fdt(bytes(data))

    def test_bounded_xz(self):
        data = lzma.compress(b"x" * 100)
        self.assertEqual(decompress(data, 100), b"x" * 100)
        for bad, limit in [(data, 99), (data[:-1], 100), (data + data, 200), (b"bad", 100)]:
            with self.subTest(limit=limit), self.assertRaises(BundleError):
                decompress(bad, limit)

    def test_extract_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Update.img"
            target.write_bytes(b"existing")
            with self.assertRaises(BundleError):
                extract_container(Path("missing"), target)
            self.assertEqual(target.read_bytes(), b"existing")

    def test_extract_reject_unrecognized_exe(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "vendor.exe"
            source.write_bytes(b"untrusted")
            target = Path(directory) / "Update.img"
            with self.assertRaisesRegex(BundleError, "Unrecognized updater"):
                extract_container(source, target)
            self.assertFalse(target.exists())

    def test_extract_reject_ambiguous_zip(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "vendor.zip"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("one.exe", b"one")
                archive.writestr("two.exe", b"two")
            with self.assertRaises(BundleError):
                extract_container(source, Path(directory) / "Update.img")
