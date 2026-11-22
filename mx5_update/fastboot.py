"""Fastboot framing and a deliberately narrow MX5 v2.7 update sequence."""

import re
from dataclasses import dataclass

from .bundle import EXPECTED_SIZES, Bundle
from .usb import USBError

UNLOCK = "oem inmusic-unlock-magic-7de5fbc22b8c524e"
DEFAULT_DOWNLOAD_LIMIT = 512 * 1024 * 1024  # Official updater's initialization value.
READ_VARIABLES = (
    "version-bootloader", "power-source", "max-download-size", "sparse-image-support",
    "partition-type:splash", "partition-type:recoverysplash", "partition-type:rootfs",
    "partition-size:splash", "partition-size:recoverysplash", "partition-size:rootfs",
)


class FastbootError(RuntimeError):
    pass


class DeviceFailure(FastbootError):
    pass


class RebootError(FastbootError):
    """All firmware writes succeeded, but reboot completion is uncertain."""


class Fastboot:
    def __init__(self, transport, *, allow_write=False, info=None):
        self.transport = transport
        self.allow_write = allow_write
        self.info = info or (lambda _: None)

    def response(self, *, allow_data=False, timeout=5000):
        # Match the vendor's inactivity timeout: each INFO packet starts a
        # fresh read with the full timeout, even for a long erase/flash.
        while True:
            packet = self.transport.read(timeout=timeout)
            status, payload = packet[:4], packet[4:]
            if status == b"INFO":
                self.info(payload.decode("ascii", errors="replace"))
            elif status == b"OKAY":
                return payload
            elif status == b"FAIL":
                raise DeviceFailure(payload.decode("ascii", errors="replace"))
            elif status == b"DATA" and allow_data and re.fullmatch(b"[0-9a-fA-F]{8}", payload):
                return int(payload, 16)
            else:
                raise FastbootError(f"Unexpected Fastboot packet: {packet[:80]!r}")

    def command(self, command: str, *, timeout=5000):
        # Read-only is enforced here, not merely by the CLI.
        if not self.allow_write and command not in {
            "getvar:" + name for name in READ_VARIABLES
        }:
            raise FastbootError("Mutating or unknown commands are disabled")
        encoded = command.encode("ascii")
        if not encoded or len(encoded) > 64 or b"\0" in encoded:
            raise FastbootError("Invalid Fastboot command")
        self.transport.write(encoded, timeout=timeout)
        return self.response(timeout=timeout)

    def getvar(self, name: str) -> str | None:
        try:
            return self.command("getvar:" + name).decode("ascii")
        except DeviceFailure:
            return None  # Only explicit device FAIL means an unsupported variable.

    def download(self, data: bytes):
        if not self.allow_write:
            raise FastbootError("Downloads are disabled in read-only mode")
        if not 0 < len(data) <= DEFAULT_DOWNLOAD_LIMIT:
            raise FastbootError("Download is empty or exceeds the implementation limit")
        self.transport.write(f"download:{len(data):08x}".encode())
        accepted = self.response(allow_data=True)
        if type(accepted) is not int or accepted != len(data):
            raise FastbootError(f"Device accepted unexpected download size: {accepted!r}")
        for offset in range(0, len(data), 1024 * 1024):
            self.transport.write_all(data[offset:offset + 1024 * 1024], timeout=5000)
        self.response(timeout=5000)


def hex_size(value: str) -> int:
    if not re.fullmatch(r"(?:0[xX])?[0-9a-fA-F]+", value):
        raise FastbootError(f"Invalid Fastboot hexadecimal size: {value!r}")
    size = int(value, 16)
    if size <= 0:
        raise FastbootError("Device reported a zero size")
    return size


@dataclass(frozen=True)
class Preflight:
    variables: dict[str, str | None]
    download_limit: int


def preflight(fastboot: Fastboot) -> Preflight:
    values = {name: fastboot.getvar(name) for name in READ_VARIABLES}
    if not values["version-bootloader"]:
        raise FastbootError("Bootloader version query failed")
    power = values["power-source"]
    # Stricter than the shipped config, which can bypass the vendor's power check.
    if not power or power.lower() not in {"mains", "dc", "ac", "external", "adapter"}:
        raise FastbootError(f"Cannot verify external power: {power!r}")
    maximum = values["max-download-size"]
    limit = hex_size(maximum) if maximum else DEFAULT_DOWNLOAD_LIMIT
    for partition, size in EXPECTED_SIZES.items():
        if size > limit:
            raise FastbootError(
                f"{partition} needs {size} bytes, download limit is {limit}; "
                "split/sparse transfers are not implemented"
            )
        kind = values[f"partition-type:{partition}"]
        if partition == "rootfs" and kind != "ext4":
            raise FastbootError(f"Expected ext4 rootfs partition, got {kind!r}")
        if partition != "rootfs" and kind not in {None, "", "raw"}:
            raise FastbootError(f"Unexpected splash partition type: {kind!r}")
        reported = values[f"partition-size:{partition}"]
        if reported is not None and hex_size(reported) < size:
            raise FastbootError(f"Partition {partition} is smaller than its payload")
    return Preflight(values, limit)


def flash(fastboot: Fastboot, bundle: Bundle, *, log=print):
    if not fastboot.allow_write:
        raise FastbootError("Flashing is disabled in read-only mode")
    if tuple(image.partition for image in bundle.images) != tuple(EXPECTED_SIZES):
        raise FastbootError("Expected all three firmware partitions in bundle order")
    # Complete all validation before the first mutating command.
    state = preflight(fastboot)
    payloads = [(image.partition, image.unpack()) for image in bundle.images]
    for partition, payload in payloads:
        if len(payload) != EXPECTED_SIZES[partition] or len(payload) > state.download_limit:
            raise FastbootError("Payload size changed after validation")
    try:
        fastboot.command(UNLOCK)
    except DeviceFailure as exc:
        # Exactly the compatibility cases accepted by the official updater.
        if str(exc) not in {"unknown oem command", "unrecognized command"}:
            raise
    for partition, payload in payloads:
        log(f"Writing {partition}: {len(payload)} bytes")
        if state.variables[f"partition-type:{partition}"] == "ext4":
            fastboot.command(f"erase:{partition}", timeout=300_000)
        fastboot.download(payload)
        fastboot.command(f"flash:{partition}", timeout=300_000)
    log("All three writes acknowledged. Requesting reboot.")
    try:
        fastboot.command("reboot")
    except (FastbootError, USBError, OSError) as exc:
        raise RebootError(
            f"All three firmware writes were acknowledged, but reboot was not: {exc}"
        ) from exc
    log("Reboot acknowledged. Verify firmware v2.7 in Global Settings after startup.")
