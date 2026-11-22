# Comparison with the official MX5 v2.7 updater

> Historical audit of the former direct ctypes/libusb backend. The current
> implementation is a firmware-only Python helper plus a shell runbook using
> the Android Fastboot CLI; see [the current implementation notes](protocol.md#implementation-and-hardware-validation).
> The binary analysis below still informs the MX5-specific write sequence,
> but its direct-USB timing/transport comparisons are not claims about the CLI.

## Scope and confidence

Static analysis of the official Windows `FirmwareUpdater.exe`, SHA-256
`92f939cd372f589d0f002a215ecf7a37f0a5e3ec85d0a04a4759355763f4daad`,
and its bundled `Config.json` and `Update.img`.
Addresses below are x86-64 virtual addresses in that EXE.

The comparison follows the GUI update worker, image dispatcher, XZ transfer
path, Fastboot backend function table, command framing, erase/flash routines,
and success/error exits. This is not a captured successful official update,
nor an audit of the pedal's bootloader implementation. No mutating commands
were sent to the connected pedal.

## Findings by risk

### 1. Raw versus sparse transfer: raw is an official path

The earlier concern that the official updater necessarily uses sparse
transfers on this MX5 was too strong.

The Fastboot backend table begins at `0x14024e060`. Offset `+0x38` points to
the streaming-image writer at `0x1401209c0`. The XZ image path at
`0x14011b5c0` obtains the decompressed size and invokes that writer at
`0x14011b823`.

At `0x1401209d9`, the writer compares the decompressed size with the device
context's download limit:

- If it fits: optionally erase, initiate one download, stream raw data, then
  flash the partition.
- If it exceeds the limit: branch at `0x1401209dd` to `0x140120aaf`, which
  invokes the sparse/splitting machinery at `0x1401201d0`.

The direct in-memory image writer at `0x140120890` has the same fit/overflow
decision (`0x1401208a9`).

Fastboot initialization at `0x14011fa48` sets a 512 MiB initial limit. The
largest image here is exactly 300 MiB. Our independent read-only query also
reported a larger device limit, `0x70000000`. Thus the complete raw transfer
used by this project matches the official writer's fitting-image path.
Sparse support is not required merely because the device advertises it.

This establishes static protocol agreement, not proof that our implementation
has performed a successful hardware write.

### 2. Preparation and finalization: unlock and successful reboot match

Initialization at `0x14011f9e0` sends:

```text
oem inmusic-unlock-magic-7de5fbc22b8c524e
```

The native updater accepts the exact compatibility errors `unknown oem command`
and `unrecognized command`. Our unlock handling does the same.

Our read-only preflight occurs before unlocking. The native library performs
the unlock during its write-capable device initialization. This extra
read-only preflight is intentional; the queried values were accessible on the
tested device without unlocking.

The GUI worker calls the image-update routine at `0x140103f94`. Its success
path optionally erases the `data` partition only if the
`eraseDataPartition` setting is enabled (`0x14010404b`–`0x140104073`).
The worker's data-erase state initializes to false at `0x1401037f3`; the
shipped Config.json has no `eraseDataPartition` entry.

The normal success path then invokes backend offset `+0x60` with argument
zero (`0x140104140`–`0x140104156`). That points to `0x140120bd0`, which sends
**`reboot`**, not a hidden commit/finalization command.

The initial implementation stopped in update mode instead. Following this
audit, it sends the same `reboot` command only after all three partition writes
are acknowledged. It never sends reboot after a failed erase/download/flash.
Missing reboot acknowledgment is reported separately from failed firmware
writes, without retrying either action.

Bootloader/partition-table operations are conditional on corresponding image
types or the `uboot` partition name in `0x14011a600`. This exact bundle has
only normal `splash`, `recoverysplash`, and `rootfs` images. No additional
bootloader image or partition-table operation is indicated for it.

### 3. Erased rootfs / interruption: a real risk shared with the official updater

The erase helper at `0x14011fab0`:

1. Queries `getvar:partition-type:<partition>`.
2. Erases only when the successful response equals `ext4`.
3. Uses a 300-second timeout for that erase.

The fitting streaming writer calls this helper at `0x140120a0d`, before
initiating the download at `0x140120a20`. The ordinary fitting writer has
the same ordering at `0x1401208dd` and `0x1401208f0`.

Our implementation likewise erases rootfs before downloading it. It does
not erase the splash partitions on the tested device, since those type
queries explicitly fail. Its whole-bundle validation and decompression
complete before the first mutating command.

There is no A/B or transactional update sequence visible in this bundle's
host-side path. If power/USB/process failure occurs after erasing rootfs, the
normal system can remain incomplete. The official updater is not immune to
this risk. Bootloader accessibility after such a failure is not established
by the host EXE.

### 4. Read-back verification: not present in the inspected native host path

The download starter at `0x14011fc70` checks that the returned `DATA` length
equals the requested length. After payload transfer, `0x14011fdf0` reads the
download completion response, then sends `flash:<partition>` and waits for
the result. Our protocol uses the same exchanges.

Host-side SHA-1 verification at `0x14011db00` operates on the firmware's
inline data and expected hash. It is not a post-write read of the flash.
After the normal image loop, the GUI success path proceeds to optional data
erase and reboot; it does not retrieve and compare partition contents.

No host-side post-write checksum/read-back exchange was found in this normal
path. Our absence of read-back is therefore not a demonstrated regression
against the official host updater. The bootloader may perform internal checks;
those cannot be inferred from `OKAY` or from this host-only audit.

### 5. Recovery and rollback: not guaranteed by either host program

Image write failures propagate out of the image loop. In the GUI worker,
the error branch after `0x140103fa2` goes to failure handling, not the
success-only data-erase/reboot path.

The inspected host path does not restore the old rootfs or retry a failed
flash transaction automatically. Our stop-on-error behavior agrees in that
respect. The official updater remains the better recovery tool, but static
host analysis does not establish that every interruption is recoverable.

### 6. User presets: no explicit data erase in the normal update, but back up

Our code never sends `erase:data`, format, bootloader-write, or partition-table
commands. The official GUI's optional data erase is disabled by default
for this configuration, as described above.

The extracted rootfs also mounts a separate internal filesystem at
`/media/az01-internal`, using
`/etc/systemd/system/media-az01\x2dinternal.mount`.
Its prerequisite `az01-internal-mkfs.service` invokes
`/usr/sbin/az01-internal-mkfs`; that script runs `e2label` on the internal
partition and **formats it if that check exits with status 1**.

This is shipped firmware behavior, not an updater command, and does not mean
a normal update necessarily formats anything. It does mean that “we never
erase data” cannot be turned into a guarantee that user data survives every
failure or first-boot condition. Application-level migrations have not been
audited. Backups remain mandatory.

## Transport and completion behavior after remediation

The audit originally found short-write, timeout, and reboot differences.
They have now been addressed and covered by simulated transport tests:

| Area | Official updater | Direct-USB implementation at time of audit |
| --- | --- | --- |
| Successful short payload writes | Continues from the actual transferred offset at `0x14011ff82`–`0x14011ffb0` | Continues from the actual transferred offset |
| Payload chunk size | At most 1 MiB (`0x14011fefa`), also used by XZ buffers | 1 MiB |
| Payload transfer timeout | 5 seconds per libusb transfer (`0x14011ff63`) | 5 seconds per libusb transfer |
| Response timing | Starts another read with the full timeout after each `INFO` (`0x14011f650`) | Same; no whole-response deadline or progress-packet cap |
| Erase and flash timeout | 300 seconds per response read | 300 seconds per response read |
| Completion | Sends `reboot` automatically on normal success | Sends `reboot` only after all three writes are acknowledged |
| External-power policy | Generic check understands exact `ac`/`battery`; shipped config sets `allowUpdateOnBattery: true` | Requires an allowlisted external-power value |
| Download limit | Fastboot initialization sets 512 MiB | Queries device; falls back to 512 MiB; current supported payloads are all smaller |
| Sparse overflow | Implemented | Refused before unlocking |

Continuation applies only to successful short **payload** writes. Fastboot
command packets are not fragmented; short command writes still abort.
Failed transfers, including timeouts reporting partial progress, are not retried.
Zero-progress or impossible byte counts fail rather than spinning indefinitely.

The response loop now mirrors the vendor's inactivity timeout rather than
aborting an operation that is still producing progress messages. Like the
vendor, it can keep waiting while valid progress continues.

Tests for the former backend covered ctypes buffer offsets using a fake libusb call, partial
transfer errors without retries, per-transfer timeouts, more than 1024 progress
packets, the complete simulated Fastboot wire sequence, success-only reboot,
failure at every write stage, and uncertain reboot acknowledgment. These tests
did not require or modify hardware. Those transport-specific tests and the
subsequent Python CLI adapter have since been removed. Current tests cover the
shell runbook's checksums, sysfs identity, command order, and failure paths.

## Bottom line

For the pinned v2.7 payload, static analysis supports the core raw-transfer,
unlock, conditional erase, and flash sequence. The original raw-versus-sparse
warning is substantially resolved. There is no evidence in this normal path
of a missing mandatory vendor commit or read-back command.

After the audit and transport/completion fixes, a user reported a successful
MX5 firmware update to v2.7 using this implementation. This is a real hardware
result on one device, not validation of every hardware revision or recovery
scenario. It is also not a captured USB trace of an official update.
Intentional differences remain in safety preflight/power policy and refusing
unsupported sparse transfers.

The subsequent move to a standard Fastboot shell runbook has not yet been
validated with a hardware flash; the reported success applies to the earlier backend.
Power, partition type, and buffer-size verification are now explicit operator
steps, not automated Python preflight.

## Reproducing the inspection

After extracting the pinned updater, Rizin can inspect the relevant regions
without executing it or accessing USB:

```sh
rizin -A -q -c \
  'e scr.color=0; pxq 128 @ 0x14024e060; pd 110 @ 0x1401209c0; pd 80 @ 0x14011fab0' \
  FirmwareUpdater.exe
```

Additional useful regions: `0x140103e00` (GUI worker),
`0x14011a990` (orchestrator), `0x14011b5c0` (XZ streaming),
`0x14011f9e0` (unlock), `0x14011fc70` (download handshake),
`0x14011fdf0` (download result and flash), `0x14011fe90` (payload writes),
`0x14011f650` (response reads), and `0x140120bd0` (reboot).
