import argparse
import json
import os
import sys
from pathlib import Path

from .bundle import EXPECTED_SIZES, Bundle, BundleError, extract_firmware
from .fastboot import (
    READ_VARIABLES,
    Fastboot,
    FastbootError,
    RebootError,
    flash,
    preflight,
)
from .usb import USB, USBError


def parser():
    result = argparse.ArgumentParser(description="Linux HeadRush MX5 firmware updater")
    result.set_defaults(bundle=None)
    commands = result.add_subparsers(dest="command", required=True)
    default_bundle = os.environ.get("MX5_FIRMWARE")

    def add_bundle(sub):
        sub.add_argument(
            "bundle", type=Path, nargs="?",
            default=Path(default_bundle) if default_bundle else None,
            help="Update.img (defaults to MX5_FIRMWARE in the Nix package)",
        )
    extract = commands.add_parser("extract", help="Extract and validate Update.img; no USB")
    extract.add_argument("source", type=Path, help="Official Windows ZIP/EXE or Update.img")
    extract.add_argument("--output", type=Path, required=True, help="New output directory")
    for command, help_text in (
        ("inspect", "Validate bundle and print metadata; no USB"),
        ("plan", "Validate bundle and show the update sequence; no USB"),
    ):
        sub = commands.add_parser(command, help=help_text)
        add_bundle(sub)
    probe = commands.add_parser("probe", help="Read-only bootloader queries")
    probe.add_argument("--serial")
    check = commands.add_parser("check", help="Read-only update preflight; no unlock/write")
    add_bundle(check)
    check.add_argument("--serial")
    update = commands.add_parser("flash", help="Update firmware and reboot after successful writes")
    add_bundle(update)
    update.add_argument("--serial", required=True, help="Exact serial returned by probe")
    return result


def run(args):
    if args.command == "extract":
        extract_firmware(args.source, args.output)
        print(f"Validated and extracted firmware to {args.output}")
        return
    if args.command != "probe" and args.bundle is None:
        raise BundleError("Supply an Update.img path or set MX5_FIRMWARE")
    bundle = Bundle.load(args.bundle) if args.bundle is not None else None
    if args.command in {"inspect", "plan"}:
        metadata = bundle.metadata()
        if args.command == "plan":
            metadata["plan"] = [
                "Read-only device, external-power, partition, and transfer-limit checks",
                "Vendor compatibility unlock",
                *[
                    f"{partition}: erase only if ext4; download raw image; flash partition"
                    for partition in EXPECTED_SIZES
                ],
                "Send reboot only after all three firmware writes are acknowledged",
            ]
        print(json.dumps(metadata, indent=2))
        return
    if args.command == "flash":
        print("Updating MX5 firmware. Back up your rigs, presets, loops, and IRs first.")
        print("Keep external power and USB connected. Do not suspend this computer.")
        print("The pedal will be sent reboot only after all three writes succeed.")
    with USB(serial=args.serial) as transport:
        print(f"MX5 update-mode USB serial: {transport.serial}")
        protocol = Fastboot(
            transport, allow_write=args.command == "flash",
            info=lambda text: print(f"Device: {text}", file=sys.stderr),
        )
        if args.command == "probe":
            print(json.dumps(
                {name: protocol.getvar(name) for name in READ_VARIABLES}, indent=2
            ))
        elif args.command == "check":
            state = preflight(protocol)
            print(json.dumps(state.variables, indent=2))
            print(f"Read-only preflight passed; download limit {state.download_limit} bytes")
        else:
            flash(protocol, bundle)


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        run(args)
        return 0
    except (BundleError, FastbootError, USBError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if isinstance(exc, RebootError):
            print(
                "Firmware writes completed, but reboot status is uncertain. "
                "Check the pedal's display/state before taking further action; "
                "do not automatically retry flashing.",
                file=sys.stderr,
            )
        elif args.command == "flash":
            print(
                "Stopped. If writes began, keep the MX5 powered in update mode. "
                "Do not reboot after an incomplete update; recover with the official updater.",
                file=sys.stderr,
            )
        return 1
    except KeyboardInterrupt:
        print("Interrupted; no further commands sent.", file=sys.stderr)
        return 130
