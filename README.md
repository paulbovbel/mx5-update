# mx5-update

Flash HeadRush MX5 firmware from Linux, without Windows or Wine. Supports the
exact official **MX5 v2.7** bundle, optionally patched with
[MX-Edit Bridge](https://github.com/TicT4x/MX-Edit) and
[NAM](https://github.com/lolgab/mods-for-legacy-headrush).

Independent project, not supported by HeadRush or inMusic. Fastboot has passed
read-only device checks; the current flashing sequence and mod combinations
have **not been hardware-tested**. Other devices and firmware are unsupported.

## Before flashing

- Back up rigs, setlists, presets, loops and impulse responses.
- Use the MX5 power supply and a reliable USB data cable. Prevent computer suspend.
- Enter **⋯ → Global Settings → ⋯ → Firmware Update → OK** on the pedal.
- Connect only one Fastboot device and complete the
  [read-only checks](docs/flashing.md#read-only-checks): power must be `ac`,
  rootfs `ext4`, and the download limit at least 300 MiB.

**All flasher commands write immediately, without confirmation. An interrupted
or incorrect update can leave the pedal unbootable.**

## Nix

Requires Linux and Nix with flakes enabled. Nix supplies the tools and downloads
the official firmware; no manual download or Python installation is needed.

```sh
git clone https://github.com/paulbovbel/mx5-update.git
cd mx5-update
nix build .#firmware --out-link firmware-result
```

Inspect `firmware-result/share/mx5-update/manifest.json` and complete the runbook
checks. Use `nix run .#fastboot -- …` for its Fastboot commands. Then flash stock:

```sh
nix run .#flash
```

### Optional mod profiles

Stock remains the default. Choose a build output and its matching flasher:

| Firmware | Build output | Flasher app |
| --- | --- | --- |
| Stock | `firmware` | `flash` |
| MX-Edit bridge | `firmware-bridge` | `flash-bridge` |
| NAM, 2 instances | `firmware-nam` | `flash-nam` |
| NAM + bridge, 2 instances | `firmware-nam-bridge` | `flash-nam-bridge` |
| NAM, up to 4 instances | `firmware-nam-4` | `flash-nam-4` |
| NAM + bridge, up to 4 instances | `firmware-nam-bridge-4` | `flash-nam-bridge-4` |

Stock and bridge builds support x86_64 and aarch64 Linux. **NAM builds require
x86_64 Linux** because of the pinned ARM cross-toolchain. No Docker is needed.

For example, build NAM + bridge without accessing USB:

```sh
nix build .#firmware-nam-bridge --out-link firmware-nam-bridge-result
cat firmware-nam-bridge-result/share/mx5-update/manifest.json
```

After backups and the runbook checks, flash that exact build:

```sh
./firmware-nam-bridge-result/bin/mx5-flash-nam-bridge
```

Important differences:

- **NAM replaces Anxiety OD in every rig.** Four-instance builds also replace
  Anxiety OD V2; two-instance builds leave V2 intact. Put `.nam` models in the
  device's `NAM` folder following the [upstream instructions](https://github.com/lolgab/mods-for-legacy-headrush#loading-models).
  Pedalboard-only additive pedals, reverb and page-turner mods are not enabled.
- **Bridge enables live USB-MIDI editing.** Run MX-Edit separately; its GUI is
  not bundled here. The bridge permits unauthenticated root shell commands over
  USB MIDI, so connect only trusted computers/software.
- Mod outputs contain raw images, a provenance manifest and a build-specific
  flasher, not a repacked `Update.img`. Keep each build's images and flasher
  together; filesystem timestamps can change hashes between rebuilds.

## Native Python / pip

For stock firmware without Nix, install Python 3.11+, Git, Bash, coreutils,
Android `fastboot` and 7-Zip (`7zz` or `7z`). On recent Debian/Ubuntu:

```sh
sudo apt install git python3-venv fastboot 7zip
git clone https://github.com/paulbovbel/mx5-update.git
cd mx5-update
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
```

Download **HeadRush MX5 – Firmware Updater v2.7.0 (Win)** from the
[official downloads page](https://www.headrushfx.com/downloads.html), then:

```sh
mx5-extract-firmware \
  "$HOME/Downloads/HeadRush MX5 2.7 Firmware Updater - Win.exe.zip" \
  --output ./firmware
```

Extraction never executes the EXE or accesses USB, and refuses existing output
directories. After backups and the runbook checks:

```sh
mx5-flash ./firmware
```

## Validation and recovery

The builder validates pinned stock firmware, applies selected mods in
**NAM → bridge** order, checks filesystem integrity and file read-back, and
records source revisions and hashes. NAM libraries are checked for ARM32
hard-float and glibc requirements no newer than the device's 2.32.
These checks establish build integrity, not hardware safety.

Flashers verify embedded image hashes and the MX5's USB identity (`0763:301a`),
then write only `splash`, `recoverysplash` and `rootfs`. They do not trust runtime
manifests. **Power, partition and buffer checks remain manual.** There is no
post-write read-back, automatic retry/resume, bootloader flashing or factory reset.
Verify v2.7 in Global Settings after startup.

If a write fails, **keep the pedal powered in update mode; do not reboot or
retry blindly**. Use the official Windows/macOS updater for recovery. A failed
reboot acknowledgement is reported separately; check the pedal before acting.
To return to stock, enter update mode and use the stock flashing path.
If normal startup fails, upstream documents **footswitches 1 + 2 at power-on**
for recovery mode. **2 + 3 is a factory reset that erases rigs.**

Firmware is proprietary, downloaded from the vendor and built locally with
substitution disabled. It is not committed here; no redistribution rights are granted.
See the [runbook](docs/flashing.md), [protocol notes](docs/protocol.md) and
[updater audit](docs/native-updater-audit.md) for details.

## USB permissions

Update mode uses `0763:301a` (often named `Miniboard`); normal audio mode
`0763:401a` cannot be flashed. For permission errors on a systemd/udev desktop,
an administrator can add `/etc/udev/rules.d/70-headrush-mx5.rules`:

```udev
SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="0763", ATTR{idProduct}=="301a", TAG+="uaccess"
```

Reload udev rules and reconnect. NixOS users should declare the equivalent rule
in their system configuration. **Do not run the updater as root.**

## Development

```sh
nix develop --command python -m unittest discover -s tests
nix develop --command ruff check .
nix develop --command shellcheck scripts/mx5-flash
nix flake check
```

Tests never access hardware. Flake checks also build every supported firmware
profile for the host system. Python has no third-party runtime dependencies;
without Nix, run tests with `python3 -m unittest discover -s tests`.

The mod pipeline is in `mx5_update/compose.py`, with adapters in
`mx5_update/mods/` and pinned sources/tools in `nix/mods/`. Profiles are explicit
adapter sequences, not dynamically loaded plugins. Upstream mod source pins live
in `mx5_update/mods/sources.json`, read by Nix for fetching and Python for
provenance. Nix owns fetching, tool builds, dependencies and packaging; Python
owns patch ordering, application, validation and artifact publication. Build-only
dependencies (such as NAM's compiler and libraries) remain pinned in Nix.
Filesystem operations and
artifact generation are shared; Fastboot flashing remains a separate shell script.
