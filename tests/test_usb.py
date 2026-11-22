import ctypes as C
import unittest
from collections import deque
from types import SimpleNamespace

from mx5_update.usb import USB, USBError


class USBWriteTests(unittest.TestCase):
    def transport(self, results):
        """Fake only the C library call; exercise the real ctypes write path."""
        usb = object.__new__(USB)
        usb.handle = C.c_void_p(1)
        usb.calls = []
        results = deque(results)

        def transfer(handle, endpoint, buffer, length, transferred, timeout):
            usb.calls.append((C.string_at(buffer, length), endpoint, timeout))
            status, size = results.popleft()
            C.cast(transferred, C.POINTER(C.c_int))[0] = size
            return status

        usb.lib = SimpleNamespace(
            libusb_bulk_transfer=transfer,
            libusb_error_name=lambda _: b"LIBUSB_ERROR_TIMEOUT",
        )
        return usb

    def test_payload_continues_from_actual_offsets(self):
        usb = self.transport([(0, 3), (0, 2), (0, 3)])
        usb.write_all(b"abcdefgh")
        self.assertEqual(usb.calls, [
            (b"abcdefgh", 0x02, 5000),
            (b"defgh", 0x02, 5000),
            (b"fgh", 0x02, 5000),
        ])

    def test_short_command_is_not_fragmented(self):
        usb = self.transport([(0, 2)])
        with self.assertRaisesRegex(USBError, "Short USB command"):
            usb.write(b"reboot")
        self.assertEqual(len(usb.calls), 1)

    def test_zero_progress_and_invalid_counts_stop(self):
        for count in [0, -1, 5]:
            with self.subTest(count=count):
                usb = self.transport([(0, count)])
                with self.assertRaisesRegex(USBError, "progress"):
                    usb.write_all(b"test")
                self.assertEqual(len(usb.calls), 1)

    def test_error_with_partial_progress_is_not_retried(self):
        usb = self.transport([(0, 2), (-7, 1)])
        with self.assertRaisesRegex(USBError, "TIMEOUT"):
            usb.write_all(b"test")
        self.assertEqual([call[0] for call in usb.calls], [b"test", b"st"])

    def test_each_successful_payload_transfer_gets_full_timeout(self):
        usb = self.transport([(0, 1), (0, 1)])
        usb.write_all(b"ab", timeout=1234)
        self.assertEqual([call[2] for call in usb.calls], [1234, 1234])

    def test_empty_transfers_never_reach_usb(self):
        usb = self.transport([])
        for method in [usb.write, usb.write_all]:
            with self.assertRaises(USBError):
                method(b"")
        self.assertEqual(usb.calls, [])
