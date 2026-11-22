# mx5-update

**Native Linux firmware tools for the HeadRush MX5.**
No Windows, Wine, or Windows USB drivers are required. Python talks directly
to the pedal's Fastboot interface through Linux libusb.

**A successful MX5 firmware update to v2.7 has been reported using this tool.**
Extraction and read-only probing have also been tested on an MX5. This does
not establish compatibility with other firmware versions or hardware revisions.
Use the official Windows/macOS updater if you need a supported procedure.
An interrupted or incorrect update can leave the pedal unbootable.

## Nix flake: automatic download and extraction

From this checkout:

```sh
nix run . -- inspect
nix run . -- probe
nix run . -- check --serial YOUR_USB_SERIAL
```

The first run downloads the official Windows updater ZIP from HeadRush's CDN
using a fixed SHA-256, extracts it **without executing Windows code**, and
validates the firmware. The packaged CLI automatically uses the validated
`Update.img` in the Nix store. An explicit bundle path overrides that default.

```sh
nix build .                         # CLI with libusb and firmware
nix build .#firmware --out-link firmware-result
ls firmware-result/share/mx5-update # Bundle, raw images, manifest
nix develop                        # Python, libusb, 7-Zip, Ruff; no firmware download
nix flake check                    # Unit tests, firmware extraction, package smoke tests
```

Outputs are available for `x86_64-linux` and `aarch64-linux`.
`nix/package.nix` and `nix/firmware.nix` can also be used with `pkgs.callPackage`
by passing `source` (this repository) and `firmware` to the CLI package.
The firmware is proprietary/unfree; the flake allows only this named firmware
package, fetches it from the vendor, and disables substitution for its extracted
derivation. This does not grant redistribution rights.

Flashing remains opt-in, even with the firmware bundled:

```sh
nix run . -- flash --serial YOUR_USB_SERIAL
```

`flash` starts the update without a confirmation prompt. It requires an explicit
USB serial and performs all firmware/device checks before writing.
No build, check, inspection, or extraction step writes firmware to connected hardware.

## Requirements

- Linux, Python 3.11+, and the libusb-1.0 shared library.
- `7zz` or `7z` (7-Zip) for extracting the official Windows updater.
- An MX5 on its external power supply and a reliable USB data cable.
- A backup of **all** rigs, setlists, presets, loops, and impulse responses.

Python has no third-party package dependencies. From this checkout:

```sh
python3 -m mx5_update --help
```

Or install into a virtual environment with `pip install .` to get the
`mx5-update` command. On NixOS, `nix-shell` provides the runtime and sets
`MX5_LIBUSB` to the correct library. Elsewhere, the library is discovered
automatically; `MX5_LIBUSB=/absolute/path/to/libusb-1.0.so` overrides discovery.

## Download and extract

Download **HeadRush MX5 – Firmware Updater v2.7.0 (Win)** from the
[official downloads page](https://www.headrushfx.com/downloads.html).
Do not use firmware for a Gigboard, Pedalboard, Core, or Prime.

```sh
python3 -m mx5_update extract \
  "$HOME/Downloads/HeadRush MX5 2.7 Firmware Updater - Win.exe.zip" \
  --output ./firmware
python3 -m mx5_update inspect ./firmware/Update.img
python3 -m mx5_update plan ./firmware/Update.img
```

`extract` accepts the ZIP, its self-extracting EXE, or an existing `Update.img`.
It never executes the EXE, never touches USB, and refuses existing output
directories. It produces:

- `Update.img`: the original structured firmware bundle.
- `splash.img`, `recoverysplash.img`, `rootfs.img`: decompressed partition images.
- `manifest.json`: image sizes and checksums.

Only the exact, hash-pinned official MX5 v2.7 bundle is accepted. SHA-1 values
inside the bundle cover the **compressed** payloads. The tool validates those
hashes, the container structure, model/device identifiers, decompression bounds,
and decompressed image sizes. The SHA-256 pin, rather than SHA-1 alone, prevents
silently accepting a modified image.

Do **not** flash `Update.img` as a partition image: it is a container.

## Read-only device checks

On the MX5, select **⋯ → Global Settings → ⋯ → Firmware Update → OK**.
It should enumerate as USB `0763:301a` (often named `Miniboard`).
Normal audio mode uses `0763:401a` and cannot be flashed.

```sh
python3 -m mx5_update probe
python3 -m mx5_update check ./firmware/Update.img --serial YOUR_USB_SERIAL
```

Both commands send **only allowlisted `getvar` queries**. They do not unlock,
erase, download data, flash, or reboot. `probe` prints the serial needed for
flashing. If multiple matching pedals are attached, specify `--serial`.

Unsupported variables appear as `null`; transport/protocol failures are errors.
The tested MX5 exposes no splash partition types or partition sizes, which is
consistent with the vendor updater tolerating failed type queries. `check`
requires external power, an `ext4` rootfs, and an adequate transfer limit.
Where partition-size queries work, their values are also checked.

### USB permissions

If opening the device fails with `LIBUSB_ERROR_ACCESS`, grant your logged-in
desktop session access to **this device**, not the whole USB bus. For a typical
systemd/udev desktop, an administrator can install:

```udev
# /etc/udev/rules.d/70-headrush-mx5.rules
SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="0763", ATTR{idProduct}=="301a", TAG+="uaccess"
```

Reload udev rules, then unplug/replug the cable. Use your distribution's
declarative equivalent on NixOS. Do not run Wine or this updater as root.

## Flashing

The v2.7 update sequence has been used successfully on an MX5. Read
[the protocol notes](docs/protocol.md) for the implementation and supported limits.
The official Windows/macOS updater remains the supported vendor alternative.

After backing up the pedal and passing `check`:

```sh
python3 -m mx5_update flash ./firmware/Update.img \
  --serial YOUR_USB_SERIAL
```

This command starts immediately, without a typed confirmation or interactive
terminal requirement. Back up first; keep external power and USB connected,
and prevent computer suspend throughout the update.

The tool validates the whole bundle and decompresses all payloads before
mutating the device. It then:

1. Sends the vendor's compatibility unlock command.
2. Writes `splash`, `recoverysplash`, and `rootfs` in bundle order.
3. Erases only the rootfs partition, and only after it reports `ext4`.
4. Downloads each complete raw image and requires an acknowledgment for every
   transfer and flash.
5. Sends **`reboot` only after all three writes are acknowledged**, matching
   the official updater's successful completion sequence.

It never sends commands to format user data, change the partition table,
or update the bootloader. It never reboots after a failed erase, download,
or flash. After successful reboot, check v2.7 in Global Settings.
An acknowledgment means the bootloader accepted the write; this is not a
read-back verification. See the [official-updater audit](docs/native-updater-audit.md)
for the comparison and first-boot data-preservation caveats.

If a write fails, **do not reboot or power off** the pedal. Keep it in update
mode and recover using the official updater. Failed transfers/commands are not
retried and there is no resume logic. Successful short payload writes continue
from the transferred offset, matching the vendor implementation. Avoid suspend,
disconnects, hubs, and power interruption.

If all three writes succeeded but reboot was not acknowledged, the CLI reports
that separate condition. The device may have disconnected to reboot; check its
display/state before acting. Do not automatically reflash.

### Limitations

- Only the exact official MX5 v2.7 bundle is supported.
- Transfers use complete raw images, not split Android sparse images.
  The tested pedal reports a `0x70000000` download limit, sufficient for the
  300 MiB rootfs. Smaller limits are refused before unlocking.
  Static analysis confirms that the official updater also uses raw transfers
  when an image fits; sparse framing is only its overflow path.
- If `max-download-size` is unsupported, the vendor updater's initial 512 MiB
  default is used; this fallback has not been validated on other bootloaders.
- No on-device firmware signature verification or post-write read-back is
  implemented. Do not use firmware from untrusted sources.
- No bootloader flashing, factory reset, partition-table edits, downgrade
  guarantees, or support for other HeadRush models.
- Like the vendor updater, each valid progress response resets the full
  response timeout. A device that keeps reporting progress can keep the updater
  waiting; there is deliberately no whole-operation deadline.

## Development

```sh
python3 -m unittest discover -s tests -v
```

Tests use synthetic containers and fake USB transports. They never touch
hardware or require proprietary firmware. Firmware binaries are not committed
to this repository; the Nix firmware derivation downloads them on demand.
This is an independent project, not affiliated with or supported by HeadRush
or inMusic.
