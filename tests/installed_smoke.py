"""Exercise a pip installation outside the source tree, using only synthetic firmware."""

import hashlib
import importlib.util
import json
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from test_bundle import fixture

import mx5_update
from mx5_update.bundle import EXPECTED_SIZES


def main():
    repository = Path(__file__).resolve().parents[1]
    package = Path(mx5_update.__file__).resolve()
    if package.is_relative_to(repository):
        raise RuntimeError(f"Smoke test imported source rather than installed package: {package}")
    for removed in ("fastboot", "usb", "cli"):
        if importlib.util.find_spec(f"mx5_update.{removed}") is not None:
            raise RuntimeError(f"Removed module is still installed: {removed}")
    commands = {name: shutil.which(name) for name in ("mx5-extract-firmware", "mx5-flash")}
    if not all(commands.values()):
        raise RuntimeError("Both installed commands must be on PATH")
    data = fixture()
    original_directory = Path.cwd()
    try:
        with tempfile.TemporaryDirectory(prefix="mx5-installed-") as temp:
            os.chdir(temp)
            for executable in commands.values():
                subprocess.run([executable, "--help"], check=True)
            source = Path(temp) / "synthetic.img"
            source.write_bytes(data)
            output = Path(temp) / "firmware"
            # Patch only this test process, never the installed files. Execute the
            # actual pip-installed entry script so production has no test switches.
            with (
                patch("mx5_update.bundle.KNOWN_SHA256", hashlib.sha256(data).hexdigest()),
                patch.dict(EXPECTED_SIZES, {name: 4 for name in EXPECTED_SIZES}),
                patch.object(sys, "argv", [commands["mx5-extract-firmware"], str(source), "--output", str(output)]),
            ):
                try:
                    runpy.run_path(commands["mx5-extract-firmware"], run_name="__main__")
                except SystemExit as exc:
                    if exc.code != 0:
                        raise RuntimeError("Installed extraction command failed") from exc
            if (output / "Update.img").read_bytes() != data:
                raise RuntimeError("Installed extraction changed the bundle")
            for name in EXPECTED_SIZES:
                if (output / f"{name}.img").read_bytes() != b"test":
                    raise RuntimeError(f"Incorrect extracted image: {name}")
            digest = hashlib.sha256(b"test").hexdigest()
            expected = "".join(f"{digest}  {name}.img\n" for name in EXPECTED_SIZES)
            if (output / "SHA256SUMS").read_text() != expected:
                raise RuntimeError("Incorrect extracted checksums")
            if json.loads((output / "manifest.json").read_text())["sha256"] != hashlib.sha256(data).hexdigest():
                raise RuntimeError("Incorrect extracted manifest")
    finally:
        os.chdir(original_directory)
    print("Installed commands, package contents, and synthetic extraction passed.")


if __name__ == "__main__":
    main()
