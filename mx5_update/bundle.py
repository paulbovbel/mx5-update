"""Strict, bounded reader for the MX5 v2.7 FDT firmware container."""

import hashlib
import lzma
import shutil
import struct
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

MAGIC = 0xD00DFEED
MAX_BUNDLE = 128 * 1024 * 1024
MAX_IMAGE = 512 * 1024 * 1024
KNOWN_SHA256 = "c09326c7a9caf561049a214c522c9e6ed72bc3660a3930ba0023943cc376628c"
KNOWN_EXE_SHA256 = "3a1c7f818ded8f8e3f0b350889a8ffcaab1f247aa5438ad23620b8392bad83df"
EXPECTED_SIZES = {
    "splash": 1_536_000,
    "recoverysplash": 1_536_000,
    "rootfs": 314_572_800,
}


class BundleError(ValueError):
    pass


def cstring(data: bytes) -> str:
    if not data.endswith(b"\0") or b"\0" in data[:-1]:
        raise BundleError("Expected a single NUL-terminated string")
    try:
        return data[:-1].decode("ascii")
    except UnicodeDecodeError as exc:
        raise BundleError("Non-ASCII firmware metadata") from exc


def read_fdt(data: bytes) -> dict[str, dict[str, bytes]]:
    """Parse only the FDT structures needed here; reject ambiguous input."""
    if len(data) < 40 or len(data) > MAX_BUNDLE:
        raise BundleError("Invalid bundle length")
    magic, size, tree, strings, reserve, version, last, _, nstrings, ntree = (
        struct.unpack_from(">10I", data)
    )
    if magic != MAGIC or size != len(data) or version != 17 or last > 17:
        raise BundleError("Unsupported FDT header")
    if not (
        40 <= reserve < tree
        and tree % 4 == 0
        and ntree % 4 == 0
        and tree + ntree <= strings
        and strings + nstrings <= size
    ):
        raise BundleError("Invalid FDT section bounds")
    names = data[strings : strings + nstrings]
    end = tree + ntree
    pos = tree
    stack: list[str] = []
    nodes: dict[str, dict[str, bytes]] = {}
    finished_root = False

    def take(n: int) -> bytes:
        nonlocal pos
        if n < 0 or pos + n > end:
            raise BundleError("Truncated FDT structure")
        value = data[pos : pos + n]
        pos += n
        return value

    def align() -> None:
        take((-pos) % 4)

    while pos < end:
        token = struct.unpack(">I", take(4))[0]
        if token == 1:
            stop = data.find(b"\0", pos, end)
            if stop < 0 or finished_root:
                raise BundleError("Invalid FDT node")
            name = cstring(take(stop - pos + 1))
            align()
            if (not stack and name) or (stack and (not name or "/" in name)):
                raise BundleError("Invalid FDT node name")
            stack.append(name)
            if len(stack) > 16:
                raise BundleError("FDT nesting limit exceeded")
            path = "/".join(stack)
            if path in nodes:
                raise BundleError("Duplicate FDT node")
            nodes[path] = {}
        elif token == 2:
            if not stack:
                raise BundleError("Unbalanced FDT nodes")
            stack.pop()
            if not stack:
                finished_root = True
        elif token == 3:
            if not stack:
                raise BundleError("Property outside FDT node")
            length, offset = struct.unpack(">II", take(8))
            stop = names.find(b"\0", offset)
            if offset >= len(names) or stop < 0:
                raise BundleError("Invalid FDT property name offset")
            name = cstring(names[offset : stop + 1])
            props = nodes["/".join(stack)]
            if not name or name in props:
                raise BundleError("Duplicate or empty FDT property")
            props[name] = take(length)
            align()
        elif token == 4:
            continue
        elif token == 9:
            if stack or not finished_root or pos != end:
                raise BundleError("Invalid FDT terminator")
            return nodes
        else:
            raise BundleError(f"Unsupported FDT token {token}")
    raise BundleError("Missing FDT terminator")


def decompress(data: bytes, limit: int = MAX_IMAGE) -> bytes:
    decoder = lzma.LZMADecompressor(memlimit=128 * 1024 * 1024)
    try:
        result = decoder.decompress(data, max_length=limit + 1)
    except lzma.LZMAError as exc:
        raise BundleError(f"Invalid XZ payload: {exc}") from exc
    if len(result) > limit or not decoder.eof or decoder.unused_data:
        raise BundleError("Oversized, truncated, or concatenated XZ payload")
    return result


@dataclass(frozen=True)
class Image:
    partition: str
    compressed: bytes
    sha1: str

    def unpack(self) -> bytes:
        return decompress(self.compressed, EXPECTED_SIZES[self.partition])


@dataclass(frozen=True)
class Bundle:
    sha256: str
    description: str
    images: tuple[Image, ...]

    @classmethod
    def load(cls, path: Path) -> "Bundle":
        if path.stat().st_size > MAX_BUNDLE:
            raise BundleError("Bundle is too large")
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        # Pinning also prevents accidentally applying Core/Gigboard firmware,
        # future unsupported layouts, or a modified image with replaced hashes.
        if digest != KNOWN_SHA256:
            raise BundleError(
                f"Unrecognized bundle SHA-256: {digest}; only official MX5 v2.7 is supported"
            )
        nodes = read_fdt(data)
        root = nodes.get("", {})
        if root.get("compatible") != b"inmusic,hg04\0":
            raise BundleError("Not an MX5/HG04 image")
        if root.get("inmusic,devices") != bytes.fromhex("0763301a"):
            raise BundleError("Unexpected target USB device")
        images = []
        for partition, expected_size in EXPECTED_SIZES.items():
            props = nodes.get(f"/images/{partition}", {})
            hashes = nodes.get(f"/images/{partition}/hash", {})
            if (
                props.get("partition") != partition.encode() + b"\0"
                or props.get("compression") != b"xz\0"
                or hashes.get("algo") != b"sha1\0"
                or "data" not in props
            ):
                raise BundleError(f"Unsupported image metadata: {partition}")
            compressed = props["data"]
            digest1 = hashlib.sha1(compressed).digest()
            if digest1 != hashes.get("value"):
                raise BundleError(f"Checksum mismatch: {partition}")
            image = Image(partition, compressed, digest1.hex())
            if len(image.unpack()) != expected_size:
                raise BundleError(f"Unexpected decompressed size: {partition}")
            images.append(image)
        allowed = {"", "/images"}
        for partition in EXPECTED_SIZES:
            allowed.update((f"/images/{partition}", f"/images/{partition}/hash"))
        if set(nodes) != allowed:
            raise BundleError("Unexpected firmware nodes")
        return cls(digest, cstring(root["description"]), tuple(images))


def extract_container(source: Path, destination: Path) -> None:
    """Extract Update.img only, never execute the vendor's EXE."""
    if destination.exists():
        raise BundleError(f"Refusing to overwrite {destination}")
    if source.stat().st_size > MAX_BUNDLE:
        raise BundleError("Source is too large")
    with tempfile.TemporaryDirectory(prefix="mx5-extract-") as temp:
        exe = source
        if zipfile.is_zipfile(source):
            with zipfile.ZipFile(source) as archive:
                members = [
                    item for item in archive.infolist()
                    if item.filename.endswith(".exe") and not item.is_dir()
                ]
                if len(members) != 1 or members[0].file_size > MAX_BUNDLE:
                    raise BundleError("Expected one bounded updater EXE in ZIP")
                exe = Path(temp) / "updater.exe"
                exe.write_bytes(archive.read(members[0]))
        target = Path(temp) / "Update.img"
        if exe.suffix.lower() == ".img":
            target.write_bytes(exe.read_bytes())
        else:
            if hashlib.sha256(exe.read_bytes()).hexdigest() != KNOWN_EXE_SHA256:
                raise BundleError("Unrecognized updater EXE; only official MX5 v2.7 is supported")
            sevenzip = shutil.which("7zz") or shutil.which("7z")
            if not sevenzip:
                raise BundleError("Install 7zz or 7z (7-Zip) to extract the Windows updater")
            try:
                with target.open("wb") as output:
                    result = subprocess.run(
                        [sevenzip, "e", "-so", str(exe.resolve()), "Update.img"],
                        stdout=output, stderr=subprocess.PIPE, timeout=120, check=False,
                    )
                if result.returncode:
                    raise BundleError(result.stderr.decode(errors="replace"))
            except subprocess.TimeoutExpired as exc:
                raise BundleError("7-Zip extraction timed out") from exc
            except FileNotFoundError as exc:
                raise BundleError("Install 7zz (7-Zip) to extract the Windows updater") from exc
        Bundle.load(target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as output:
            output.write(target.read_bytes())
