import argparse
import sys
from pathlib import Path

from .bundle import BundleError, extract_firmware


def parser():
    result = argparse.ArgumentParser(description="Validate and extract HeadRush MX5 v2.7 firmware")
    result.add_argument("source", type=Path, help="Official Windows ZIP/EXE or Update.img; no USB")
    result.add_argument("--output", type=Path, required=True, help="New output directory")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        extract_firmware(args.source, args.output)
        print(f"Validated and extracted firmware to {args.output}")
        return 0
    except (BundleError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
