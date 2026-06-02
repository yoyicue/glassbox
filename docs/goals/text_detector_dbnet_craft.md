# Goal (conditional stub) — Optional text DETECTOR seam (DBNet / CRAFT)

Status: **NOT TRIGGERED — conditional. 2026-06-02.** Do not start until the
trigger below fires. This is a deliberate stub, not a full goal.

## Trigger (the only reason to open this)

Open **only if** the cheap levers in
[`ocr_max_out_vision_levers.md`](ocr_max_out_vision_levers.md) — WS1
(`minimumTextHeight=0`) and WS2 (native ROI / tiling) — prove **on-rig** that
Apple Vision's text-**detection recall** is the bottleneck on dense/tiny UI text
(small labels, the 3px minus button) and the levers cannot close it. If Vision's
recall turns out adequate, this goal stays closed and a third-party detector is
**not** worth its dependency + latency.

## Why a stub, not a full goal

The full Apple-Silicon recipe is already researched and parked in project memory
`[[dbnet-craft-apple-silicon]]`. Headlines (do not re-derive — read the memory):

- Prefer **`PP-OCRv5_mobile_det`** (DBNet head, ~5M params, **Apache-2.0
  code+weights**) → export ONNX → **ONNX Runtime + `CoreMLExecutionProvider`
  (+CPU EP fallback)** with a **fixed/letterbox input shape** (dynamic shape →
  silent CPU fallback, ANE gain lost) → DB post-proc on CPU → crops → feed back
  to the existing Apple Vision **recognizer**.
- **DBNet > CRAFT** for dense, axis-aligned UI text (recall, weight, license).
- **`MhLiao/DB` has no license — do not vendor.** CRAFT-pytorch is MIT (not
  non-commercial, a common myth).
- **Latency caveat**: the detector forward is cheap; DB/CRAFT segmentation
  post-proc (CPU/OpenCV) + per-crop re-recognition can be **slower** than one
  tuned full-frame `.accurate`. Profile before adopting.

Writing a full goal now would be speculative — the conditional may never fire.

## When triggered, expand into

- Model + runtime choice (start from the memory recipe).
- A **detector seam** in `glassbox/cognition/` — a `GLASSBOX_TEXT_DETECTOR`
  selector defaulting to `"vision"`, mirroring the icon-backend seam
  (`icon_detect.py` / `GLASSBOX_ICON_DETECTOR`). The new stage must not touch the
  free OCR-only default path.
- A go/no-go A/B: annotated UI corpus → Baseline A (Vision tuned) vs B
  (Vision + DBNet), adopt only if B gives recall A cannot match on the hardest
  elements at acceptable latency.

## Constraints (already settled)

MIT/Apache only; default-off; **can** be a real `pyproject.toml` optional
dependency (unlike the AGPL OmniParser plugin), but heavy weights stay out of the
default install. Fix-the-core (`glassbox/cognition/`, not a skill). All ms must
be on-rig measured.
