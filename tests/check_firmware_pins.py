"""Offline build check: compare the shell's embedded pins with extracted images."""

import hashlib
import re
import sys
from pathlib import Path

PARTITIONS = ("splash", "recoverysplash", "rootfs")


def read_pins(script: Path) -> dict[str, str]:
    source = script.read_text()
    start = "<<'CHECKSUMS'\n"
    if source.count(start) != 1:
        raise ValueError("Expected exactly one embedded checksum block")
    block = source.split(start, 1)[1].split("\nCHECKSUMS\n", 1)[0]
    pins = {}
    for line in block.splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([a-z]+\.img)", line)
        if match is None or match[2] in pins:
            raise ValueError("Invalid or duplicate embedded checksum")
        pins[match[2]] = match[1]
    if tuple(pins) != tuple(f"{partition}.img" for partition in PARTITIONS):
        raise ValueError("Unexpected embedded image names or order")
    return pins


def check_pins(script: Path, firmware: Path) -> None:
    for name, expected in read_pins(script).items():
        with (firmware / name).open("rb") as image:
            actual = hashlib.file_digest(image, "sha256").hexdigest()
        if actual != expected:
            raise ValueError(f"Embedded checksum does not match extracted {name}")


if __name__ == "__main__":
    check_pins(Path(sys.argv[1]), Path(sys.argv[2]))
    print("All embedded firmware pins match extracted images.")
