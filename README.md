# glassbox

glassbox is an iOS-first computer-use runtime for driving a real device from
screen observations. It wires frame capture, OCR/VLM perception, action
execution, verification, recording, and screen memory behind pluggable seams.

The default open-source tree includes PicoKVM, noop, and static-frame paths. It
does not include any third-party target app, private profiles, or private
transport bridges.

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
  digitizer, the iPhone must have **AssistiveTouch / external pointer enabled**;
  taps are pointer moves plus clicks, and swipes/drags are mouse drags. PicoKVM
  logical coordinates (absolute, max 32767) are mapped to decoded frame pixels
  via a calibrated linear fit.
- **Network:** both links to glassbox are plain HTTP to the PicoKVM, set with
  `GLASSBOX_PICOKVM_BASE_URL` (default `http://picokvm.local`). The controller
  host (macOS) only needs network reachability to the PicoKVM, not a direct
  cable to the iPhone.

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

Offline/static-frame development:

```bash
GLASSBOX_FRAME_DIR=/path/to/png-frames uv run python -c "from glassbox.runtime import make_source; print(make_source())"
```

PicoKVM runtime:

```bash
export GLASSBOX_PICOKVM=1
export GLASSBOX_PICOKVM_BASE_URL=http://picokvm.local
uv run glassbox-show-screen
```

## Backends

| Surface | Built in | Notes |
| --- | --- | --- |
| Frame source | AVFoundation, static PNG directory, PicoKVM MJPEG stream | macOS is the primary controller platform. |
| Effector | noop, PicoKVM | PicoKVM uses USB HID mouse/keyboard semantics with iOS AssistiveTouch/external pointer enabled. |
| OCR | Apple Vision, ocrmac | PaddleOCR is optional through the `ocr` extra. |
| VLM | Moonshot-compatible and SiliconFlow-compatible clients | VLM is opt-in with environment-provided API keys. |
| Platform | iOS | Other platforms are extension seams, not built-in finished ports. |

## Development

```bash
uv run ruff check glassbox skills
uv run pytest skills/smoke -q
```

Icon detector backends with AGPL-heavy dependencies are intentionally kept as
drop-in plugins instead of project extras, so the core package remains
dependency-clean for MIT distribution.
