# OCR Temporal Voting Home Spike - 2026-06-01

## Setup

- Device: iPad mini 7 through PicoKVM HDMI capture.
- Screen: Home widget/icon page at rest.
- Runtime config: `platform=ipados`, `phone_model=ipad_mini_7`.
- Command shape: `collect_ocr_temporal_spike(samples=10, spacing_ms=500, keep_clusters=False)`.
- Artifact run used for the preceding manual check: `artifacts/run_2026_06_01_19_30_43_229468`.

## Result

```json
{
  "samples_requested": 10,
  "samples_used": 10,
  "distinct_frames": 5,
  "duplicate_frames": 5,
  "clusters": 48,
  "variant_clusters": 0,
  "variant_region_rate": 0.0,
  "clusters_with_majority_change": 0,
  "sample_spacing_ms": 500
}
```

## Decision Gate

The capture path produced enough distinct frames for a minimal check
(`distinct_frames=5`), but no OCR text region varied across those frames
(`variant_region_rate=0.0`, `clusters_with_majority_change=0`).

This fails the temporal-voting gate:

- required: non-trivial important-region disagreement;
- observed: no region-level variants;
- required: at least half of variants corrected by `vote_scenes`;
- observed: no variants to correct.

## Decision

Keep OCR temporal voting default-off and do not opt in the Home path. Home OCR
failures observed on this rig are deterministic for this screen, so the next
repair is closed-set SpringBoard app-label recognition plus spatial/icon
constraints, not temporal voting.
