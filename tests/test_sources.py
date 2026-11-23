import base64
import unittest

from mx5_update.mods import SOURCES, bridge, nam


class SourceTests(unittest.TestCase):
    def test_pins_are_complete_and_immutable(self):
        self.assertEqual(set(SOURCES), {"bridge", "nam"})
        for name, pin in SOURCES.items():
            with self.subTest(name=name):
                self.assertEqual(set(pin), {"source", "revision", "archive", "hash"})
                self.assertRegex(pin["revision"], r"^[0-9a-f]{40}$")
                self.assertTrue(pin["source"].startswith("https://github.com/"))
                self.assertEqual(
                    pin["archive"],
                    pin["source"].replace("https://github.com/", "https://codeload.github.com/")
                    + "/tar.gz",
                )
                self.assertTrue(pin["hash"].startswith("sha256-"))
                self.assertEqual(len(base64.b64decode(pin["hash"][7:], validate=True)), 32)

    def test_adapters_use_shared_provenance(self):
        for adapter in (bridge, nam):
            with self.subTest(name=adapter.NAME):
                pin = SOURCES[adapter.NAME]
                self.assertEqual(adapter.COMMIT, pin["revision"])
                self.assertEqual(adapter.SOURCE, pin["source"])
