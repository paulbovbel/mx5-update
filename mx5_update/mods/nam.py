"""Wrap the upstream NAM CLI; only validated stock MX5 input is supplied."""

import hashlib
import re
import struct
from pathlib import Path

from ..bundle import MAX_BUNDLE, BundleError, Image, read_fdt
from ..filesystem import Filesystem, run

NAME = "nam"
COMMIT = "cf70ea7efc38badb2782136cc74a760f00252e86"
SOURCE = "https://github.com/lolgab/mods-for-legacy-headrush"
WRITES = {
    "/usr/Evil/Evil", "/usr/Evil/Scripts/evil",
    "/usr/Evil/libnam_hook.so", "/usr/Evil/libnam_preload.so",
}


def extract_patched_rootfs(stock: Path, patched: Path) -> bytes:
    """Structural output validation, NOT an alternative stock firmware reader."""
    if patched.stat().st_size > MAX_BUNDLE:
        raise BundleError("Oversized NAM output bundle")
    original = read_fdt(stock.read_bytes())
    output = read_fdt(patched.read_bytes())
    if set(original) != set(output):
        raise BundleError("NAM changed firmware nodes")
    # Upstream rebuilds the FIT timestamp. Only the rootfs payload/hash may otherwise change.
    for path, props in original.items():
        ignored = {"timestamp"} if path == "" else set()
        if path == "/images/rootfs":
            ignored = {"data"}
        elif path == "/images/rootfs/hash":
            ignored = {"value"}
        if {k: v for k, v in props.items() if k not in ignored} != {
            k: v for k, v in output[path].items() if k not in ignored
        }:
            raise BundleError(f"NAM changed unexpected firmware metadata/payload: {path}")
    payload = output["/images/rootfs"]["data"]
    digest = hashlib.sha1(payload).digest()
    if output["/images/rootfs/hash"]["value"] != digest:
        raise BundleError("NAM output rootfs checksum mismatch")
    return Image("rootfs", payload, digest.hex()).unpack()


def validate_launcher(script: bytes, instances: int) -> None:
    text = script.decode()
    pattern = (
        r"\tsystemd-inhibit --what=handle-power-key "
        r"env LD_PRELOAD=/usr/Evil/libnam_preload\.so"
        r"(?: NAM_HOOK_SLOT_GONK(?:_V2)?_ADDR=0x[0-9a-f]+)+ "
        r"/usr/Evil/Evil\n\texitCode=\$\?\n"
    )
    if len(re.findall(pattern, text)) != 1 or "# --- NAM mod ---\n" not in text:
        raise BundleError("Unexpected NAM launcher")
    if ("NAM_HOOK_SLOT_GONK_V2_ADDR=" in text) != (instances == 4):
        raise BundleError("NAM launcher instance count mismatch")


def validate_library(data: bytes) -> None:
    if (
        len(data) < 52 or data[:7] != b"\x7fELF\x01\x01\x01"
        or struct.unpack_from("<H", data, 16)[0] != 3
        or struct.unpack_from("<H", data, 18)[0] != 40
        or struct.unpack_from("<I", data, 36)[0] & 0xFF000400 != 0x05000400
    ):
        raise BundleError("NAM payload is not an ARM32 hard-float ELF library")
    versions = re.findall(rb"GLIBC_(\d+)\.(\d+)(?:\.(\d+))?", data)
    if any(tuple(int(part or b"0") for part in version) > (2, 32, 0) for version in versions):
        raise BundleError("NAM payload requires glibc newer than the device's 2.32")


def apply(context, work: Path) -> list[dict]:
    fs = Filesystem(context.rootfs)
    before = {path: fs.read(path) for path in WRITES}
    patched = work / "Update_nam.img"
    run(
        str(context.nam_cli), str(context.stock_bundle), str(patched),
        "--model", "mx5", "--anxiety-hijack", "--no-nam-pedals",
        "--instances", str(context.instances), timeout=600,
    )
    context.rootfs.write_bytes(extract_patched_rootfs(context.stock_bundle, patched))
    validate_launcher(fs.read("/usr/Evil/Scripts/evil"), context.instances)
    records = []
    for path in sorted(WRITES):
        if path.endswith(".so"):
            validate_library(fs.read(path))
        record = fs.record(path, 0o100755)
        old = before[path]
        record["before_sha256"] = hashlib.sha256(old).hexdigest() if old else None
        if record["sha256"] == record["before_sha256"]:
            raise BundleError(f"NAM did not change expected file: {path}")
        records.append(record)
    return records
