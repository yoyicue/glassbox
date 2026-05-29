from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from glassbox.action import ActionOrchestrator, ActuationProfile, CandidatePointGenerator
from glassbox.action.actuation_profile import load_actuation_profile, save_actuation_profile
from glassbox.action.seeds import DEFAULT_RECOVERY_SEED, recovery_hint
from glassbox.cognition import Box, UIElement
from glassbox.effector import MockEffector
from glassbox.obs.artifacts import ArtifactStore
from glassbox.perception.source import Frame
from glassbox.phone import Phone


class _ImageSource:
    resolution = (32, 32)

    def __init__(self, frames: list[np.ndarray]):
        self.frames = frames
        self.index = 0

    def snapshot(self):
        image = self.frames[min(self.index, len(self.frames) - 1)]
        self.index += 1
        return Frame(img=image.copy(), ts=float(self.index))


class _TargetOCR:
    contract = None

    def recognize(self, image):
        del image
        return [
            UIElement(
                type="text",
                box=Box(x=8, y=8, w=12, h=12),
                text="Go",
                confidence=0.95,
                element_id=7,
            )
        ]


class _NavTargetOCR:
    """OCR that returns the "Go" row until a tap actually lands (the changed_roi
    marker appears), then a different page — i.e. a tap that lands really
    navigates, so success comes from scene progress, not a raw pixel delta."""

    contract = None

    def recognize(self, image):
        navigated = bool(image[9:19, 9:19].any())
        if navigated:
            return [
                UIElement(
                    type="text",
                    box=Box(x=2, y=2, w=10, h=6),
                    text="Detail",
                    confidence=0.95,
                    element_id=9,
                )
            ]
        return [
            UIElement(
                type="text",
                box=Box(x=8, y=8, w=12, h=12),
                text="Go",
                confidence=0.95,
                element_id=7,
            )
        ]


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _frame(*, changed_roi: bool = False) -> np.ndarray:
    image = np.zeros((32, 32, 3), dtype=np.uint8)
    if changed_roi:
        image[9:19, 9:19] = 255
    return image


@pytest.mark.smoke
def test_candidate_point_generator_is_deterministic_and_has_fallback_points():
    element = UIElement(
        type="switch",
        box=Box(x=10, y=20, w=40, h=20),
        text="Wi-Fi",
        confidence=0.9,
    )

    points = CandidatePointGenerator().generate(element)

    assert [(p.x, p.y) for p in points[:3]] == [(30, 30), (40, 30), (30, 24)]
    assert len(points) >= 3
    assert len({(p.x, p.y) for p in points}) == len(points)


@pytest.mark.smoke
def test_target_tap_landing_miss_retries_with_next_candidate_and_emits_events(tmp_path):
    frames = [
        _frame(),  # tap_text target lookup
        _frame(),  # preflight
        _frame(),  # attempt 0 before_requested
        _frame(),  # attempt 0 before_command
        _frame(),  # attempt 0 landing window: miss
        _frame(),  # attempt 0 stable after: no progress
        _frame(),  # attempt 1 before_requested
        _frame(),  # attempt 1 before_command
        _frame(changed_roi=True),  # attempt 1 landing window: landed
        _frame(changed_roi=True),  # attempt 1 stable after: scene progressed
    ]
    store = ArtifactStore(tmp_path, run_id="run")
    orchestrator = ActionOrchestrator(store)
    effector = MockEffector()
    phone = Phone(
        source=_ImageSource(frames),
        ocr=_NavTargetOCR(),
        effector=effector,
        action_orchestrator=orchestrator,
        action_fail_fast=False,
        perceive_cache_diff=0.0,
    )

    result = phone.tap_text("Go", landing_retry_allowed=True)
    orchestrator.close()

    assert result.ok is True
    assert result.semantic_status == "succeeded"
    assert [action.kwargs for action in effector.actions] == [
        {"x": 14, "y": 14},
        {"x": 13, "y": 14},
    ]

    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    # First attempt missed (no ROI change); the re-tap landed AND really
    # navigated, so success comes from scene progress (CUQ-1.1: a mouse tap is
    # not scored succeeded on a raw pixel delta alone).
    assert [action["semantic"]["reason"] for action in actions] == [
        "landing_missed",
        "scene changed after action",
    ]
    assert actions[0]["semantic"]["retry_allowed"] is True
    assert actions[0]["actuation"]["landing_observation"]["landing_signal"] == "missed"
    assert actions[1]["actuation"]["landing_observation"]["landing_signal"] == "landed"

    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    landing_events = [event for event in audit if event["type"] == "actuation.landing_observed"]
    attempt_events = [event for event in audit if event["type"] == "actuation.attempt_attributed"]
    group_events = [event for event in audit if event["type"] == "actuation.attributed"]
    retry_events = [event for event in audit if event["type"] == "action.retry_scheduled"]

    assert [event["payload"]["landing_signal"] for event in landing_events] == ["missed", "landed"]
    assert [event["payload"]["label"] for event in attempt_events] == ["missed", "landed_ok"]
    assert group_events[0]["payload"]["label"] == "landed_ok"
    assert group_events[0]["payload"]["contributing_attempts"] == [
        {
            "attempt_id": "act_000000",
            "method": "mouse_tap",
            "landing_signal": "missed",
            "label": "missed",
        },
        {
            "attempt_id": "act_000001",
            "method": "mouse_tap",
            "landing_signal": "landed",
            "label": "landed_ok",
        },
    ]
    assert retry_events[0]["payload"]["kind"] == "landing"

    profile = json.loads((store.run_dir / "actuation_profile.json").read_text(encoding="utf-8"))
    method_stats = profile["entries"][0]["value"]["methods"]["mouse_tap"]
    assert method_stats["command_tries"] == 2
    assert method_stats["landed_attempts"] == 1
    assert method_stats["semantic_ok"] == 1
    assert method_stats["by_label"] == {"landed_ok": 1, "missed": 1}
    assert method_stats["offset"]["mean"] == [-1.0, 0.0]
    assert method_stats["offset"]["n"] == 1
    report = json.loads((store.run_dir / "actuation_report.json").read_text(encoding="utf-8"))
    assert report["attempt_labels"] == {"landed_ok": 1, "missed": 1}
    assert report["landing_signals"] == {"landed": 1, "missed": 1}


@pytest.mark.smoke
def test_mouse_tap_pixel_change_without_scene_progress_is_not_false_success(tmp_path):
    """CUQ-1.1: a mouse tap whose ROI changes (ripple/highlight/reflow) but
    whose page identity does NOT change must stay unknown+retryable, not be
    promoted to a confident success on the raw pixel delta."""
    frames = [
        _frame(),  # target lookup
        _frame(),  # preflight
        _frame(),  # before_requested
        _frame(),  # before_command
        _frame(changed_roi=True),  # landing window: ROI pixels changed -> "landed"
        _frame(changed_roi=True),  # stable after: same OCR -> no scene progress
    ]
    store = ArtifactStore(tmp_path, run_id="run")
    orchestrator = ActionOrchestrator(store)
    effector = MockEffector()
    phone = Phone(
        source=_ImageSource(frames),
        ocr=_TargetOCR(),  # always "Go" -> scene/page identity unchanged
        effector=effector,
        action_orchestrator=orchestrator,
        action_fail_fast=False,
        perceive_cache_diff=0.0,
    )

    result = phone.tap_text("Go")
    orchestrator.close()

    assert result.semantic_status == "unknown"
    assert result.semantic_status != "succeeded"
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert actions[-1]["actuation"]["landing_observation"]["landing_signal"] == "landed"
    assert actions[-1]["semantic"]["retry_allowed"] is True


@pytest.mark.smoke
def test_profile_offset_is_consumed_for_next_target_tap(tmp_path):
    profile = ActuationProfile()
    profile.record_correction_pair(
        control_bucket={"control_role": "text", "size_bucket": "small", "region_zone": "center"},
        method="mouse_tap",
        missed_point={"x": 14, "y": 14, "space": "frame_px"},
        landed_point={"x": 13, "y": 14, "space": "frame_px"},
    )
    store = ArtifactStore(tmp_path, run_id="run")
    orchestrator = ActionOrchestrator(store, actuation_profile=profile)
    effector = MockEffector()
    phone = Phone(
        source=_ImageSource([_frame(), _frame(), _frame(), _frame(), _frame(), _frame()]),
        ocr=_TargetOCR(),
        effector=effector,
        action_orchestrator=orchestrator,
        action_fail_fast=False,
        perceive_cache_diff=0.0,
    )

    phone.tap_text("Go")
    orchestrator.close()

    assert effector.actions[0].kwargs == {"x": 13, "y": 14}


@pytest.mark.smoke
def test_unactuatable_bucket_skips_without_effector_call(tmp_path):
    profile = ActuationProfile()
    bucket = {"control_role": "text", "size_bucket": "small", "region_zone": "center"}
    # CUQ-1.2: needs >= 5 all-negative tries from >= 2 distinct controls before
    # the shared bucket is judged unactuatable.
    for i in range(5):
        profile.record_attempt(
            control_bucket=bucket,
            method="mouse_tap",
            landing_signal="missed",
            label="missed",
            target_identity={"intent": f"row_{i % 3}"},
        )
    store = ArtifactStore(tmp_path, run_id="run")
    orchestrator = ActionOrchestrator(store, actuation_profile=profile)
    effector = MockEffector()
    phone = Phone(
        source=_ImageSource([_frame(), _frame()]),
        ocr=_TargetOCR(),
        effector=effector,
        action_orchestrator=orchestrator,
        action_fail_fast=False,
        perceive_cache_diff=0.0,
    )

    result = phone.tap_text("Go")
    orchestrator.close()

    assert result.semantic_status == "skipped"
    assert result.semantic_reason == "unactuatable"
    assert effector.actions == []
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    skipped = [event for event in audit if event["type"] == "actuation.skipped"]
    assert skipped[0]["payload"]["reason"] == "unactuatable"


@pytest.mark.smoke
def test_ignore_actuation_profile_skip_still_executes_unactuatable_bucket(tmp_path):
    profile = ActuationProfile()
    bucket = {"control_role": "text", "size_bucket": "small", "region_zone": "center"}
    # CUQ-1.2: needs >= 5 all-negative tries from >= 2 distinct controls before
    # the shared bucket is judged unactuatable.
    for i in range(5):
        profile.record_attempt(
            control_bucket=bucket,
            method="mouse_tap",
            landing_signal="missed",
            label="missed",
            target_identity={"intent": f"row_{i % 3}"},
        )
    store = ArtifactStore(tmp_path, run_id="run")
    orchestrator = ActionOrchestrator(store, actuation_profile=profile)
    effector = MockEffector()
    phone = Phone(
        source=_ImageSource([_frame(), _frame(), _frame(), _frame(), _frame(), _frame()]),
        ocr=_TargetOCR(),
        effector=effector,
        action_orchestrator=orchestrator,
        action_fail_fast=False,
        perceive_cache_diff=0.0,
    )

    element = phone.expect_text("Go")
    phone.tap_element(element, ignore_actuation_profile_skip=True)
    orchestrator.close()

    assert effector.actions
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    assert not [event for event in audit if event["type"] == "actuation.skipped"]


@pytest.mark.smoke
def test_one_stubborn_control_does_not_poison_shared_bucket(tmp_path):
    """CUQ-1.2: repeated negatives from a SINGLE control must not flag the whole
    shared (role,size,zone) bucket unactuatable and skip unrelated taps."""
    profile = ActuationProfile()
    bucket = {"control_role": "text", "size_bucket": "small", "region_zone": "center"}
    for _ in range(6):  # same control re-tried, NOT distinct controls
        profile.record_attempt(
            control_bucket=bucket,
            method="mouse_tap",
            landing_signal="missed",
            label="missed",
            target_identity={"intent": "Go"},
        )
    store = ArtifactStore(tmp_path, run_id="run")
    orchestrator = ActionOrchestrator(store, actuation_profile=profile)
    effector = MockEffector()
    phone = Phone(
        source=_ImageSource([_frame()] * 8),
        ocr=_TargetOCR(),
        effector=effector,
        action_orchestrator=orchestrator,
        action_fail_fast=False,
        perceive_cache_diff=0.0,
    )

    result = phone.tap_text("Go")
    orchestrator.close()

    # Not poisoned: the tap actually executed instead of being skipped.
    assert result.semantic_reason != "unactuatable"
    assert effector.actions


@pytest.mark.smoke
def test_tap_text_records_ocr_selection_source(tmp_path):
    """CUQ-2.9: a normal OCR-resolved tap stamps selection_source='ocr' into the
    recorded command, so the harness reads the real source."""
    store = ArtifactStore(tmp_path, run_id="run")
    orchestrator = ActionOrchestrator(store)
    phone = Phone(
        source=_ImageSource([_frame()] * 8),
        ocr=_TargetOCR(),
        effector=MockEffector(),
        action_orchestrator=orchestrator,
        action_fail_fast=False,
        perceive_cache_diff=0.0,
    )

    phone.tap_text("Go")
    orchestrator.close()

    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert actions[0]["command"]["selection_source"] == "ocr"


@pytest.mark.smoke
def test_record_correction_pair_rejects_outlier_delta():
    """CUQ-3.8: a small candidate-point correction is learned; an implausibly
    large missed->landed delta (a mis-pairing) is rejected, not learned, so one
    noisy pair cannot bias the shared bucket's offset."""
    profile = ActuationProfile()
    bucket = {"control_role": "text", "size_bucket": "small", "region_zone": "center"}

    small = profile.record_correction_pair(
        control_bucket=bucket,
        method="mouse_tap",
        missed_point={"x": 100, "y": 100, "space": "frame_px"},
        landed_point={"x": 98, "y": 101, "space": "frame_px"},
    )
    assert small is not None
    offset = profile.entry_for_bucket(bucket).methods["mouse_tap"].offset
    assert offset is not None and offset.n == 1

    outlier = profile.record_correction_pair(
        control_bucket=bucket,
        method="mouse_tap",
        missed_point={"x": 10, "y": 10, "space": "frame_px"},
        landed_point={"x": 400, "y": 400, "space": "frame_px"},  # ~551px delta
    )
    assert outlier is None
    # The outlier did not update (bias) the learned offset.
    assert profile.entry_for_bucket(bucket).methods["mouse_tap"].offset.n == 1


@pytest.mark.smoke
def test_keyboard_focus_activate_emits_focus_landing_and_profile_stats(tmp_path):
    frames = [
        _frame(),  # target lookup
        _frame(),  # preflight
        _frame(),  # before_requested
        _frame(),  # before_command
        _frame(changed_roi=True),  # focus-evidence landing window
        _frame(changed_roi=True),  # stable after
    ]
    store = ArtifactStore(tmp_path, run_id="run")
    orchestrator = ActionOrchestrator(store)
    effector = MockEffector()
    phone = Phone(
        source=_ImageSource(frames),
        ocr=_TargetOCR(),
        effector=effector,
        action_orchestrator=orchestrator,
        action_fail_fast=False,
        perceive_cache_diff=0.0,
    )

    result = phone.keyboard_focus_activate("Go")
    orchestrator.close()

    assert result.semantic_status == "succeeded"
    assert effector.actions[0].op == "key"
    assert effector.actions[0].kwargs == {"modifier": 0, "keycode": 0x28}

    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    landing = next(event for event in audit if event["type"] == "actuation.landing_observed")
    attempt = next(event for event in audit if event["type"] == "actuation.attempt_attributed")
    assert landing["payload"]["method"] == "keyboard_focus_activate"
    assert landing["payload"]["landing_signal"] == "landed"
    assert landing["payload"]["landing_diff_artifact"]["window"] == "post_command_focus"
    assert attempt["payload"]["method"] == "keyboard_focus_activate"
    assert attempt["payload"]["label"] == "landed_ok"

    profile = json.loads((store.run_dir / "actuation_profile.json").read_text(encoding="utf-8"))
    method_stats = profile["entries"][0]["value"]["methods"]["keyboard_focus_activate"]
    assert method_stats["command_tries"] == 1
    assert method_stats["landed_attempts"] == 1
    assert method_stats["semantic_ok"] == 1


@pytest.mark.smoke
def test_profile_method_ranking_switches_target_tap_to_keyboard_focus(tmp_path):
    profile = ActuationProfile()
    bucket = {"control_role": "text", "size_bucket": "small", "region_zone": "center"}
    for _ in range(3):
        profile.record_attempt(
            control_bucket=bucket,
            method="mouse_tap",
            landing_signal="missed",
            label="missed",
        )
    profile.record_attempt(
        control_bucket=bucket,
        method="keyboard_focus_activate",
        landing_signal="landed",
        label="landed_ok",
    )
    store = ArtifactStore(tmp_path, run_id="run")
    orchestrator = ActionOrchestrator(store, actuation_profile=profile)
    effector = MockEffector()
    phone = Phone(
        source=_ImageSource([
            _frame(),
            _frame(),
            _frame(),
            _frame(),
            _frame(changed_roi=True),
            _frame(changed_roi=True),
        ]),
        ocr=_TargetOCR(),
        effector=effector,
        action_orchestrator=orchestrator,
        action_fail_fast=False,
        perceive_cache_diff=0.0,
    )

    result = phone.tap_text("Go")
    orchestrator.close()

    assert result.semantic_status == "succeeded"
    assert effector.actions[0].op == "key"
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    attempt = next(event for event in audit if event["type"] == "actuation.attempt_attributed")
    assert attempt["payload"]["method"] == "keyboard_focus_activate"


@pytest.mark.smoke
def test_actuation_profile_persists_by_platform_device_bucket(tmp_path):
    profile = ActuationProfile(platform="ios", os_version="unknown", device_model="iphone_test")
    profile.record_attempt(
        control_bucket={"control_role": "button", "size_bucket": "medium", "region_zone": "edge"},
        method="mouse_tap",
        landing_signal="landed",
        label="landed_ok",
    )

    saved = save_actuation_profile(profile, profile_dir=tmp_path)
    loaded = load_actuation_profile(platform="ios", device_model="iphone_test", profile_dir=tmp_path)

    assert saved.name == "ios_unknown_iphone_test.json"
    assert loaded.to_dict() == profile.to_dict()


@pytest.mark.smoke
def test_loaded_profile_drops_unactuatable_verdict_but_keeps_offset(tmp_path):
    """CUQ-3.6: a persisted calibration offset survives a reload, but a stale
    'unactuatable' verdict (and its evidence) does NOT — a transient hiccup that
    disabled a control class last run must not silently disable it on load."""
    from glassbox.action.actuation_profile import _method_is_unactuatable

    profile = ActuationProfile(platform="ios", os_version="unknown", device_model="iphone_test")
    bucket = {"control_role": "switch", "size_bucket": "small", "region_zone": "center"}
    profile.record_correction_pair(
        control_bucket=bucket, method="mouse_tap",
        missed_point={"x": 100, "y": 100, "space": "frame_px"},
        landed_point={"x": 98, "y": 101, "space": "frame_px"},
    )
    for i in range(5):  # drive the bucket unactuatable (5 negatives, distinct controls)
        profile.record_attempt(
            control_bucket=bucket, method="mouse_tap",
            landing_signal="missed", label="missed", target_identity={"intent": f"row_{i % 3}"},
        )
    pre = profile.entry_for_bucket(bucket).methods["mouse_tap"]
    assert _method_is_unactuatable(pre) and pre.offset is not None

    save_actuation_profile(profile, profile_dir=tmp_path)
    loaded = load_actuation_profile(platform="ios", device_model="iphone_test", profile_dir=tmp_path)

    lstats = loaded.entry_for_bucket(bucket).methods["mouse_tap"]
    assert not _method_is_unactuatable(lstats)          # verdict not carried
    assert lstats.command_tries == 0
    assert lstats.negative_identities == set()
    assert lstats.offset is not None                    # calibration offset preserved
    assert loaded.entry_for_bucket(bucket).actuability != "unactuatable"


@pytest.mark.smoke
def test_static_actuation_seed_and_recovery_seed_stay_separate():
    profile = ActuationProfile()
    profile.apply_seed({
        "schema_version": 1,
        "entries": [
            {
                "key": {
                    "platform": "ios",
                    "os_version": "unknown",
                    "device_model": "unknown",
                    "control_role": "button",
                    "size_bucket": "medium",
                    "region_zone": "center",
                },
                "value": {
                    "methods": {
                        "mouse_tap": {
                            "command_tries": 2,
                            "landed_attempts": 2,
                            "semantic_ok": 2,
                            "by_label": {"landed_ok": 2},
                            "last_outcome": "landed_ok",
                            "updated_at": "seed",
                            "source": "seed",
                        }
                    },
                    "actuability": "actuatable",
                    "calibration_version": 0,
                },
            }
        ],
    })

    entry = profile.entry_for_bucket({
        "control_role": "button",
        "size_bucket": "medium",
        "region_zone": "center",
    })

    assert entry is not None
    assert entry.methods["mouse_tap"].source == "seed"
    hint = recovery_hint(DEFAULT_RECOVERY_SEED, "ios_system_permission_dialog")
    assert hint is not None
    assert hint["profile_actuability"] == "not_applicable"


@pytest.mark.smoke
def test_raw_tap_xy_does_not_emit_actuation_profile_events(tmp_path):
    store = ArtifactStore(tmp_path, run_id="run")
    orchestrator = ActionOrchestrator(store)
    phone = Phone(
        source=_ImageSource([_frame(), _frame(), _frame(), _frame()]),
        ocr=_TargetOCR(),
        effector=MockEffector(),
        action_orchestrator=orchestrator,
        action_fail_fast=False,
        perceive_cache_diff=0.0,
    )

    phone.tap_xy(14, 14)
    orchestrator.close()

    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    assert not [event for event in audit if event["type"].startswith("actuation.")]
