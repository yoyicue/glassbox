"""S3 mint-flip allow-list guards (docs/design/iphone_settings_transition.md).

Two layers, mirroring test_privacy_guard.py:

1. **Fixture floor (runs everywhere, CI included):** the committed, hand-
   reviewed allow-list of ``recorded page_id → re-minted page_id`` flips stays
   well-formed and non-empty, every flip carries a review verdict, and the
   known S3 members are present.
2. **Local replay subset (host-local, skips loudly in CI):** on hosts that
   hold the raw run ledger (gitignored ``artifacts/``), re-run the committed
   generator (``skills.regression.replay_settings_mint_flips``) over every
   scene and assert the emitted flips are a **subset** of the allow-list — any
   new, un-reviewed flip fails the gate and forces a re-review.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST_PATH = (
    REPO_ROOT / "skills" / "regression" / "fixtures" / "ios_settings_mint_flip_allowlist.json"
)
RUN_DIR = Path(
    os.environ.get("GLASSBOX_MINT_FLIP_RUN_DIR")
    or REPO_ROOT
    / "artifacts"
    / "computer_use_success_rate"
    / "iphone_floor_runs"
    / "run_2026_06_12_06_04_38_737160"
)

# Verified members of the reviewed allow-list (the S3 forensics' false
# rejections); their absence means the fixture was emptied or regenerated
# without review.
KNOWN_FLIPS = {
    ("settings/CURRENT", "settings/Wallpaper"),
    ("settings/Silent Mode", "settings/Sounds & Haptics"),
    ("settings/Paired Devices", "settings/Developer"),
}


def _allowlist() -> dict:
    return json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))


@pytest.mark.smoke
def test_mint_flip_allowlist_is_well_formed_and_reviewed():
    allowlist = _allowlist()
    assert allowlist["schema"] == "ios_settings_mint_flip_allowlist.v1"
    assert allowlist["run"]
    assert allowlist["generator"].startswith("uv run python -m skills.regression.")
    flips = allowlist["flips"]
    assert flips, "allow-list must not be empty"
    seen_scenes: set[str] = set()
    for flip in flips:
        assert isinstance(flip["old"], str) and flip["old"], flip
        assert isinstance(flip["new"], str) and flip["new"], flip
        assert flip["scenes"] and all(s.startswith("scn_") for s in flip["scenes"]), flip
        assert str(flip["review"]).strip(), f"unreviewed flip committed: {flip['old']}"
        overlap = seen_scenes & set(flip["scenes"])
        assert not overlap, f"scene(s) in two flip groups: {sorted(overlap)}"
        seen_scenes.update(flip["scenes"])
    assert {(f["old"], f["new"]) for f in flips} >= KNOWN_FLIPS


@pytest.mark.smoke
def test_local_run_replay_flips_are_subset_of_allowlist():
    if not (RUN_DIR / "scenes").is_dir():
        pytest.skip(
            "SKIPPED BY DESIGN: raw run ledger not present under "
            f"{RUN_DIR} (artifacts/ is gitignored, so CI and fresh checkouts "
            "cannot replay the 834-scene run). On the rig/owner host this test "
            "re-runs the generator and pins its flips to the reviewed allow-list."
        )
    from skills.regression.replay_settings_mint_flips import replay_mint_flips

    allowed = {
        (flip["old"], flip["new"], scene)
        for flip in _allowlist()["flips"]
        for scene in flip["scenes"]
    }
    report = replay_mint_flips(RUN_DIR)
    got = {(flip["old"], flip["new"], flip["scene_id"]) for flip in report["flips"]}
    unreviewed = got - allowed
    assert not unreviewed, (
        f"replay produced {len(unreviewed)} flip(s) outside the reviewed allow-list "
        f"(hand-review and regenerate the fixture): {sorted(unreviewed)[:10]}"
    )
    # Non-vacuity: the headline C2 flip must actually occur on the local replay.
    assert any(
        old == "settings/Silent Mode" and new == "settings/Sounds & Haptics"
        for old, new, _scene in got
    )
