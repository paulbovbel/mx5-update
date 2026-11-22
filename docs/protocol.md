# MX5 v2.7 protocol notes

These notes distinguish static analysis, read-only device observations, and
hardware update results. No firmware was written during the initial
investigation; a user subsequently reported a successful update to v2.7.

## Artifacts

Source: the MX5 v2.7 Windows updater linked from
<https://www.headrushfx.com/downloads.html>.

| Artifact | SHA-256 |
| --- | --- |
| Windows EXE wrapper | `3a1c7f818ded8f8e3f0b350889a8ffcaab1f247aa5438ad23620b8392bad83df` |
| Inner `FirmwareUpdater.exe` | `92f939cd372f589d0f002a215ecf7a37f0a5e3ec85d0a04a4759355763f4daad` |
| `Update.img` | `c09326c7a9caf561049a214c522c9e6ed72bc3660a3930ba0023943cc376628c` |

The outer EXE is a 32-bit 7-Zip self-extractor. Its actual updater and bundled
`libusb-1.0.dll` are 64-bit. This explains why a 32-bit Wine installation can
open the extractor but fail with “Bad EXE format.”

The bundled Windows libusb needs a Windows USB backend. In Wine 11.0,
WinUSB initialization/read/write entry points are stubs:
<https://github.com/wine-mirror/wine/blob/wine-11.0/dlls/winusb/winusb.spec>.
An enabled updater button is **not** proof of device detection.

## Container

`Update.img` is an FDT version 17 container, not a raw disk image:

- Description: `HG04 upgrade image`.
- Compatible: `inmusic,hg04`.
- `inmusic,devices`: four bytes `07 63 30 1a`.
- `/images/{splash,recoverysplash,rootfs}` each contain `partition`,
  `compression=xz`, and inline `data`.
- Child `hash` nodes contain `algo=sha1` and the compressed data's hash.

| Partition | XZ bytes | Raw bytes | SHA-1 of XZ data |
| --- | ---: | ---: | --- |
| splash | 159724 | 1536000 | `e61445026ee4ed8098dcc60de27ec8a67cfc24f9` |
| recoverysplash | 157384 | 1536000 | `cd4679341f170e365aa041b06a5291990d452ed8` |
| rootfs | 61291516 | 314572800 | `33ce48ac881a4dd169276c8d53d4ecf6b11811b1` |

There is no `uboot` image or partition-table payload in this bundle. The
updater contains generic bootloader/update/reset functionality used by other
bundles; the mere presence of those command strings does not justify sending
them for this update.

## USB and read-only observations

Normal mode: `0763:401a`, USB audio.
Update mode: `0763:301a`, vendor-specific interface 0, subclass `0x42`,
protocol `3`, string `Android Fastboot`. Bulk OUT endpoint `0x02`;
bulk IN endpoint `0x81`; 512-byte max packet size.

Observed read-only responses on one MX5:

| Variable | Value |
| --- | --- |
| version-bootloader | `0.4` |
| power-source | `ac` |
| max-download-size | `0x70000000` |
| sparse-image-support | `yes` |
| partition-type:rootfs | `ext4` |
| partition-type:splash / recoverysplash | FAIL (unsupported) |
| partition-size:all three target names | FAIL (unsupported) |

Linux libusb successfully opened/claimed the interface and exchanged these
queries. That establishes native transport connectivity, **not flash safety**.

## Static analysis of the official updater

Addresses below are virtual addresses in the pinned inner x86-64 EXE.
This is independently written behavior documentation, not copied vendor code.

- `0x14011f9e0`: initialize Fastboot device; set initial max-download value
  to `0x20000000` (512 MiB); send
  `oem inmusic-unlock-magic-7de5fbc22b8c524e`.
  The two exact failures `unknown oem command` and `unrecognized command`
  are accepted for compatibility.
- `0x14011fab0`: query `partition-type:<name>`; issue `erase:<name>` with
  a 300-second timeout only for `ext4`. Failed queries do not cause an erase.
- `0x14011fc70`: initiate a Fastboot `download:%08x` exchange.
- `0x14011fdf0`: issue `flash:<partition>`.
- `0x1401201d0`: raw/sparse transfer machinery. It checks the bootloader and
  `sparse-image-support`; Android sparse framing uses magic `0xed26ff3a`,
  4096-byte blocks, and RAW/DONT_CARE chunks.
- `0x14011a600`: decompress/dispatch image writes; additional bootloader and
  partition-table operations are conditional on relevant image types/names.

## Implementation and hardware validation

The Python package now only validates and extracts firmware, emitting metadata
in `manifest.json`; its CLI is `mx5-extract-firmware SOURCE --output DIRECTORY`.
It contains no USB access, Fastboot implementation, subprocess supervisor, or
device commands. The original ctypes/libusb backend and subsequent Python
Fastboot adapter have both been removed.

[`scripts/mx5-flash`](../scripts/mx5-flash) implements the documented
[runbook](flashing.md) with standard `fastboot` calls under `set -Eeuo pipefail`.
Python extraction also emits raw-image `SHA256SUMS` for inspection; the script
checks its own embedded raw-image SHA-256 pins, rather than trusting that file.

This implementation sends complete **raw** payloads when the reported limit
permits them. A deeper audit confirms that the vendor updater also selects
raw transfers when the decompressed image fits its download buffer; sparse
framing is its overflow path, not mandatory on this bootloader.
The CLI is invoked as `fastboot -s SERIAL …`; writes use
`-S 0 --skip-reboot flash PARTITION IMAGE`. All raw images must fit the device's
download limit; power, partition type, buffer size, and Android slot/logical
properties are **manual prerequisites** in the runbook, not parsed in Python
or the script. Some Fastboot versions print failed `getvar` queries while
returning zero, so the operator must verify the printed values.

The script captures the serial from `fastboot devices`, rejecting empty,
ambiguous, malformed, or network targets. It checks Linux sysfs once before
unlocking and accepts only one `0763:301a` device matching that serial. Only the final successful
write is followed by a separate `reboot` invocation. Failed mutating commands
are not ignored, including unknown OEM-command errors.

Fastboot owns USB framing, partial transfers, acknowledgments, and timeouts;
these are not overridden or claimed identical to the vendor's implementation.
There is no process supervisor or automatic reconnect/retry. Fastboot can wait
indefinitely for a disconnected device; the runbook explains how to handle that.

A successful hardware update was reported using the earlier direct-USB
backend. Read-only checks passed on an MX5 using both Fastboot 35.0.2 and the
Nix-packaged Fastboot. The current shell script has offline command-sequence
and failure-path tests; it has not reflashed hardware.
The tool does not claim complete vendor parity. See the historical
[native-updater comparison](native-updater-audit.md) for evidence and limits.

No flash should be performed merely to test detection. A real flash requires
the explicit `flash` command, a backup, stable AC/USB, and a recovery plan
using the official updater; there is no additional confirmation prompt.
Future work includes comparing complete command
traces from an official update and implementing/testing bounded sparse
transfers if smaller-buffer bootloaders need them.
