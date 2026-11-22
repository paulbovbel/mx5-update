"""Rootless ext4 operations, explicit checks and patch read-back."""

import hashlib
import re
import subprocess
from pathlib import Path

from .bundle import EXPECTED_SIZES, BundleError


def run(*args: str, timeout: int = 120) -> bytes:
    result = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    if result.returncode:
        raise BundleError(f"{args[0]} failed: {result.stderr.decode(errors='replace')}")
    return result.stdout


class Filesystem:
    def __init__(self, image: Path):
        self.image = image

    def check(self) -> None:
        if self.image.stat().st_size != EXPECTED_SIZES["rootfs"]:
            raise BundleError("Mod changed rootfs image size")
        run("e2fsck", "-fn", str(self.image))

    def read(self, path: str) -> bytes:
        # All paths are adapter-owned constants, never user-provided debugfs commands.
        return run("debugfs", "-R", f'cat "{path}"', str(self.image))

    def record(self, path: str, mode: int) -> dict:
        data = self.read(path)
        if not data:
            raise BundleError(f"Missing or empty mod file: {path}")
        stat = run("debugfs", "-R", f'stat "{path}"', str(self.image)).decode()
        if not re.search(rf"Mode:\s+0{mode & 0o7777:o}\b", stat) or not re.search(
            r"User:\s+0\s+Group:\s+0\b", stat,
        ):
            raise BundleError(f"Mod metadata mismatch: {path}")
        return {"path": path, "sha256": hashlib.sha256(data).hexdigest(), "mode": oct(mode)}

    def apply(self, plan: dict, work: Path) -> list[dict]:
        commands = []
        before = {}
        for index, (path, (data, mode)) in enumerate(sorted(plan.items())):
            old = self.read(path)
            before[path] = hashlib.sha256(old).hexdigest() if old else None
            local = work / f"patch-file-{index}"
            local.write_bytes(data)
            commands.extend((
                f'rm "{path}"', f'write "{local.name}" "{path}"',
                f'sif "{path}" mode 0{mode:o}',
                f'sif "{path}" uid 0', f'sif "{path}" gid 0',
            ))
        command_file = work / "debugfs.commands"
        command_file.write_text("\n".join(commands) + "\n")
        result = subprocess.run(
            ["debugfs", "-w", "-f", str(command_file), str(self.image)],
            cwd=work, capture_output=True, timeout=120, check=False,
        )
        if result.returncode:
            raise BundleError("debugfs patch failed")
        records = []
        # debugfs can exit zero on command failure: verify every byte and mode.
        for path, (data, mode) in sorted(plan.items()):
            if self.read(path) != data:
                raise BundleError(f"Mod read-back mismatch: {path}")
            records.append({**self.record(path, mode), "before_sha256": before[path]})
        return records
