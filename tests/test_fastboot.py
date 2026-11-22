import unittest
from collections import deque
from types import SimpleNamespace
from unittest.mock import patch

from mx5_update.bundle import EXPECTED_SIZES
from mx5_update.fastboot import (
    DEFAULT_DOWNLOAD_LIMIT,
    READ_VARIABLES,
    UNLOCK,
    DeviceFailure,
    Fastboot,
    FastbootError,
    RebootError,
    flash,
    hex_size,
    preflight,
)


class Transport:
    def __init__(self, packets=()):
        self.packets = deque(packets)
        self.writes = []
        self.read_timeouts = []
        self.write_timeouts = []
        self.payload_writes = []

    def write(self, data, timeout=5000):
        self.writes.append(data)
        self.write_timeouts.append(timeout)

    def write_all(self, data, timeout=5000):
        self.payload_writes.append(data)
        self.write(data, timeout=timeout)

    def read(self, timeout=5000):
        self.read_timeouts.append(timeout)
        if not self.packets:
            raise OSError("No response")
        return self.packets.popleft()


class Device:
    allow_write = True

    def __init__(self):
        self.values = {
            "version-bootloader": "0.4", "power-source": "ac",
            "max-download-size": "0x70000000", "sparse-image-support": "yes",
            "partition-type:rootfs": "ext4",
        }
        self.events = []
        self.failure = None

    def getvar(self, name):
        self.events.append(("getvar", name))
        return self.values.get(name)

    def command(self, command, **kwargs):
        self.events.append(("command", command))
        if self.failure and command.startswith(self.failure):
            raise DeviceFailure("failure")
        return b""

    def download(self, payload):
        self.events.append(("download", payload))


def bundle():
    return SimpleNamespace(images=tuple(
        SimpleNamespace(partition=name, unpack=lambda: b"test") for name in EXPECTED_SIZES
    ))


class ProtocolTests(unittest.TestCase):
    def test_progress_resets_full_timeout_without_packet_cap(self):
        transport = Transport([b"INFOprogress"] * 2048 + [b"OKAY"])
        self.assertEqual(Fastboot(transport).response(timeout=300_000), b"")
        self.assertEqual(transport.read_timeouts, [300_000] * 2049)

    def test_timeout_after_progress_still_aborts(self):
        transport = Transport([b"INFOprogress"])
        with self.assertRaises(OSError):
            Fastboot(transport).response(timeout=300_000)
        self.assertEqual(transport.read_timeouts, [300_000, 300_000])

    def test_info_then_okay(self):
        transport = Transport([b"INFOhello", b"OKAY0.4"])
        messages = []
        protocol = Fastboot(transport, info=messages.append)
        self.assertEqual(protocol.getvar("version-bootloader"), "0.4")
        self.assertEqual(messages, ["hello"])
        self.assertEqual(transport.writes, [b"getvar:version-bootloader"])

    def test_explicit_fail_optional(self):
        protocol = Fastboot(Transport([b"FAILunknown variable"]))
        self.assertIsNone(protocol.getvar("power-source"))

    def test_usb_errors_not_optional(self):
        with self.assertRaises(OSError):
            Fastboot(Transport()).getvar("power-source")

    def test_invalid_framing_not_optional(self):
        for response in [b"", b"OK", b"garbage", b"DATA00000001"]:
            with self.subTest(response=response), self.assertRaises(FastbootError):
                Fastboot(Transport([response])).getvar("power-source")

    def test_readonly_blocks_all_mutating_commands(self):
        transport = Transport()
        protocol = Fastboot(transport)
        for command in [UNLOCK, "flash:rootfs", "erase:rootfs", "reboot", "getvar:all"]:
            with self.subTest(command=command), self.assertRaises(FastbootError):
                protocol.command(command)
        with self.assertRaises(FastbootError):
            protocol.download(b"x")
        self.assertFalse(transport.writes)

    def test_download_framing(self):
        transport = Transport([b"DATA00000004", b"OKAY"])
        Fastboot(transport, allow_write=True).download(b"test")
        self.assertEqual(transport.writes, [b"download:00000004", b"test"])
        self.assertEqual(transport.payload_writes, [b"test"])
        self.assertEqual(transport.write_timeouts, [5000, 5000])
        self.assertEqual(transport.read_timeouts, [5000, 5000])

    def test_payload_uses_megabyte_chunks(self):
        data = b"x" * (1024 * 1024 + 1)
        transport = Transport([b"DATA00100001", b"OKAY"])
        Fastboot(transport, allow_write=True).download(data)
        self.assertEqual([len(chunk) for chunk in transport.payload_writes], [1024 * 1024, 1])

    def test_download_rejects_wrong_size_before_payload(self):
        for response in [b"DATA00000003", b"DATAnope!!!!", b"OKAY"]:
            transport = Transport([response])
            with self.subTest(response=response), self.assertRaises(FastbootError):
                Fastboot(transport, allow_write=True).download(b"test")
            self.assertEqual(len(transport.writes), 1)

    def test_download_stops_on_payload_failure(self):
        with self.assertRaises(DeviceFailure):
            Fastboot(Transport([b"DATA00000004", b"FAILwrite"]), allow_write=True).download(b"test")

    def test_hexadecimal_sizes(self):
        self.assertEqual(hex_size("0x70000000"), 0x70000000)
        self.assertEqual(hex_size("20000000"), 0x20000000)
        for value in ["0", "-1", "0x", "1; reboot", "", " 10"]:
            with self.subTest(value=value), self.assertRaises(FastbootError):
                hex_size(value)

    def test_invalid_commands_never_sent(self):
        transport = Transport()
        for command in ["", "x" * 65, "bad\0command"]:
            with self.subTest(command=command), self.assertRaises(FastbootError):
                Fastboot(transport, allow_write=True).command(command)
        self.assertFalse(transport.writes)


class UpdateTests(unittest.TestCase):
    def test_complete_wire_sequence_matches_fitting_image_path(self):
        device = Device()
        variables = [
            b"FAILunknown variable" if device.values.get(name) is None
            else b"OKAY" + device.values[name].encode()
            for name in READ_VARIABLES
        ]
        transport = Transport(variables + [
            b"OKAY",  # Unlock.
            b"DATA00000004", b"OKAY", b"OKAY",  # Splash.
            b"DATA00000004", b"OKAY", b"OKAY",  # Recovery splash.
            b"OKAY",  # Rootfs erase.
            b"DATA00000004", b"OKAY", b"OKAY",  # Rootfs.
            b"OKAY",  # Reboot.
        ])
        with patch.dict(EXPECTED_SIZES, {name: 4 for name in EXPECTED_SIZES}):
            flash(Fastboot(transport, allow_write=True), bundle(), log=lambda _: None)
        self.assertEqual(transport.writes, [
            *[("getvar:" + name).encode() for name in READ_VARIABLES],
            UNLOCK.encode(),
            b"download:00000004", b"test", b"flash:splash",
            b"download:00000004", b"test", b"flash:recoverysplash",
            b"erase:rootfs",
            b"download:00000004", b"test", b"flash:rootfs",
            b"reboot",
        ])
        self.assertFalse(transport.packets)

    def test_preflight_matches_live_mx5(self):
        device = Device()
        self.assertEqual(preflight(device).download_limit, 0x70000000)
        self.assertTrue(all(event[0] == "getvar" for event in device.events))

    def test_preflight_default_download_limit(self):
        device = Device()
        device.values.pop("max-download-size")
        self.assertEqual(preflight(device).download_limit, DEFAULT_DOWNLOAD_LIMIT)

    def test_preflight_refuses_unsafe_device(self):
        for variable, value in [
            ("power-source", "battery"), ("power-source", None),
            ("power-source", "unknown"), ("version-bootloader", None),
            ("max-download-size", "0x100000"), ("partition-type:rootfs", None),
            ("partition-type:rootfs", "raw"), ("partition-size:rootfs", "0x1000"),
            ("partition-type:splash", "ext4"),
        ]:
            with self.subTest(variable=variable, value=value):
                device = Device()
                device.values[variable] = value
                with self.assertRaises(FastbootError):
                    flash(device, bundle(), log=lambda _: None)
                self.assertTrue(all(event[0] == "getvar" for event in device.events))

    def test_flash_sequence_reboots_after_all_writes_without_data_erase(self):
        device = Device()
        with patch.dict(EXPECTED_SIZES, {name: 4 for name in EXPECTED_SIZES}):
            flash(device, bundle(), log=lambda _: None)
        mutations = [event for event in device.events if event[0] != "getvar"]
        self.assertEqual(mutations, [
            ("command", UNLOCK),
            ("download", b"test"), ("command", "flash:splash"),
            ("download", b"test"), ("command", "flash:recoverysplash"),
            ("command", "erase:rootfs"),
            ("download", b"test"), ("command", "flash:rootfs"),
            ("command", "reboot"),
        ])

    def test_stop_after_first_flash_failure(self):
        device = Device()
        device.failure = "flash:splash"
        with (
            patch.dict(EXPECTED_SIZES, {name: 4 for name in EXPECTED_SIZES}),
            self.assertRaises(DeviceFailure),
        ):
            flash(device, bundle(), log=lambda _: None)
        self.assertEqual(device.events[-1], ("command", "flash:splash"))

    def test_no_unlock_if_decompression_fails(self):
        device = Device()
        bad = bundle()
        bad.images[-1].unpack = lambda: (_ for _ in ()).throw(ValueError())
        with self.assertRaises(ValueError):
            flash(device, bad, log=lambda _: None)
        self.assertTrue(all(event[0] == "getvar" for event in device.events))

    def test_readonly_refuses_flash(self):
        device = Device()
        device.allow_write = False
        with self.assertRaises(FastbootError):
            flash(device, bundle())
        self.assertFalse(device.events)

    def test_no_reboot_after_any_mutating_command_failure(self):
        for stage in [
            UNLOCK, "flash:splash", "flash:recoverysplash", "erase:rootfs", "flash:rootfs",
        ]:
            with self.subTest(stage=stage):
                device = Device()
                device.failure = stage
                with (
                    patch.dict(EXPECTED_SIZES, {name: 4 for name in EXPECTED_SIZES}),
                    self.assertRaises(DeviceFailure),
                ):
                    flash(device, bundle(), log=lambda _: None)
                self.assertNotIn(("command", "reboot"), device.events)

    def test_no_reboot_after_download_failure(self):
        for position in range(3):
            with self.subTest(position=position):
                device = Device()
                with (
                    patch.dict(EXPECTED_SIZES, {name: 4 for name in EXPECTED_SIZES}),
                    patch.object(
                        device, "download",
                        side_effect=[None] * position + [OSError("USB disconnected")],
                    ),
                    self.assertRaises(OSError),
                ):
                    flash(device, bundle(), log=lambda _: None)
                self.assertNotIn(("command", "reboot"), device.events)

    def test_incomplete_or_duplicate_bundle_never_reboots(self):
        for images in [bundle().images[:2], (bundle().images[0],) * 3]:
            device = Device()
            with self.subTest(images=images), self.assertRaises(FastbootError):
                flash(device, SimpleNamespace(images=images), log=lambda _: None)
            self.assertEqual(device.events, [])

    def test_reboot_failure_reports_completed_writes_without_retry(self):
        device = Device()
        device.failure = "reboot"
        with (
            patch.dict(EXPECTED_SIZES, {name: 4 for name in EXPECTED_SIZES}),
            self.assertRaisesRegex(RebootError, "All three firmware writes"),
        ):
            flash(device, bundle(), log=lambda _: None)
        self.assertEqual(device.events[-2:], [
            ("command", "flash:rootfs"), ("command", "reboot"),
        ])
        self.assertEqual(device.events.count(("command", "reboot")), 1)
