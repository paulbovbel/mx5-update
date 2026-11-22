"""Apply the upstream MX5 Bridge patch plan, optionally after NAM."""

import importlib.util
from pathlib import Path

from ..bundle import BundleError
from ..filesystem import Filesystem

NAME = "bridge"
COMMIT = "c2ef5344fb01a1a4b2ee3356c1b4d040b8af9688"
VERSION = "0.7"
SOURCE = "https://github.com/TicT4x/MX-Edit"
SCRIPT_NAMES = (
    "usb-otg-audio-start.sh", "usb-otg-audio-stop.sh", "mx5bridge-diag.sh",
    "mx5bridge-usb.sh", "mx5bridge-db.sh", "mx5bridge-sqlite3",
    "setup-mass-storage.sh", "remove-mass-storage.sh", "runevil", "evil",
)
WRITES = {f"/usr/Evil/Scripts/{name}" for name in SCRIPT_NAMES} | {
    "/usr/Evil/Assignments/f_midi_Device.qml",
    "/usr/Evil/Assignments/f_midi_Assignments.qml",
}
NAM_INFO = "/usr/Evil/Scripts/mx5bridge-nam.txt"


def validate_plan(plan: dict, nam: object, with_nam: bool = False) -> None:
    expected = WRITES | ({NAM_INFO} if with_nam else set())
    if bool(nam) != with_nam or set(plan) != expected:
        raise BundleError("Unexpected bridge patch paths or NAM modification")
    for path, (data, mode) in plan.items():
        expected_mode = 0o100644 if path.endswith((".qml", ".txt")) else 0o100755
        if not data or mode != expected_mode:
            raise BundleError(f"Unexpected bridge file contents/mode: {path}")


def apply(context, work: Path) -> list[dict]:
    upstream = context.bridge_source
    spec = importlib.util.spec_from_file_location(
        "mx5_bridge_patch", upstream / "firmware" / "bridgepatch.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.VERSION != VERSION:
        raise BundleError("Unexpected upstream bridge version")
    filesystem = Filesystem(context.rootfs)
    info = None
    if context.with_nam:
        from .nam import COMMIT as NAM_COMMIT

        info = f"nam_mod_ref={NAM_COMMIT}\nnam_instanzen={context.instances}\n"
    plan, nam = module.plan(filesystem.read, nam_info=info, device="MX5")
    validate_plan(plan, nam, context.with_nam)
    return filesystem.apply(plan, work)
