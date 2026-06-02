"""Tests for centralized glassbox config."""

from __future__ import annotations

import pytest

from glassbox.config import AgentConfig, get_config


@pytest.mark.smoke
def test_defaults():
    cfg = AgentConfig(_env_file=None)
    assert cfg.hdmi_index == 0
    assert cfg.hdmi_fps == 30
    assert cfg.no_hdmi is False
    assert cfg.frame_dir is None
    assert cfg.auto_recover_capture is False
    assert cfg.allow_noop_fallback is False
    assert cfg.effector_backend == "noop"
    assert cfg.picokvm is False
    assert cfg.wheel_ticks_per_scroll == 90
    assert cfg.wheel_invert is False
    assert cfg.effector_crop_bbox is None
    assert cfg.app_viewport_bbox is None
    assert cfg.app_viewport_mode == "auto"
    assert cfg.default_observation_scope == "device"
    assert cfg.effector_crop_cache is None
    assert cfg.effector_crop_retries == 3
    assert cfg.phone_model == "iphone_17_pro_max"
    assert cfg.ocr == "vision"
    assert cfg.crawl_policy == "generic"
    assert cfg.enable_vlm is None
    assert cfg.enable_kimi is False
    assert cfg.vlm == "moonshot"
    assert cfg.vlm_cache_dir is None
    assert cfg.kimi_cache_dir is None
    assert cfg.action_fail_fast is True
    assert cfg.ocr_temporal_voting_enabled is False
    assert cfg.ocr_temporal_voting_frames == 3
    assert cfg.ocr_temporal_voting_min_presence == 2
    assert cfg.ocr_temporal_voting_pos_tol == 20
    assert cfg.ocr_temporal_voting_sample_spacing_ms == 0
    assert cfg.ocr_temporal_voting_outer_timeout == 0.0
    assert cfg.ocr_temporal_voting_keep_raw_samples is False
    assert cfg.ocr_minimum_text_height is None
    assert cfg.ocr_confidence_threshold is None
    assert cfg.ocr_unsharp_mask is None
    assert cfg.ocr_unsharp_sigma is None
    assert cfg.ocr_unsharp_amount is None
    assert cfg.ocr_tiling_enabled is False
    assert cfg.ocr_tiling_rows == 2
    assert cfg.ocr_tiling_cols == 2
    assert cfg.ocr_tiling_overlap == 0.15
    assert cfg.ocr_tiling_include_full_frame is True
    assert cfg.ocr_tiling_nms_iou == 0.55


@pytest.mark.smoke
def test_env_override_int(monkeypatch):
    monkeypatch.setenv("GLASSBOX_HDMI_INDEX", "2")
    monkeypatch.setenv("GLASSBOX_WHEEL_TICKS_PER_SCROLL", "11")
    monkeypatch.setenv("GLASSBOX_EFFECTOR_CROP_RETRIES", "4")
    monkeypatch.setenv("GLASSBOX_ENABLE_VLM", "1")
    monkeypatch.setenv("GLASSBOX_VLM_CACHE_DIR", "/tmp/vlm-cache")
    monkeypatch.setenv("GLASSBOX_CRAWL_POLICY", "ios_settings")
    monkeypatch.setenv("GLASSBOX_APP_VIEWPORT_BBOX", "10,20,300,600")
    monkeypatch.setenv("GLASSBOX_APP_VIEWPORT_MODE", "iphone_compat")
    monkeypatch.setenv("GLASSBOX_DEFAULT_OBSERVATION_SCOPE", "app")
    monkeypatch.setenv("GLASSBOX_OCR_TEMPORAL_VOTING_FRAMES", "4")
    monkeypatch.setenv("GLASSBOX_OCR_TEMPORAL_VOTING_MIN_PRESENCE", "3")
    monkeypatch.setenv("GLASSBOX_OCR_MINIMUM_TEXT_HEIGHT", "0.0")
    monkeypatch.setenv("GLASSBOX_OCR_CONFIDENCE_THRESHOLD", "0.2")
    monkeypatch.setenv("GLASSBOX_OCR_UNSHARP_SIGMA", "0.8")
    monkeypatch.setenv("GLASSBOX_OCR_UNSHARP_AMOUNT", "1.2")
    monkeypatch.setenv("GLASSBOX_OCR_TILING_ROWS", "3")
    monkeypatch.setenv("GLASSBOX_OCR_TILING_COLS", "4")
    monkeypatch.setenv("GLASSBOX_OCR_TILING_OVERLAP", "0.2")
    monkeypatch.setenv("GLASSBOX_OCR_TILING_NMS_IOU", "0.6")

    cfg = AgentConfig(_env_file=None)

    assert cfg.hdmi_index == 2
    assert cfg.wheel_ticks_per_scroll == 11
    assert cfg.effector_crop_retries == 4
    assert cfg.enable_vlm is True
    assert cfg.vlm_cache_dir == "/tmp/vlm-cache"
    assert cfg.crawl_policy == "ios_settings"
    assert cfg.app_viewport_bbox == (10, 20, 300, 600)
    assert cfg.app_viewport_mode == "iphone_compat"
    assert cfg.default_observation_scope == "app"
    assert cfg.ocr_temporal_voting_frames == 4
    assert cfg.ocr_temporal_voting_min_presence == 3
    assert cfg.ocr_minimum_text_height == 0.0
    assert cfg.ocr_confidence_threshold == 0.2
    assert cfg.ocr_unsharp_sigma == 0.8
    assert cfg.ocr_unsharp_amount == 1.2
    assert cfg.ocr_tiling_rows == 3
    assert cfg.ocr_tiling_cols == 4
    assert cfg.ocr_tiling_overlap == 0.2
    assert cfg.ocr_tiling_nms_iou == 0.6


@pytest.mark.smoke
def test_env_override_bool(monkeypatch):
    monkeypatch.setenv("GLASSBOX_NO_HDMI", "1")
    monkeypatch.setenv("GLASSBOX_AUTO_RECOVER_CAPTURE", "1")
    monkeypatch.setenv("GLASSBOX_PICOKVM", "true")
    monkeypatch.setenv("GLASSBOX_OCR_UNSHARP_MASK", "0")
    monkeypatch.setenv("GLASSBOX_WHEEL_INVERT", "true")
    monkeypatch.setenv("GLASSBOX_ALLOW_NOOP_FALLBACK", "true")
    monkeypatch.setenv("GLASSBOX_ACTION_FAIL_FAST", "false")
    monkeypatch.setenv("GLASSBOX_OCR_TEMPORAL_VOTING_ENABLED", "true")
    monkeypatch.setenv("GLASSBOX_OCR_TEMPORAL_VOTING_KEEP_RAW_SAMPLES", "true")
    monkeypatch.setenv("GLASSBOX_OCR_TILING_ENABLED", "true")
    monkeypatch.setenv("GLASSBOX_OCR_TILING_INCLUDE_FULL_FRAME", "false")

    cfg = AgentConfig(_env_file=None)

    assert cfg.no_hdmi is True
    assert cfg.auto_recover_capture is True
    assert cfg.picokvm is True
    assert cfg.wheel_invert is True
    assert cfg.allow_noop_fallback is True
    assert cfg.action_fail_fast is False
    assert cfg.ocr_temporal_voting_enabled is True
    assert cfg.ocr_temporal_voting_keep_raw_samples is True
    assert cfg.ocr_unsharp_mask is False
    assert cfg.ocr_tiling_enabled is True
    assert cfg.ocr_tiling_include_full_frame is False


@pytest.mark.smoke
def test_effector_env_aliases(monkeypatch):
    monkeypatch.setenv("AGENT_PICOKVM", "1")
    monkeypatch.setenv("AGENT_EFFECTOR", "toy")

    cfg = AgentConfig(_env_file=None)

    assert cfg.picokvm is True
    assert cfg.effector_backend == "toy"


@pytest.mark.smoke
def test_invalid_ocr_config_is_rejected():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AgentConfig(_env_file=None, ocr="paddle")


@pytest.mark.smoke
def test_semantic_plan_ops_default_on_validated(monkeypatch):
    """The P1/P2 strategy ladder is ON by default for back/scroll/tap after the
    2026-05-29 on-rig A/B (`make ab-semantic-plan`, iPhone 17 Pro Max) showed no
    regression and a clear win (see config.py / the rig-validation runbook).
    Widening the op set requires re-running that A/B."""
    monkeypatch.delenv("GLASSBOX_SEMANTIC_PLAN_OPS", raising=False)
    assert AgentConfig(_env_file=None).semantic_plan_ops == "back,scroll,tap"


@pytest.mark.smoke
def test_semantic_plan_ops_env_override(monkeypatch):
    """An explicit env value overrides the validated default (e.g. narrow to one
    op, or empty-string back to the legacy single-strategy path)."""
    monkeypatch.setenv("GLASSBOX_SEMANTIC_PLAN_OPS", "back")
    cfg = AgentConfig(_env_file=None)
    assert cfg.semantic_plan_ops == "back"
    # The runtime parses this raw string into the per-op routing set (the same
    # split build_phone() applies); routing-when-flagged itself is covered by
    # test_computer_use_runtime.py.
    ops = {op.strip() for op in cfg.semantic_plan_ops.split(",") if op.strip()}
    assert ops == {"back"}


@pytest.mark.smoke
def test_profile_bundle_default_none(monkeypatch):
    monkeypatch.delenv("GLASSBOX_PROFILE_BUNDLE", raising=False)
    assert AgentConfig(_env_file=None).profile_bundle is None


@pytest.mark.smoke
def test_profile_bundle_env_override(monkeypatch):
    monkeypatch.setenv("GLASSBOX_PROFILE_BUNDLE", "com.example.app")
    assert AgentConfig(_env_file=None).profile_bundle == "com.example.app"


@pytest.mark.smoke
def test_explicit_arg_beats_env(monkeypatch):
    monkeypatch.setenv("GLASSBOX_HDMI_INDEX", "5")
    cfg = AgentConfig(hdmi_index=9, _env_file=None)
    assert cfg.hdmi_index == 9


@pytest.mark.smoke
def test_phone_size_resolves_from_model():
    cfg = AgentConfig(phone_model="iphone_17_pro_max", _env_file=None)
    assert cfg.phone_size() == (1320, 2868)
    assert cfg.phone_points() == (440, 956)


@pytest.mark.smoke
def test_ipad_mini_7_phone_size_resolves_from_model():
    cfg = AgentConfig(phone_model="ipad_mini_7", _env_file=None)
    assert cfg.phone_size() == (1488, 2266)
    assert cfg.phone_points() == (744, 1133)


@pytest.mark.smoke
def test_phone_size_unknown_model_raises():
    cfg = AgentConfig(phone_model="nokia_3310", _env_file=None)
    with pytest.raises(KeyError):
        cfg.phone_size()


@pytest.mark.smoke
def test_get_config_cache_clear(monkeypatch):
    get_config.cache_clear()
    monkeypatch.setenv("GLASSBOX_HDMI_INDEX", "7")
    assert get_config().hdmi_index == 7
    get_config.cache_clear()
