# iOS Settings transition corpus (iPhone)

Committed offline replay corpus for the iPhone Settings transition-recognition
work — S1 of `docs/design/iphone_settings_transition.md`. Extracted from the
live repro run `run_2026_06_12_06_04_38_737160` (iPhone 17 Pro Max, en/CN,
144-action ledger; snapshot as of `8eb69f7`).

One JSON file per **candidate tap group** — a Settings-root row tap whose
command carried a `page_id` expected_state and a row target — plus
`root_scene.json` (the Settings root the taps started from). Each group file
records the zh-canonical/visible `target`, the `expected_state` payload
verbatim as built at run time, the slimmed after-scene (`page_id`,
`platform_scene_kind`, `elements[{text, box, type}]`), the recorded semantic
verdict/reason, and how the candidate verified live (`verified_via`:
`page_id` — the after-scene's minted page_id was in `any_of`;
`vlm_escalation` — only a billed VLM rescue matched; `null` — rejected live).

## Regenerating

The generator is a committed script; the structural detector + scrubber it
uses are shared in `skills/regression/scrub.py` (the raw run directory exists
only on the rig host and is **not** committed):

```bash
uv run python -m skills.regression.extract_transition_corpus \
    --run artifacts/computer_use_success_rate/iphone_floor_runs/run_2026_06_12_06_04_38_737160 \
    --out skills/golden/ios_settings_transitions
```

## Scrubbing

Personal data is replaced with stable placeholders (`SCRUBBED_*`) so replay
still works; detection is structural — the personal strings appear nowhere in
the repo. Classes scrubbed from this run: the Apple Account display name on
the Settings root, Wi-Fi/WLAN network names (the WLAN after-scene lists
nearby networks; the root scene shows the connected one), a trusted phone
number and its "Date added" value (Apple-ID modal), a Game Center nickname +
e-mail. Bluetooth device names are detected too; this run had none paired.
`skills/smoke/test_ios_settings_transition_corpus.py` asserts every committed
scene stays clean (shape-based; no personal literals in the test either).

## Consumers

- `skills/smoke/test_ios_settings_transition_corpus.py` — corpus floor +
  scrub assertions.
- `skills/smoke/test_ios_settings_transition_replay.py` — rebuilds each
  expected_state with the **current** builder
  (`navigation._settings_row_expected_state` →
  `policy.page_id_route_label_candidates`) under en/CN, **re-mints** the
  after-scene `page_id` with the current classifier
  (`glassbox.ios.scene.classify_ios_scene` over the committed elements; since
  the S3 nav-band mint fix the mint itself is under test, not the recorded
  string) and replays the real comparator
  (`glassbox.action.semantic_plan.verify_expected_state`), pinning matches /
  correct rejections / S3-fixed mints / the one remaining wrong-mint
  false rejection (strict xfail, S4 territory).
