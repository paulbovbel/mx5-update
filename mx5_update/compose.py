"""Offline, explicit firmware profiles. Sources and tools are pinned by Nix."""

import argparse
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .artifact import publish_metadata, sha256
from .bundle import EXPECTED_SIZES, Bundle, BundleError
from .filesystem import Filesystem
from .mods import bridge, nam

PROFILES = {
    "bridge": (bridge,), "nam": (nam,), "nam-bridge": (nam, bridge),
}


def resolve(profile: str, instances: int = 2) -> tuple:
    if profile not in PROFILES:
        raise BundleError(f"Unknown firmware profile: {profile}")
    mods = PROFILES[profile]
    if instances not in (2, 4) or (nam not in mods and instances != 2):
        raise BundleError("NAM instances must be 2 or 4 and require a NAM profile")
    # The only supported shared write is the NAM launcher followed by its bridge wrapper.
    if nam in mods and bridge in mods and nam.WRITES & bridge.WRITES != {"/usr/Evil/Scripts/evil"}:
        raise BundleError("Unexpected NAM/bridge write overlap")
    return mods


@dataclass
class Context:
    stock_bundle: Path
    rootfs: Path
    bridge_source: Path | None
    nam_cli: Path | None
    with_nam: bool
    instances: int


def build(
    stock_bundle: Path, flasher: Path, output: Path, *, profile: str,
    bridge_source: Path | None = None, nam_cli: Path | None = None, instances: int = 2,
) -> None:
    mods = resolve(profile, instances)
    if bridge in mods and bridge_source is None:
        raise BundleError("Bridge profile requires a pinned upstream source")
    if nam in mods and nam_cli is None:
        raise BundleError("NAM profile requires a pinned upstream CLI")
    if output.exists():
        raise BundleError(f"Refusing to overwrite {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix=".mx5-compose-") as temporary:
        work = Path(temporary).resolve()
        stage = work / "firmware"
        stage.mkdir()
        # This remains the ONLY input firmware acceptance path.
        bundle = Bundle.load(stock_bundle, image_directory=stage)
        names = [f"{partition}.img" for partition in EXPECTED_SIZES]
        stock = {name: sha256(stage / name) for name in names}
        context = Context(
            stock_bundle.resolve(), stage / "rootfs.img", bridge_source, nam_cli,
            nam in mods, instances,
        )
        fs = Filesystem(context.rootfs)
        fs.check()
        stages = []
        for mod in mods:
            stage_work = work / mod.NAME
            stage_work.mkdir()
            before = sha256(context.rootfs)
            records = mod.apply(context, stage_work)
            expected = set(mod.WRITES)
            if mod is bridge and context.with_nam:
                expected.add(bridge.NAM_INFO)
            if {record["path"] for record in records} != expected or len(records) != len(expected):
                raise BundleError(f"Unexpected changed-file declaration: {mod.NAME}")
            fs.check()
            after = sha256(context.rootfs)
            if before == after:
                raise BundleError(f"Mod did not change rootfs: {mod.NAME}")
            stages.append({
                "name": mod.NAME, "source": mod.SOURCE, "revision": mod.COMMIT,
                "options": {"instances": instances} if mod is nam else {},
                "input_rootfs_sha256": before, "output_rootfs_sha256": after,
                "files": records,
            })
        images = {name: sha256(stage / name) for name in names}
        if any(stock[name] != images[name] for name in names[:2]):
            raise BundleError("Mod changed a splash image")
        manifest = {
            "variant": profile, "version": "2.7", "target": "mx5-2.7",
            "stock_bundle_sha256": bundle.sha256,
            "stock_images": stock, "images": images, "mods": stages,
        }
        publish_metadata(stage, flasher, manifest)
        stage.rename(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-bundle", type=Path, required=True)
    parser.add_argument("--flasher", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=PROFILES, required=True)
    parser.add_argument("--bridge-source", type=Path)
    parser.add_argument("--nam-cli", type=Path)
    parser.add_argument("--instances", type=int, choices=(2, 4), default=2)
    args = parser.parse_args()
    try:
        build(
            args.stock_bundle, args.flasher, args.output, profile=args.profile,
            bridge_source=args.bridge_source, nam_cli=args.nam_cli, instances=args.instances,
        )
    except (BundleError, OSError) as exc:
        parser.exit(1, f"Firmware composition failed: {exc}\n")


if __name__ == "__main__":
    main()
