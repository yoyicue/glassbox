# icon_backends/ — drop-in icon-detection plugins

`detect_icons` (`../icon_detect.py`) ships one built-in backend, `classical`
(OpenCV, no extra deps). Extra backends live here as drop-in plugins.

**This directory is git-ignored** (except this README). Plugin code never
enters version control, so the glassbox core stays dependency-clean and
permissively (MIT) licensed. Heavier or differently-licensed detectors are
dropped in locally, per machine.

## Plugin contract

A plugin is any `*.py` file in this directory (names starting with `_` are
skipped). At import time it must register itself:

```python
from glassbox.cognition.icon_detect import IconRegion, register_icon_backend

def _detect(frame_img, *, text_boxes=(), **_):   # **_ swallows classical-only kwargs
    ...
    return [IconRegion(box=(x, y, w, h)), ...]

register_icon_backend("my_backend", _detect)
```

Select it at runtime with `GLASSBOX_ICON_DETECTOR=my_backend`. A plugin that fails
to import is logged and skipped — it never breaks the core.

## OmniParser backend (internal only — AGPL-3.0)

The OmniParser v2 YOLO detector (`omniparser` backend) is **not** part of the
MIT core: its model and the `ultralytics` runtime are AGPL-3.0. The plugin is
kept on the internal `feat/omniparser-icon-detect` branch. To use it, drop that
plugin file into this directory and `pip install ultralytics torch
huggingface_hub`. See that branch's `docs/omniparser_icon_backend.md`.
