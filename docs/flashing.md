# MX5 v2.7 flashing runbook

Use this runbook after extracting the official firmware with `mx5-extract-firmware SOURCE --output DIRECTORY`,
or use the Nix package's automatically downloaded firmware.
Only an MX5 and the pinned official v2.7 images are supported.

## Prerequisites

- Back up all rigs, setlists, presets, loops, and IRs.
- Connect the pedal's external power supply and a reliable USB data cable.
- Prevent computer suspend. Do not interrupt power or USB during writes.
- On the MX5: **⋯ → Global Settings → ⋯ → Firmware Update → OK**.
- Have `fastboot` on PATH. With Nix, enter `nix develop` for the checks below,
  or replace each `fastboot` invocation with `nix run .#fastboot --`.

The Python tool only prepares files; it never accesses the pedal.
The shell script deliberately does not parse Fastboot output or infer readiness.
You must verify the checks below before running it.

## Read-only checks

List devices and capture the MX5's serial. **Stop if the list is empty or shows
more than one device**; disconnect other Fastboot devices before proceeding:

```sh
fastboot devices
SERIAL=$(fastboot devices | cut -f1)
fastboot -s "$SERIAL" getvar version-bootloader
fastboot -s "$SERIAL" getvar power-source
fastboot -s "$SERIAL" getvar partition-type:rootfs
fastboot -s "$SERIAL" getvar max-download-size
```

Verify the **printed responses**, not just exit codes: some Fastboot versions
return zero even when a `getvar` query fails.

| Check | Required response | Observed MX5 response |
| --- | --- | --- |
| Bootloader | Successful version response | `0.4` |
| Power source | Exactly `ac` | `ac` |
| Root filesystem | Exactly `ext4` | `ext4` |
| Download limit | At least `314572800` bytes (`0x12c00000`, 300 MiB) | `0x70000000` |

Stop if a required query fails or the value is unexpected. Do not guess a buffer
limit or proceed on battery power.

Fastboot may query Android slot/logical-partition properties while flashing.
Confirm that none report `yes`:

```sh
for partition in splash recoverysplash rootfs; do
  fastboot -s "$SERIAL" getvar "has-slot:$partition"
  fastboot -s "$SERIAL" getvar "is-logical:$partition"
done
```

These optional queries returned unsupported-variable failures on the tested MX5;
that is expected. A response of `yes` is not supported by this workflow.

## Flash

**This starts immediately; there is no confirmation prompt.**

For a pip installation, point to the extraction directory, not `Update.img`:

```sh
mx5-flash ./firmware
```

For Nix, the packaged script defaults to the validated firmware in the store:

```sh
nix run .#flash
```

The script checks all three raw images against embedded SHA-256 pins before
unlocking. It discovers the serial from `fastboot devices`, requiring exactly
one device, then verifies that serial against exactly one USB `0763:301a` device
in sysfs. Empty, ambiguous, malformed, unrelated, or network targets are rejected.
An existing or edited local `SHA256SUMS` cannot override the embedded pins.

For review, this is the command sequence in
[`scripts/mx5-flash`](../scripts/mx5-flash), executed from the validated image
directory under Bash's fail-fast `set -Eeuo pipefail`:

```sh
fastboot -s "$SERIAL" oem inmusic-unlock-magic-7de5fbc22b8c524e
fastboot -s "$SERIAL" -S 0 --skip-reboot flash splash splash.img
fastboot -s "$SERIAL" -S 0 --skip-reboot flash recoverysplash recoverysplash.img
fastboot -s "$SERIAL" erase rootfs
fastboot -s "$SERIAL" -S 0 --skip-reboot flash rootfs rootfs.img
fastboot -s "$SERIAL" reboot
```

Do not execute later commands individually after an earlier command fails.
The script does not ignore OEM unlock errors or retry failed writes.
It does not erase user data, change partition tables, or flash the bootloader.
`-S 0` leaves the target download limit in effect; the manual buffer check ensures
each complete raw image fits without requiring sparse splitting.

## Completion and failure handling

- **All writes and reboot succeed:** wait for startup and verify **v2.7** in
  Global Settings. A bootloader acknowledgment is not a read-back verification.
- **An erase or flash fails:** the script stops without sending reboot. Keep the
  pedal powered in update mode and recover with the official Windows/macOS
  updater. Do not power-cycle or automatically retry.
- **Only reboot fails:** all firmware writes completed, but the device may have
  disconnected to reboot before acknowledgment. Inspect its display/state
  before taking further action. Do not automatically reflash.
- **Fastboot waits for a device:** it can wait indefinitely. Stop the waiting
  command before reconnecting or starting another update; do not leave a pending
  flash to resume unexpectedly. If writes already began, keep the pedal powered.
- **A read-only query hangs despite a visible serial:** stop pending commands
  first. If no writes have begun, reconnect USB while keeping the pedal powered,
  confirm update mode, and repeat the checks. `fastboot devices` only proves
  enumeration, not that the bootloader responds. Do not proceed to flashing
  while queries fail. For diagnosis, bound a read-only query with
  `timeout 10s fastboot -s "$SERIAL" getvar power-source` (or
  `timeout 10s nix run .#fastboot -- -s "$SERIAL" getvar power-source`). Exit
  status `124` means it timed out; a first Nix evaluation/build can also consume
  that limit, so run `nix run .#fastboot -- --version` first. Do not apply a
  short timeout to writes.

There is no Python subprocess supervision, automatic resume, or rollback.
Operator checks and standard Fastboot behavior replace those abstractions.

## Validation status

Firmware v2.7 was successfully installed using this project's earlier
direct-USB implementation. Read-only checks passed with Fastboot 35.0.2 and
the Nix-packaged Fastboot. The shell script is tested offline for checksum
failures, device identity, exact command order, failure at every write step,
and success-only reboot. This new shell workflow has not reflashed hardware.

See [protocol notes](protocol.md) and the
[historical vendor-updater audit](native-updater-audit.md) for the reverse
engineering behind this sequence.
