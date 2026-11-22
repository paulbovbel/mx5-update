import hashlib
import itertools
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_bundle import fixture

from mx5_update import compose
from mx5_update.bundle import EXPECTED_SIZES, BundleError
from mx5_update.mods import bridge, nam


class ComposeTests(unittest.TestCase):
    def test_profiles_and_supported_options(self):
        for name, expected in compose.PROFILES.items():
            self.assertEqual(compose.resolve(name), expected)
        self.assertEqual(compose.resolve("nam-bridge"), (nam, bridge))
        self.assertEqual(len(compose.resolve("nam-bridge", 4)), 2)
        for profile, instances in (
            ("unknown", 2), ("stock", 2), ("bridge", 4), ("nam", 3),
        ):
            with self.subTest(profile=profile), self.assertRaises(BundleError):
                compose.resolve(profile, instances)

    def test_undeclared_overlaps_are_rejected(self):
        with patch.object(bridge, "WRITES", bridge.WRITES | {"/usr/Evil/Evil"}), self.assertRaisesRegex(
            BundleError, "overlap",
        ):
            compose.resolve("nam-bridge")

    def test_missing_tools_are_rejected_before_reading_firmware(self):
        with patch.object(compose.Bundle, "load") as load:
            for profile in ("bridge", "nam", "nam-bridge"):
                with self.assertRaises(BundleError):
                    compose.build(Path("missing"), Path("script"), Path("out"), profile=profile)
            load.assert_not_called()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.stock = self.root / "Update.img"
        data = fixture()
        self.stock.write_bytes(data)
        self.output = self.root / "output"
        self.flasher = self.root / "flasher"
        digest = hashlib.sha256(b"test").hexdigest()
        self.flasher.write_text(
            "#!/bin/bash\nsha256sum --check --strict <<'CHECKSUMS'\n"
            + "".join(f"{digest}  {name}.img\n" for name in EXPECTED_SIZES)
            + "CHECKSUMS\n",
        )
        for context in (
            patch("mx5_update.bundle.KNOWN_SHA256", hashlib.sha256(data).hexdigest()),
            patch.dict(EXPECTED_SIZES, {key: 4 for key in EXPECTED_SIZES}),
            patch("mx5_update.compose.Filesystem.check"),
        ):
            context.start()
            self.addCleanup(context.stop)

    def build(self, profile):
        compose.build(
            self.stock, self.flasher, self.output, profile=profile,
            bridge_source=self.root, nam_cli=self.root / "nam-cli",
        )

    def test_all_profiles_publish_ordered_provenance_and_pinned_flasher(self):
        def apply_nam(context, work):
            self.assertEqual(context.rootfs.read_bytes(), b"test")
            context.rootfs.write_bytes(b"nam!")
            return [{"path": path} for path in nam.WRITES]

        def apply_bridge(context, work):
            self.assertEqual(context.rootfs.read_bytes(), b"nam!" if context.with_nam else b"test")
            context.rootfs.write_bytes(b"brdg")
            paths = bridge.WRITES | ({bridge.NAM_INFO} if context.with_nam else set())
            return [{"path": path} for path in paths]

        for profile, names in compose.PROFILES.items():
            self.output = self.root / profile
            with (
                self.subTest(profile=profile),
                patch.object(nam, "apply", side_effect=apply_nam),
                patch.object(bridge, "apply", side_effect=apply_bridge),
            ):
                self.build(profile)
                manifest = json.loads((self.output / "manifest.json").read_text())
                stages = manifest["mods"]
                self.assertEqual(tuple(stage["name"] for stage in stages), tuple(mod.NAME for mod in names))
                self.assertEqual(manifest["stock_images"]["splash.img"], manifest["images"]["splash.img"])
                for previous, current in itertools.pairwise(stages):
                    self.assertEqual(previous["output_rootfs_sha256"], current["input_rootfs_sha256"])
                script = (self.output / f"mx5-flash-{profile}").read_text()
                self.assertIn(manifest["images"]["rootfs.img"], script)
                with self.assertRaisesRegex(BundleError, "overwrite"):
                    self.build(profile)

    def test_failure_and_undeclared_paths_never_publish_partial_output(self):
        for failure in ("noop", "undeclared", "exception", "splash"):
            def apply(context, work, failure=failure):
                if failure == "exception":
                    raise BundleError("stage failed")
                if failure != "noop":
                    context.rootfs.write_bytes(b"brdg")
                if failure == "splash":
                    (context.rootfs.parent / "splash.img").write_bytes(b"oops")
                return [{"path": path} for path in (
                    {"/unexpected"} if failure == "undeclared" else bridge.WRITES
                )]

            with (
                self.subTest(failure=failure),
                patch.object(bridge, "apply", side_effect=apply),
                self.assertRaises(BundleError),
            ):
                self.build("bridge")
            self.assertFalse(self.output.exists())
            self.assertFalse(list(self.root.glob(".mx5-compose-*")))

    def test_wrong_stock_is_rejected_without_invoking_mods(self):
        self.stock.write_bytes(fixture(compatible=b"inmusic,mg01\0"))
        with patch.object(nam, "apply") as apply, self.assertRaises(BundleError):
            self.build("nam")
        apply.assert_not_called()
        self.assertFalse(self.output.exists())
