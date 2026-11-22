"""Minimal ctypes libusb transport, restricted to the MX5 update-mode VID/PID."""

import ctypes as C
import ctypes.util
import os

VID, PID = 0x0763, 0x301A


class USBError(RuntimeError):
    pass


class Descriptor(C.Structure):
    _fields_ = [
        ("length", C.c_uint8), ("type", C.c_uint8), ("usb", C.c_uint16),
        ("device_class", C.c_uint8), ("subclass", C.c_uint8),
        ("protocol", C.c_uint8), ("packet_size", C.c_uint8),
        ("vendor", C.c_uint16), ("product", C.c_uint16), ("version", C.c_uint16),
        ("manufacturer", C.c_uint8), ("name", C.c_uint8),
        ("serial", C.c_uint8), ("configurations", C.c_uint8),
    ]


class USB:
    def __init__(self, serial: str | None = None):
        library = os.environ.get("MX5_LIBUSB") or ctypes.util.find_library("usb-1.0")
        if not library:
            raise USBError("libusb-1.0 not found; install it or set MX5_LIBUSB to its path")
        try:
            self.lib = C.CDLL(library)
        except OSError as exc:
            raise USBError(str(exc)) from exc
        self.context = C.c_void_p()
        self.handle = C.c_void_p()
        self.claimed = False
        self.serial = ""
        self._declare()
        self.check(self.lib.libusb_init(C.byref(self.context)))
        try:
            self._open(serial)
        except BaseException:
            self.close()
            raise

    def _declare(self):
        declarations = {
            "init": ([C.POINTER(C.c_void_p)], C.c_int),
            "exit": ([C.c_void_p], None),
            "get_device_list": (
                [C.c_void_p, C.POINTER(C.POINTER(C.c_void_p))], C.c_ssize_t
            ),
            "free_device_list": ([C.POINTER(C.c_void_p), C.c_int], None),
            "get_device_descriptor": ([C.c_void_p, C.POINTER(Descriptor)], C.c_int),
            "open": ([C.c_void_p, C.POINTER(C.c_void_p)], C.c_int),
            "close": ([C.c_void_p], None),
            "get_string_descriptor_ascii": (
                [C.c_void_p, C.c_uint8, C.c_void_p, C.c_int], C.c_int
            ),
            "claim_interface": ([C.c_void_p, C.c_int], C.c_int),
            "release_interface": ([C.c_void_p, C.c_int], C.c_int),
            "bulk_transfer": (
                [C.c_void_p, C.c_ubyte, C.c_void_p, C.c_int,
                 C.POINTER(C.c_int), C.c_uint], C.c_int
            ),
            "error_name": ([C.c_int], C.c_char_p),
        }
        for name, (args, result) in declarations.items():
            function = getattr(self.lib, f"libusb_{name}")
            function.argtypes = args
            function.restype = result

    def check(self, result: int) -> int:
        if result < 0:
            raise USBError(self.lib.libusb_error_name(result).decode())
        return result

    def _open(self, serial):
        devices = C.POINTER(C.c_void_p)()
        count = self.check(self.lib.libusb_get_device_list(self.context, C.byref(devices)))
        selected = []
        try:
            for index in range(count):
                desc = Descriptor()
                self.check(self.lib.libusb_get_device_descriptor(devices[index], C.byref(desc)))
                if (desc.vendor, desc.product) != (VID, PID):
                    continue
                handle = C.c_void_p()
                self.check(self.lib.libusb_open(devices[index], C.byref(handle)))
                try:
                    buffer = C.create_string_buffer(256)
                    if not desc.serial:
                        raise USBError("MX5 has no USB serial number; refusing ambiguous device")
                    length = self.check(
                        self.lib.libusb_get_string_descriptor_ascii(
                            handle, desc.serial, buffer, len(buffer)
                        )
                    )
                    name = buffer.raw[:length].decode("ascii")
                    if serial is None or name == serial:
                        selected.append((handle, name))
                        handle = None
                finally:
                    if handle:
                        self.lib.libusb_close(handle)
            if len(selected) != 1:
                raise USBError(
                    f"Expected exactly one matching MX5 in update mode; found {len(selected)}"
                )
            self.handle, self.serial = selected.pop()
            self.check(self.lib.libusb_claim_interface(self.handle, 0))
            self.claimed = True
        finally:
            for handle, _ in selected:
                self.lib.libusb_close(handle)
            self.lib.libusb_free_device_list(devices, 1)

    def _write_buffer(self, buffer, offset: int, length: int, timeout: int) -> int:
        sent = C.c_int()
        self.check(self.lib.libusb_bulk_transfer(
            self.handle, 0x02, C.byref(buffer, offset), length, C.byref(sent), timeout
        ))
        if not 0 < sent.value <= length:
            raise USBError(f"Invalid USB write progress: {sent.value}/{length}")
        return sent.value

    def write(self, data: bytes, timeout: int = 5000):
        """Send a command in one transfer; never fragment a Fastboot command."""
        if not data:
            raise USBError("Empty USB write")
        buffer = C.create_string_buffer(data)
        sent = self._write_buffer(buffer, 0, len(data), timeout)
        if sent != len(data):
            raise USBError(f"Short USB command write: {sent}/{len(data)}")

    def write_all(self, data: bytes, timeout: int = 5000):
        """Continue successful short payload writes, never failed transfers."""
        if not data:
            raise USBError("Empty USB payload")
        buffer = C.create_string_buffer(data)
        offset = 0
        while offset < len(data):
            offset += self._write_buffer(buffer, offset, len(data) - offset, timeout)

    def read(self, timeout: int = 5000) -> bytes:
        buffer = C.create_string_buffer(4096)
        received = C.c_int()
        self.check(self.lib.libusb_bulk_transfer(
            self.handle, 0x81, buffer, len(buffer), C.byref(received), timeout
        ))
        return buffer.raw[:received.value]

    def close(self):
        if self.handle:
            if self.claimed:
                self.lib.libusb_release_interface(self.handle, 0)
            self.lib.libusb_close(self.handle)
            self.handle = C.c_void_p()
        if self.context:
            self.lib.libusb_exit(self.context)
            self.context = C.c_void_p()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
