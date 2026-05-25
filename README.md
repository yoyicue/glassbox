# glassbox

glassbox is an iOS-first computer-use runtime for driving a real device from
screen observations. It wires frame capture, OCR/VLM perception, action
execution, verification, recording, and screen memory behind pluggable seams.

## Why this approach: minimal intrusiveness

glassbox is **out-of-band**: it observes through the iPhone's HDMI output and
acts through a USB HID mouse/keyboard. No glassbox code runs on the phone.
Compared with the usual iOS automation approaches, it changes the target device
the least:

- **No app or test runner installed.** No WebDriverAgent / Appium / XCUITest
  runner, no companion app, no sideloading.
- **No jailbreak, provisioning profile, or developer account.** It runs against
  a stock retail device on stock iOS.
- **No code injection or instrumentation.** The target app runs completely
  unmodified — glassbox sees exactly the rendered screen (HDMI) and acts exactly
  as a physical pointer/keyboard would (HID).
- **Only built-in settings, no software.** Control rides on AssistiveTouch plus
  system keyboard shortcuts, so a few stock accessibility/display toggles must be
  set first (see [iOS prerequisites](#ios-prerequisites-controlled-iphone)) — but
  nothing is installed on the phone.
- **Controller is off-device.** All perception/cognition/action logic runs on
  macOS; the phone only mirrors video out and accepts HID in.

The payoff is high-fidelity observations and actions with no test-harness
artifacts and no anti-tamper / jailbreak-detection surface, so the rig is safe
to point at apps you cannot or should not modify. The tradeoff is external
capture hardware (the PicoKVM) and HID-pointer semantics instead of native
multi-touch.

## Install

```bash
uv sync --extra dev
uv run python -c "import glassbox"
```

For editable pip installs:

```bash
python -m pip install -e ".[dev]"
```

## Quickstart

Copy the local config template before hardware or VLM runs:

```bash
cp .env.example .env
```

Offline/static-frame development (no hardware needed):

```bash
GLASSBOX_FRAME_DIR=/path/to/png-frames uv run python -c "from glassbox.runtime import make_source; print(make_source())"
```

PicoKVM runtime (requires the [Hardware setup](#hardware-setup) below):

```bash
export GLASSBOX_PICOKVM=1
export GLASSBOX_PICOKVM_BASE_URL=http://picokvm.local
uv run glassbox-show-screen
```

First end-to-end run against the always-available iOS Settings app — the
quickest way to confirm the whole rig works. Start with the readiness preflight,
then a fast read-only walkthrough:

```bash
# 1. Check the PicoKVM rig is reachable (RPC + one decoded frame).
uv run python -m skills.regression.ios_settings.diagnose --json

# 2. Drive Settings read-only, write a report, and verify it.
#    --quick visits a few pages; drop it for the full exhaustive audit.
uv run python -m skills.regression.ios_settings.run_full --quick
```

The walkthrough never changes a setting: it foregrounds Settings, opens
navigation rows, reads page text, and returns via the visible back affordance.
It exercises the full perception → action → verification pipeline and writes a
JSON report plus artifacts.

> **Note — `run_full` enables the VLM by default.** Unlike the bare runtime
> (where VLM is opt-in), the Settings `run_full` helper sets
> `GLASSBOX_ENABLE_VLM=1` for cold-start robustness, so it expects an API key. To
> run it without a key, opt out explicitly:
> `GLASSBOX_ENABLE_VLM=0 uv run python -m skills.regression.ios_settings.run_full --quick`.
> Otherwise configure a key first (see [Local VLM config](#local-vlm-config)) —
> without one the run fails fast at startup with a clear "Missing API key" error.

### Local VLM config

VLM is opt-in at the runtime level: `glassbox.config` reads `.env` and selects a
client only when `GLASSBOX_ENABLE_VLM=1` is set. (The Settings `run_full` helper
turns it on by default — see the note above.)

```dotenv
GLASSBOX_ENABLE_VLM=1
GLASSBOX_VLM=moonshot          # or siliconflow
MOONSHOT_API_KEY=...
SILICONFLOW_API_KEY=...
```

`GLASSBOX_VLM=moonshot` uses the Moonshot Anthropic-compatible client; the
SiliconFlow key is only needed when selecting `GLASSBOX_VLM=siliconflow`. The
lower-level `make_vlm_client()` helper also accepts `VLM_BACKEND` /
`KIMI_BACKEND` for direct-client compatibility, but normal runtime selection is
the `GLASSBOX_*` pair above.

To avoid paying the VLM icon-naming cost on every cold start, set
`GLASSBOX_SPRINGBOARD_ICON_MAP_PATH` to a JSON file: the VLM-built SpringBoard
icon→position map is then persisted across runs (layout-keyed and
drift-invalidated), so it is rebuilt only when the Home layout changes. Unset, the
map is in-memory per run. The Settings `run_full` helper defaults it to
`~/.cache/glassbox/springboard_icon_map.json`.

## Architecture

glassbox runs an **observe → decide → act → verify** loop against a live screen,
records every step, and updates a screen-memory graph it can reuse on later runs.
`glassbox/runtime.py` is the assembler: it wires the stages below into a single
`Phone`, and `glassbox.ai` exposes that runtime as a stable author-mode facade.

```
                        ┌──────────────────── screen memory (UTG graph) ◀─┐
                        ▼                                                  │
   frame  ──▶ Perception ──▶ Cognition ──▶ Action ──▶ Effector ──▶ device │
   source     (crop +        (OCR/VLM →    (intent →   (HID/noop    input  │
              stability)      elements)     actuation)  transport)         │
                                                │                          │
                                                └──▶ Verification ─────────┘
                                                     (semantic effect, not
                                                      transport ACK)
```

Each stage maps to a package:

| Stage | Package | Role |
| --- | --- | --- |
| Perception | `glassbox/perception` | Pull frames from a frame source, letterbox-crop to the device content area, debounce with a stability policy. |
| Cognition | `glassbox/cognition` | Turn a frame into an observation: OCR (with voting), optional VLM, icon detection, set-of-marks, text matching → elements with geometry. |
| Action | `glassbox/action` | Orchestrate intents (tap text, swipe, launch app) into low-level actuations, with policy, seeds, and recovery. |
| Effector | `glassbox/effector.py`, `glassbox/effectors/` | The input transport that actually drives the device (noop, PicoKVM HID), described by `BackendCapabilities`. |
| Verification | `glassbox/verification` | Confirm the *semantic* effect of an action (scene/text diff, golden, verifiers) instead of trusting a transport ACK or raw pixel delta. |
| Screen memory | `glassbox/memory` | A UTG-style graph of screens, elements, and transitions, persisted across runs. |
| Observability | `glassbox/obs` | Recorder, artifacts, replay, and VLM/OCR caches. |
| iOS platform | `glassbox/ios` | Scene classification, SpringBoard map, AssistiveTouch primitives, safe-area/recovery — the iOS provider behind the Platform seam. |

### Pluggable seams

Every stage is a **named boundary** — `FrameSource`, `Effector`, `OCR`, `VLM`,
`IconDetector`, `Verifier`, `Platform`, and `CrawlPolicy` (defined in
`glassbox/boundaries.py`). Backends are discovered as Python **entry points**
(`glassbox.frame_sources`, `glassbox.effectors`, `glassbox.ocr`, `glassbox.vlm`,
`glassbox.icon_detectors`, `glassbox.verifiers`, `glassbox.platforms`,
`glassbox.crawl_policies`), so you add a backend by registering an entry point —
no core edits. Effector backends advertise capabilities (coordinate space,
connection requirements, transport label, calibrated-crop and wheel defaults).
Boundary maturity is tracked in
`docs/design/architecture_boundaries.md`
(contract v2; 6 of 8 graduated, Platform and CrawlPolicy provisional).

### Entry surfaces

- **`glassbox.ai`** — stable author-mode facade (`open_phone() -> AIPhone`,
  `ai-api-v1`); text-first `observe` / `tap` / `goto` / `explore` /
  `save_report`. See `docs/design/public_api.md`.
- **`glassbox.phone.Phone`** — the low-level runtime object assembled by
  `runtime.py`.
- **`glassbox-mcp-server`** — remote MCP (stdio) for agents.
- **`glassbox-ai-session`** — long-lived JSONL observe-decide-act session.
- **`glassbox-show-screen` / `glassbox-list-devices`** — demos.

## Language and locale

glassbox treats the controlled device's UI language as a **locale seam**: OCR
vocabulary, Settings label resolution, and report display all key off the active
locale rather than being hard-coded to one language.

- **Default `zh-Hans`, English switchable.** Set with `GLASSBOX_LANGUAGE`
  (default `zh-Hans`) plus an optional `GLASSBOX_REGION` overlay, or per run with
  the `run_full --language` / `--region` flags (which set those env vars for that
  process only). Chinese is the currently validated default; flipping the
  production default to English is the last migration step (see the design doc
  below). Do not pin `GLASSBOX_LANGUAGE` in `.env` before that flip — it changes
  the global default for every caller, including the test suite.
- **OCR languages auto-select per locale.** A `zh-Hans` run drives Apple Vision
  with `("zh-Hans", "en-US")`; an `en-*` run uses English only — fewer languages
  reads cleaner and cheaper, since Latin OCR avoids CJK confusion.
- **Region variants.** Greater-China English devices (`GLASSBOX_REGION=CN` or
  `HK`) show `WLAN` / `Mobile Service` instead of `Wi-Fi` / `Cellular`; those
  resolve and display correctly only under the `en-CN` / `en-HK` packs.
- **Language-neutral section identity.** The Settings domain owns stable
  `RootSection` ids; locale packs only map OCR text ↔ id ↔ display. Coverage
  reports carry the primary label plus parallel `*_ids` (neutral tokens, so en
  and zh reports compare by id) and `*_display` (rendered in the run's own
  language), so an `en-HK` report reads in English without changing the internal
  pivot.

```bash
# Run the Settings audit against an English (Hong Kong) device.
uv run python -m skills.regression.ios_settings.run_full --drill-down \
  --language en --region HK
```

Full design and the phased migration plan live in
`docs/design/locale_seam_english_first.md`.

## Hardware setup

The reference setup drives a real iPhone with a Luckfox PicoKVM sitting between
the phone and the controller host. glassbox never touches the iPhone directly —
it only talks to the PicoKVM over the network. A single USB-C Digital AV
Multiport Adapter on the iPhone carries both directions (HDMI video out + a
USB-A host port for HID input) and also distributes power, while glassbox
reaches the PicoKVM over plain HTTP:

```
   USB-C Digital AV Multiport Adapter
   ┌─────────┐  ── HDMI out ─────────────▶  ┌──────────────┐  GET /video/stream  ┌──────────┐
   │ iPhone  │     (video)                   │   Luckfox    │  (H.264) ─────────▶ │ glassbox │
   │  (iOS)  │                               │   PicoKVM    │                     │ (macOS)  │
   │ USB-C ──┤  ◀─ USB-A host port ───────   │ HDMI capture │  POST /api/rpc      │          │
   └─────────┘     USB HID + power           │ + HID gadget │  ◀── (JSON-RPC) ─── └──────────┘
        │                                    └──────────────┘
        └── USB-C power-in ◀── charger (powers the iPhone *and* the PicoKVM)
```

- **One adapter, two paths + power:** the iPhone's USB-C port connects to a
  USB-C Digital AV Multiport Adapter. Its **HDMI** port feeds the PicoKVM
  capture input (video out), and its **USB-A** port hosts the PicoKVM HID gadget
  (control in). The adapter's **USB-C power-in is required, not optional**: the
  charger plugged there powers the iPhone *and* feeds the PicoKVM through the
  USB-A port, so the PicoKVM draws its power from this same USB-C. This is the
  current bring-up wiring; any Lightning/USB-C-to-HDMI plus USB-host equivalent
  works the same way.
- **Video (perception):** the iPhone's screen leaves over HDMI into the
  PicoKVM's capture input. The PicoKVM re-serves it as an H.264 stream at
  `GET /video/stream`, which `PicoKVMFrameSource` decodes into frames (the
  `frame_px` coordinate space).
- **Control (action):** glassbox sends actions as JSON-RPC over HTTP to
  `POST /api/rpc`. The PicoKVM presents itself to the iPhone (through the
  adapter's USB-A host port) as a USB HID mouse + keyboard and injects the
  resulting pointer/key events. Because this is a HID pointer and not a touch
  digitizer, taps are pointer moves plus clicks and swipes/drags are mouse drags;
  the controlled iPhone must be configured first (see
  [iOS prerequisites](#ios-prerequisites-controlled-iphone)). PicoKVM logical
  coordinates (absolute, max 32767) are mapped to decoded frame pixels via a
  calibrated linear fit.
- **Network:** both links to glassbox are plain HTTP to the PicoKVM, set with
  `GLASSBOX_PICOKVM_BASE_URL` (default `http://picokvm.local`). The controller
  host (macOS) only needs network reachability to the PicoKVM, not a direct
  cable to the iPhone.

### iOS prerequisites (controlled iPhone)

"Minimal intrusiveness" does not mean zero setup. Because control rides on the
AssistiveTouch pointer and on system keyboard shortcuts, the controlled iPhone
needs these stock settings configured before a run. None of them install
anything — they are all built-in iOS toggles:

| Setting | Path | Value | Why |
| --- | --- | --- | --- |
| AssistiveTouch | Accessibility › Touch › AssistiveTouch | **On** | Gives the HID mouse an on-screen pointer to drive; PicoKVM is a HID pointer, not a touch digitizer. |
| AssistiveTouch tracking speed | Accessibility › Touch › AssistiveTouch › Tracking speed | **Slowest** (slider fully left) | Keeps pointer motion deterministic so the calibrated logical→pixel fit reproduces. |
| AssistiveTouch tracking sensitivity | Accessibility › Touch › AssistiveTouch › Tracking sensitivity | **Highest** (slider fully right) | Same — matches the bring-up rig so the pointer lands where the calibration expects. |
| Auto-Lock | Display & Brightness › Auto-Lock | **Never** | Keeps the screen awake through long automation runs. |
| Full Keyboard Access | Accessibility › Keyboards › Full Keyboard Access | **On** | Enables the system keyboard shortcuts glassbox sends — `Cmd-H` (Home), `Cmd-[` (Back), `Cmd-Up` (App Switcher), `Cmd-C` (Control Center), `Cmd-N` (Notification Center). See `docs/reference/ios_full_keyboard_access_commands.md`. |

The tracking-speed/sensitivity values come from the same single-device bring-up
as the PicoKVM calibration below (iPhone 17 Pro Max); a different phone or
different slider positions can shift where the pointer lands and require
re-calibration.

### Device support and calibration

Two layers decide which iPhone this works on, and they are calibrated
differently:

- **Geometry (parameterized).** `glassbox/perception/device.py` ships a `DEVICES`
  table covering the iPhone 15 / 16 / 17 families (standard / Pro / Pro Max),
  with both native pixel sizes and UIKit point sizes. The model is selected with
  `GLASSBOX_PHONE_MODEL` (default `iphone_17_pro_max`) and drives the letterbox
  coordinate transform — so this layer is not hard-coded to one phone.
- **PicoKVM calibration (single-device).** The end-to-end PicoKVM path was only
  brought up and calibrated on an **iPhone 17 Pro Max** (the bring-up rig, dated
  2026-05-21). The device-specific values live in `PicoKVMEffectorConfig`:
  - the logical-to-frame linear fit (`abs_to_phone_scale_x/y`,
    `abs_origin_offset_x/y`), and
  - the hard-coded logical gesture coordinates
    (`keyboard_focus_x/y`, `close_app_drag_*`, etc.).

  These depend on the exact HDMI output resolution and letterboxing of that
  phone, so a different model (different aspect ratio or resolution) will be off
  until re-calibrated. They are **not** code constants you must edit — every one
  is overridable via `GLASSBOX_PICOKVM_*` environment variables. Moving to
  another iPhone means re-measuring the linear fit and gesture anchors and
  exporting the new values, not changing the source.

In short: the geometry table is multi-model, but the validated PicoKVM rig is
iPhone 17 Pro Max only.

## Backends

These are the concrete implementations that ship for the seams in
[Architecture](#architecture):

| Surface | Built in | Notes |
| --- | --- | --- |
| Frame source | AVFoundation, static PNG directory, PicoKVM H.264 stream | macOS is the primary controller platform. |
| Effector | noop, PicoKVM | PicoKVM uses USB HID mouse/keyboard semantics with iOS AssistiveTouch/external pointer enabled. |
| OCR | Apple Vision, ocrmac | PaddleOCR is optional through the `ocr` extra. |
| VLM | Moonshot-compatible and SiliconFlow-compatible clients | VLM is opt-in: set `GLASSBOX_ENABLE_VLM=1`, choose `GLASSBOX_VLM=moonshot` or `siliconflow`, and provide the matching API key. |
| Platform | iOS | Other platforms are extension seams, not built-in finished ports. |

The default open-source tree includes the PicoKVM, noop, and static-frame paths
above. It does not include any third-party target app, private profiles, or
private transport bridges.

## Development

```bash
uv run ruff check glassbox skills
uv run pytest skills/smoke -q
```

Icon detector backends with AGPL-heavy dependencies are intentionally kept as
drop-in plugins instead of project extras, so the core package remains
dependency-clean for MIT distribution.
