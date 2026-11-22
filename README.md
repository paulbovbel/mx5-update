# mx5-update

Update HeadRush MX5 firmware from Linux, without Windows or Wine.
The tool talks directly to the pedal's Fastboot interface through libusb.

**Supported firmware: the exact official MX5 v2.7 bundle.** A successful update
has been reported on an MX5; other models, firmware versions, and hardware
revisions are not validated. This is an independent project, not supported by
HeadRush or inMusic.

## Before you start

1. Back up all rigs, setlists, presets, loops, and impulse responses.
2. Connect the MX5's external power supply and a reliable USB data cable.
   Keep power and USB connected, and prevent computer suspend during flashing.
3. On the pedal, select **⋯ → Global Settings → ⋯ → Firmware Update → OK**.

Choose **one** installation method below. In either workflow, replace
`YOUR_USB_SERIAL` with the serial printed by `probe`.
**`flash` writes immediately, without a confirmation prompt.**

## Option 1: native Python / pip

### Install

You need Linux, Python 3.11+, Git, the libusb-1.0 shared library, and
7-Zip (`7zz` or `7z`). Install these with your distribution's package manager.
For example, on a recent Debian/Ubuntu system:

```sh
sudo apt install git python3-venv libusb-1.0-0 7zip
```

Install the Python package in a virtual environment:

```sh
git clone https://github.com/paulbovbel/mx5-update.git
cd mx5-update
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
```

The installed command is `mx5-update`; there are no third-party Python runtime
dependencies. Reactivate `.venv` when returning in a new shell.

### Download and extract firmware

Download **HeadRush MX5 – Firmware Updater v2.7.0 (Win)** from the
[official downloads page](https://www.headrushfx.com/downloads.html), then:

```sh
mx5-update extract \
  "$HOME/Downloads/HeadRush MX5 2.7 Firmware Updater - Win.exe.zip" \
  --output ./firmware
```

The EXE is extracted, never executed. The new `firmware` directory contains
the validated `Update.img`, three decompressed partition images, and a manifest.
Existing output directories are never overwritten.

### Check and update

```sh
mx5-update probe
mx5-update check ./firmware/Update.img --serial YOUR_USB_SERIAL
```

After `check` passes and you have a backup:

```sh
mx5-update flash ./firmware/Update.img --serial YOUR_USB_SERIAL
```

## Option 2: Nix

You need Linux and Nix with flakes enabled. Nix supplies Python, libusb, 7-Zip,
and the firmware; no pip installation or manual firmware download is needed.
Packages are available for `x86_64-linux` and `aarch64-linux`.

```sh
git clone https://github.com/paulbovbel/mx5-update.git
cd mx5-update
nix run . -- probe
nix run . -- check --serial YOUR_USB_SERIAL
```

The first run downloads the official ZIP from HeadRush's CDN, checks its pinned
SHA-256, extracts it without executing Windows code, and validates the firmware.
The packaged CLI uses this `Update.img` in the Nix store by default.

After `check` passes and you have a backup:

```sh
nix run . -- flash --serial YOUR_USB_SERIAL
```

Optional build outputs:

```sh
nix build .                         # result/bin/mx5-update
nix build .#firmware --out-link firmware-result
ls firmware-result/share/mx5-update # Bundle, raw images, manifest
```

Firmware is proprietary and fetched from the vendor, not committed here.
The flake allows only this named unfree firmware package and disables
substitution for its extraction derivation; this grants no redistribution rights.

## What to expect

`probe` and `check` are read-only; they never unlock, erase, flash, or reboot.
`extract`, `inspect`, and `plan` never access USB. Use `--help` for all commands.

`flash` validates the whole bundle and checks the selected device, external
power, partition types, and transfer limits before writing. It writes only
`splash`, `recoverysplash`, and `rootfs`, then sends `reboot` after all three
writes are acknowledged. After startup, verify **v2.7** in Global Settings.

If a write fails, **keep the pedal powered in update mode; do not reboot or
retry blindly**. Recover with the official Windows/macOS updater. If only the
reboot acknowledgment fails, the CLI reports that separately; check the pedal's
display/state before acting.

There is no post-write read-back verification, automatic retry/resume, sparse
transfer support, bootloader flashing, or factory reset. An interrupted update
can leave the pedal unbootable. See the [protocol notes](docs/protocol.md) and
[official-updater audit](docs/native-updater-audit.md) for details.

## Troubleshooting USB access

Update mode uses USB `0763:301a`, often named `Miniboard`; normal audio mode
(`0763:401a`) cannot be flashed.

For `LIBUSB_ERROR_ACCESS` on a systemd/udev desktop, an administrator can add:

```udev
# /etc/udev/rules.d/70-headrush-mx5.rules
SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="0763", ATTR{idProduct}=="301a", TAG+="uaccess"
```

Reload udev rules and reconnect the cable. NixOS users should declare the
equivalent udev rule in their system configuration. Do not run the updater as root.

For native Python installations where libusb is not discovered automatically,
set `MX5_LIBUSB=/absolute/path/to/libusb-1.0.so`. The Nix package sets it for you.

## Development

```sh
python3 -m unittest discover -s tests -v
# Or with the Nix development environment:
nix develop --command python -m unittest discover -s tests -v
nix develop --command ruff check .
nix flake check
```

Unit tests use synthetic firmware and fake USB transports; they never touch
hardware. Flake checks also download/extract the pinned firmware and smoke-test
the packaged CLI, without accessing USB.
