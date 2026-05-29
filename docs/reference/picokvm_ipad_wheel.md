# PicoKVM ↔ iPadOS wheel scrolling

Status: validated on iPad mini 7 (iPadOS, 1488×2266 portrait) connected via the
USB-C Digital AV Multiport Adapter to a Luckfox PicoKVM (firmware `kvm_app 2`,
unmodified gadget descriptors).

This note is the empirical answer to "does mouse-wheel scroll work on
PicoKVM-driven iPadOS?". The pre-2026-05-27 understanding (recorded in
`docs/design/ipad_mini_migration.md §5` and the `picokvm-scroll-overshoot-hardware-limit`
memory) was "no, wheelReport ACKs but doesn't move the sidebar — keep it
diagnostic". That conclusion was wrong; the corrected state is below.

## TL;DR

PicoKVM's existing `wheelReport` JSON-RPC scrolls iPadOS Settings sidebar
**as-is**. No descriptor change, no `kvm_app` patch, no PicoKVM firmware change
is required. glassbox can promote `scroll_strategy="wheel"` from diagnostic to
authoritative on the iPad profile.

There is one caveat — an unexplained one-time "activation" step that may be
needed on a fresh iPad ↔ PicoKVM pair. The recovery procedure (UDC bounce) is
below. Later latency probes showed wheel is already stable by t+3 s after the
bounce, so glassbox uses a 6 s settle by default.

## What was validated (2026-05-27)

All on the connected rig, against live iPadOS Settings split view, measuring
the sidebar pixel region `frame[65:1000, 640:820]` for visible scroll.

| Test | Result |
| ---- | ------ |
| Wheel-30 ticks via hidg1 RID 2 (raw HID write) across 3 fresh PicoKVM reboots | **9/9 scrolled**, sidebar max-pixel-diff = 255 each |
| Wheel-30 ticks via hidg2 standard 4-byte combined report (raw HID write) | scrolled, max-diff = 255 |
| `kvm_app` JSON-RPC `wheelReport {"wheelY": ±1}` × 30 | **scrolled both directions**, max-diff = 255 |
| `kvm_app` JSON-RPC `wheelReport` × 10 (batch typical of a single scroll step) | **scrolled**, max-diff = 255 |
| `kvm_app` JSON-RPC `wheelReport` × 1 (single tick) | max-diff ≈ 12 — visually not noticeable but accumulates |
| `kvm_app` `absMouseReport` click via hidg1 RID 1 alongside wheel | **clicks still register**, right-pane title changed |
| `vidpid_v2`: UDC bounce + probe at t+3/8/15/25 s for default VID/PID and Logitech VID/PID | **8/8 scrolled**; activation latency ≤3 s; VID/PID did not matter |
| `soak`: 8 alternating 30-tick trials across spaced idle gaps up to 5 min | **8/8 scrolled**, identical 213 px shifts; no decay over ~28 min |
| `decay_30min`: one UDC bounce + probes at t+0/5/15/30 min | **4/4 scrolled**, activation lifetime ≥30 min including ≥10 min idle gaps |

Raw probe scripts and snapshots are preserved locally under
`artifacts/wheel_probe_2026-05-27/` (gitignored evidence bundle).

The validation was on `hidg1 RID 2 wheel-only report` — i.e., the **existing**
PicoKVM path that `kvm_app:wheelReport` already drives. No change to gadget
descriptors was needed.

## Production-side action in glassbox

These are the minimum edits that flip the iPad profile from "wheel diagnostic
only" to "wheel authoritative" in glassbox.

1. `glassbox/effectors/picokvm/effector.py:_wheel_available()` — add iPad
   short-circuit so the iPad profile gets wheel without an explicit
   `GLASSBOX_PICOKVM_WHEEL_ENABLED=1`:
   ```python
   def _wheel_available(self) -> bool:
       return bool(self.config.wheel_enabled or self._is_ipad_target())
   ```
2. `glassbox/effectors/picokvm/effector.py:capabilities()` — when iPad wheel is
   on, set:
   - `scroll_strategy = "wheel"` (already conditional)
   - `scroll_strategy_validated = True` (was `False`)
   - `scroll_evidence = None` (was `"ack_only"`)
   - `wheel_diagnostic = False` (was `True`)
3. The historical "iPad wheel kept behind diagnostic flag" comments in
   `glassbox/effectors/picokvm/config.py:wheel_enabled` and `effector.py` class
   docstring should be reworded to point at this doc instead.
4. `docs/design/ipad_mini_migration.md §5` — leave the section but mark it as
   superseded by this doc.
5. Settings drill-down (skills/regression/ios_settings) now treats iPad wheel
   as a real root-coverage scroll path: when root scrolling appears stuck but
   required roots remain missing, iPad targets with wheel support get the same
   bounded root reset pass before search recovery. This consumer path is not
   yet production-proved: a 2026-05-27 live drill-down rerun with VLM disabled
   still entered only 5/17 required roots, so coverage improvement remains a
   follow-up for the Settings crawler rather than a PicoKVM wheel capability
   question.

## Single-tick is not visually noticeable; use 5-10+ tick batches

iPad's compositor smooths small wheel deltas. A single `wheelY=1` report
produces a sidebar pixel-diff around 12 — basically below the visual
threshold. Batches of 10 reliably scroll one row's worth; batches of 30 sweep
the visible area top-to-bottom.

For Settings drill-down, send wheel ticks in batches; calling
`wheelReport` once per row will undershoot. The existing
`PicoKVMEffector.scroll_wheel(ticks=N, interval_ms=40)` semantics work — just
pass `N >= 5`.

## The unexplained "activation" step

Earlier in the 2026-05-27 debugging session, raw HID wheel reports were
silently ignored by the same iPad — 7 different descriptor / interface
configurations were probed, all failed to scroll. After one experimental
gadget reconfiguration (UDC detach → modify hidg2 descriptor → reattach),
wheel started working — and continued to work across subsequent PicoKVM
**cold reboots** (3 verified), even after the descriptor was reverted to
factory. The first write-up used a guessed long post-bounce wait; the later
`vidpid_v2` run proved the wheel path was already stable at t+3 s, so the
production hook waits 6 s.

We could not cleanly isolate the trigger. Plausible explanations:

- iPad caches its initial classification of a USB HID gadget on first attach
  and only re-evaluates the wheel field on re-enumeration.
- iPad's USB pointer stack needs some wake/idle pattern that one of our test
  steps incidentally produced.
- Something else — Apple does not document this layer.

Empirically: once "activated", state persists across PicoKVM reboots (3 cold
cycles). What we **don't** know:

- Does the activation survive a physical USB-C unplug?
- Does it survive an iPad reboot?
- Does it survive long disconnection?

If the answer to any is "no", a fresh rig pairing will appear broken until
re-activated.

## Recovery procedure if wheel doesn't work on a new rig

If a freshly connected iPad does not scroll on PicoKVM wheel commands, force a
gadget re-enumeration:

```bash
ssh root@<picokvm.local> '
  echo "" > /sys/kernel/config/usb_gadget/kvm/UDC
  sleep 1
  echo "ffb00000.usb" > /sys/kernel/config/usb_gadget/kvm/UDC
  # wait until /dev/hidg1 exists and UDC state is configured
'
# wait 6 seconds, then retest wheel
```

Confirmed to wake iPad's wheel handling during the 2026-05-27 session. Cost:
~6 s setup; not required on already-activated rigs.

If even that doesn't help, a structural-descriptor change is on file as a
last-resort fallback (see "What was tried and turned out unnecessary" below).
We expect not to need it.

## glassbox-side automation

`PicoKVMEffector.connect()` now runs a one-shot UDC bounce when:
- `phone_model.startswith("ipad")`,
- iPad wheel is enabled by the profile, and
- the transient marker file on PicoKVM (`/tmp/glassbox_ipad_wheel_armed` by
  default) is missing.

After the bounce, glassbox waits until `/dev/hidg1` exists and the UDC state is
`configured`, writes the marker, then sleeps 6 s before continuing. Cost: ~6 s
plus a short readiness poll on the very first connect for a given PicoKVM boot.
After that, the marker short-circuits.

Default mode is `required`, so a failed SSH/UDC bounce makes PicoKVM connect
fail visibly instead of silently advertising validated iPad wheel support on a
cold rig. For diagnostics or known-hot rigs:

```bash
GLASSBOX_PICOKVM_IPAD_WHEEL_ACTIVATION=warn   # attempt but continue on failure
GLASSBOX_PICOKVM_IPAD_WHEEL_ACTIVATION=off    # skip activation entirely
```

### Prerequisite: SSH key on PicoKVM

The activation hook uses `ssh -o BatchMode=yes`, so the controller machine's
public key must be in PicoKVM's authorized keys before `connect()` can
succeed in `required` mode. The Luckfox PicoKVM (kvm_app 0.1.2, `sshd_config`
2026-05-27) has an **unusual `AuthorizedKeysFile`** — keys go to
`/userdata/openssh/.ssh/authorized_keys`, **not** the default
`/root/.ssh/authorized_keys`. Putting the key in the default path silently
won't help. Provision once per rig:

```bash
PUBKEY="$(cat ~/.ssh/id_rsa.pub)"   # or id_ed25519.pub
sshpass -p 'luckfox' ssh -o StrictHostKeyChecking=accept-new root@<picokvm.local> "
  mkdir -p /userdata/openssh/.ssh
  chmod 700 /userdata/openssh /userdata/openssh/.ssh
  grep -qF '$PUBKEY' /userdata/openssh/.ssh/authorized_keys 2>/dev/null || \
    echo '$PUBKEY' >> /userdata/openssh/.ssh/authorized_keys
  chmod 600 /userdata/openssh/.ssh/authorized_keys
"
ssh -o BatchMode=yes root@<picokvm.local> 'echo ok'   # smoke
```

The actual `AuthorizedKeysFile` path is in `/etc/ssh/sshd_config` line
starting `AuthorizedKeysFile` — verify on each new rig in case Luckfox changes
the firmware default.

## What was tried and turned out unnecessary

For future-archaeology — these were investigated in the same session and are
**not** the fix:

- Replacing `hid.usb2` descriptor with a Logitech mouse pattern (Report ID 2 +
  16 buttons + 12-bit X/Y rel + 8-bit wheel + AC Pan, 69 bytes). Initially
  believed to be the fix; after revert + clean reboot the original descriptor
  scrolled equally well. The Logitech mod was a red herring — the descriptor
  change happened to also force re-enumeration, which is what actually
  activated wheel.
- Adding a Wheel field to `hid.usb1` Report ID 1's abs-mouse report: iPad
  rejects the modified gadget (USB `state=not_attached`). Do not pursue.
- Removing `hid.usb1` entirely so iPad sees only `hid.usb2` as a mouse
  interface: wheel still did not fire on the cold-state iPad. The "interface
  ordering" hypothesis was disproved.

## Current PicoKVM gadget layout (reference, unchanged)

For posterity — gadget on this PicoKVM as of 2026-05-27 (VID `0x1d6b` / PID
`0x0104`, `manufacturer=KVM`, `product=USB Emulation Device`):

| Interface | dev node | Format | Used by |
| --- | --- | --- | --- |
| `hid.usb0` | `/dev/hidg0` | Boot Keyboard (8 byte) | `kvm_app.keyboardReport`; typing |
| `hid.usb1` | `/dev/hidg1` | Mouse: RID 1 abs (6 B) + RID 2 wheel-only (2 B) | `kvm_app.absMouseReport` (clicks) + `kvm_app.wheelReport` (wheel) |
| `hid.usb2` | `/dev/hidg2` | Boot Mouse rel + wheel combined (4 B) | not driven by `kvm_app`; raw writes confirmed working as alternate wheel path |

`kvm_app.wheelReport` writes Report ID 2 to `/dev/hidg1`. That's the
production wheel path validated above.

## Open follow-ups

1. **Cold-iPad behavior**: test wheel after a physical USB-C unplug + 5 min,
   and after an iPad reboot. The connect-time activation hook is now mandatory
   by default, and a single bounce is proved to last at least 30 min, but
   physical-unplug/iPad-reboot durability is still unmeasured.
2. **Ticks-per-row calibration**: measure how many wheel-report ticks scroll
   the iPad Settings sidebar by exactly one row, for accurate drill-down
   coverage budgeting.
3. **iPhone**: the old `picokvm-scroll-overshoot-hardware-limit` finding
   (iPhone+AssistiveTouch makes wheel 5-7% intermittent and unrecoverable) is
   superseded for the bounce+warmup path. A 2026-05-28 isolated rerun of
   `iphone_bounce.py` on the iPhone 17 rig reproduced stable PicoKVM RPC wheel:
   R01 moved ±352 px and R02-R10 moved a fixed ±599 px per 30 ticks. The earlier
   local 0px result was traced to stale `Phone.snapshot()` frames from the
   long-lived cv2 stream; direct ffmpeg frames showed the wheel movement.
4. **Update existing docs**: `docs/design/ipad_mini_migration.md §5` and the
   `picokvm-scroll-overshoot-hardware-limit` memory should point here for the
   iPad case.

## References

- Validation scripts and snapshots:
  `artifacts/wheel_probe_2026-05-27/`.
- Related project docs: `docs/design/ipad_mini_migration.md`,
  `docs/goals/scroll_overshoot_efficiency.md`.
- Related project memory: `picokvm-scroll-overshoot-hardware-limit`,
  `ios-ignores-usb-hid-digitizer`, `iphone-vs-ipad-mouse-keyboard-support`,
  `ipad-usb-hid-trackpad-mfi-gated` (why we cannot upgrade from wheel to
  native multi-touch trackpad on iPad — 2026-05-28 four-variant experiment).
