# mx5-update

Update HeadRush MX5 firmware from Linux, without Windows or Wine.
Python validates and extracts the firmware. A short shell script runs the
standard Android `fastboot` commands documented in the [flashing runbook](docs/flashing.md).

**Supported firmware: the exact official MX5 v2.7 bundle.** A successful update
was reported with the earlier direct-USB backend. The shell sequence has offline
tests; the Fastboot CLI has passed read-only checks but has not reflashed hardware.
Other models, firmware versions, and hardware revisions are not validated. This is an independent
project, not supported by HeadRush or inMusic.

## Before you start

1. Back up all rigs, setlists, presets, loops, and impulse responses.
2. Connect the MX5's external power supply and a reliable USB data cable.
   Keep power and USB connected, and prevent computer suspend during flashing.
3. On the pedal, select **⋯ → Global Settings → ⋯ → Firmware Update → OK**.

Choose **one** installation method below. Connect only one Fastboot device;
`mx5-flash` discovers its serial automatically and verifies the MX5 USB identity.
**`mx5-flash` writes immediately, without a confirmation prompt.**

## Option 1: native Python / pip

### Install

You need Linux, Python 3.11+, Git, Bash, `sha256sum` (coreutils), Android SDK
Platform-Tools (`fastboot`), and 7-Zip (`7zz` or `7z`).
Install these with your distribution's package manager.
For example, on a recent Debian/Ubuntu system:

```sh
sudo apt install git python3-venv fastboot 7zip
```

Install the Python package in a virtual environment:

```sh
git clone https://github.com/paulbovbel/mx5-update.git
cd mx5-update
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
```

This installs `mx5-extract-firmware` (validated extraction) and `mx5-flash` (shell script).
There are no third-party Python runtime dependencies.
Reactivate `.venv` when returning in a new shell.

### Download and extract firmware

Download **HeadRush MX5 – Firmware Updater v2.7.0 (Win)** from the
[official downloads page](https://www.headrushfx.com/downloads.html), then:

```sh
mx5-extract-firmware \
  "$HOME/Downloads/HeadRush MX5 2.7 Firmware Updater - Win.exe.zip" \
  --output ./firmware
```

The EXE is extracted, never executed. The new `firmware` directory contains
the validated `Update.img`, three decompressed partition images, a JSON manifest,
and `SHA256SUMS`.
Existing output directories are never overwritten.

### Check and update

```sh
fastboot devices
SERIAL=$(fastboot devices | cut -f1)
fastboot -s "$SERIAL" getvar power-source
fastboot -s "$SERIAL" getvar partition-type:rootfs
fastboot -s "$SERIAL" getvar max-download-size
```

Verify the responses and other prerequisites in the
[runbook](docs/flashing.md#read-only-checks) before proceeding. Power must be `ac`,
rootfs must be `ext4`, and the download limit must be at least 300 MiB.

```sh
mx5-flash ./firmware
```

## Option 2: Nix

You need Linux and Nix with flakes enabled. Nix supplies Python, Fastboot, 7-Zip,
and the firmware; no pip installation or manual firmware download is needed.
Packages are available for `x86_64-linux` and `aarch64-linux`.

```sh
git clone https://github.com/paulbovbel/mx5-update.git
cd mx5-update
nix build .#firmware --out-link firmware-result
nix run .#fastboot -- devices
SERIAL=$(nix run .#fastboot -- devices | cut -f1)
nix run .#fastboot -- -s "$SERIAL" getvar power-source
nix run .#fastboot -- -s "$SERIAL" getvar partition-type:rootfs
nix run .#fastboot -- -s "$SERIAL" getvar max-download-size
```

The firmware build downloads the official ZIP from HeadRush's CDN, checks its
pinned SHA-256, extracts it without executing Windows code, and validates the
firmware and the flashing script's raw-image pins. To inspect its metadata:

```sh
cat firmware-result/share/mx5-update/manifest.json
```

After verifying the [runbook checks](docs/flashing.md#read-only-checks) and backing up:

```sh
nix run .#flash
```

Optional build outputs:

```sh
nix build .                         # result/bin/{mx5-extract-firmware,mx5-flash}
ls firmware-result/share/mx5-update # Bundle, raw images, manifest
nix run .#extract-firmware -- /path/to/updater.zip --output ./firmware # Optional local extraction
```

Firmware is proprietary and fetched from the vendor, not committed here.
The flake allows only this named unfree firmware package and disables
substitution for its extraction derivation; this grants no redistribution rights.

## What to expect

`mx5-extract-firmware SOURCE --output DIRECTORY` never accesses USB. Device checks are explicit
Fastboot commands in the runbook, not Python code.

`mx5-flash` checks the three raw images against embedded SHA-256 pins and
requires exactly one Fastboot device, whose detected serial must match one USB
`0763:301a` device in sysfs. It does not trust
a supplied manifest. **Power, partition, and buffer checks are manual**—complete
the runbook first. The script writes only `splash`, `recoverysplash`, and `rootfs`,
then sends `reboot` after all writes succeed. After startup, verify **v2.7**
in Global Settings.

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

If Fastboot reports a permission error on a systemd/udev desktop, an
administrator can add:

```udev
# /etc/udev/rules.d/70-headrush-mx5.rules
SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="0763", ATTR{idProduct}=="301a", TAG+="uaccess"
```

Reload udev rules and reconnect the cable. NixOS users should declare the
equivalent udev rule in their system configuration. Do not run the updater as root.

## Development

```sh
python3 -m unittest discover -s tests -v
# Or with the Nix development environment:
nix develop --command python -m unittest discover -s tests -v
nix develop --command ruff check .
nix develop --command shellcheck scripts/mx5-flash
nix flake check
```

Unit tests use synthetic firmware, sysfs fixtures, fake Fastboot, and both real
and fake checksum tools; they never touch hardware. Flake checks also
download/extract the pinned firmware, verify the script's pins against the raw
images, and smoke-test the packaged commands without accessing USB. Pip CI
checks the installed package for removed modules and exercises its entry point
on synthetic firmware outside the source tree.

Fastboot owns USB framing, partial transfers, acknowledgments, and timeouts.
There is no custom Python Fastboot backend or process supervisor.
