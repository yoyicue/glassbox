# glassbox

glassbox is an iOS-first computer-use runtime for driving a real device from
screen observations. It wires frame capture, OCR/VLM perception, action
execution, verification, recording, and screen memory behind pluggable seams.

The default open-source tree includes PicoKVM, noop, and static-frame paths. It
does not include any third-party target app, private profiles, or private
transport bridges.

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
