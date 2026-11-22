"""Build-time image hashes and flasher specialisation; no USB access."""

import hashlib
import json
from pathlib import Path

from .bundle import BundleError


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def specialize_flasher(source: str, stock: dict[str, str], patched: dict[str, str]) -> str:
    old = "".join(f"{stock[name]}  {name}\n" for name in stock)
    new = "".join(f"{patched[name]}  {name}\n" for name in stock)
    block = f"<<'CHECKSUMS'\n{old}CHECKSUMS\n"
    if source.count(block) != 1:
        raise BundleError("Flasher pins do not match the validated stock images")
    return source.replace(block, f"<<'CHECKSUMS'\n{new}CHECKSUMS\n")


def publish_metadata(stage: Path, flasher: Path, manifest: dict) -> None:
    stock, images = manifest["stock_images"], manifest["images"]
    script = stage / f"mx5-flash-{manifest['variant']}"
    source = specialize_flasher(flasher.read_text(), stock, images)
    source = source.replace("Usage: mx5-flash ", f"Usage: {script.name} ")
    script.write_text(source)
    script.chmod(0o755)
    (stage / "SHA256SUMS").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in images.items()),
    )
    (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
