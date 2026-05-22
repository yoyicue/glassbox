"""skills/smoke/test_vlm_kimi.py

Unit tests for Layer 3 Kimi enrich_scene. No network; FakeKimi returns a fixed
payload, and we verify:
  - intent_label is populated by id
  - scene_type is populated
  - misaligned ids / missing fields neither crash nor corrupt
  - graceful degradation on empty elements / Kimi exceptions

For real Kimi calls see scripts/probe_kimi_grounding.py (billed).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pytest

import glassbox.cognition.vlm_kimi as vlm_mod
from glassbox.cognition import (
    Box,
    KimiAnthropic,
    KimiResponse,
    KimiVL,
    MoonshotAnthropicVLM,
    Scene,
    SiliconFlowVLM,
    UIElement,
    VLMRequest,
    VLMResponse,
    VLMResult,
    enrich_scene,
    make_kimi_client,
    make_vlm_client,
    vlm_stage_outcome_from_result,
)
from glassbox.perception.source import Frame


# ─── FakeKimi: implements a method named like KimiVL.describe_scene ──
@dataclass
class FakeKimi:
    """Records the elements passed in + returns a preset parsed payload."""
    parsed_payload: dict[str, Any] | None
    raise_exc: Exception | None = None
    last_elements: list[dict[str, Any]] | None = None
    last_hint: str | None = None

    def describe_scene(self, *, frame_image, elements, scene_hint=None):
        self.last_elements = list(elements)
        self.last_hint = scene_hint
        if self.raise_exc:
            raise self.raise_exc
        return KimiResponse(
            raw_content="(fake)",
            parsed=self.parsed_payload,
            usage={"prompt_tokens": 0, "completion_tokens": 0},
            model="fake",
            elapsed_ms=1,
        )


def _scene_with(*elements: UIElement) -> Scene:
    return Scene(frame_id=0, timestamp=0.0, elements=list(elements))


def _ocr_el(eid: int, text: str, *, type_="text") -> UIElement:
    return UIElement(
        type=type_,
        box=Box(x=10, y=10, w=100, h=20),
        text=text,
        confidence=0.9,
        element_id=eid,
    )


@pytest.mark.smoke
def test_vlm_neutral_public_names_keep_legacy_aliases():
    assert VLMResponse is VLMResult
    assert KimiResponse is VLMResponse
    assert KimiVL is SiliconFlowVLM
    assert KimiAnthropic is MoonshotAnthropicVLM
    assert make_kimi_client is make_vlm_client


@pytest.mark.smoke
def test_make_vlm_client_prefers_neutral_env(monkeypatch):
    calls: list[str] = []

    class FakeMoonshot:
        def __init__(self, **_kwargs):
            calls.append("moonshot")

    class FakeSiliconFlow:
        def __init__(self, **_kwargs):
            calls.append("siliconflow")

    monkeypatch.setenv("VLM_BACKEND", "siliconflow")
    monkeypatch.setenv("KIMI_BACKEND", "anthropic")
    monkeypatch.setattr(vlm_mod, "MoonshotAnthropicVLM", FakeMoonshot)
    monkeypatch.setattr(vlm_mod, "SiliconFlowVLM", FakeSiliconFlow)

    client = make_vlm_client()

    assert isinstance(client, FakeSiliconFlow)
    assert calls == ["siliconflow"]


@pytest.mark.smoke
def test_vlm_stage_outcome_is_typed_boundary_product():
    outcome = vlm_stage_outcome_from_result(
        VLMResult(
            raw_content="{}",
            parsed={
                "scene_type": "login_form",
                "elements": [
                    {"id": "7", "intent_label": " 确认登录 "},
                    {"id": 8, "intent_label": ""},
                    {"id": "bad", "intent_label": "ignored"},
                ],
            },
            usage={},
            model="fake",
            elapsed_ms=1,
        )
    )

    assert outcome.status == "ok"
    assert outcome.element_intents == {7: "确认登录"}
    assert outcome.classification is not None
    assert outcome.classification.source == "vlm"
    assert outcome.classification.semantic_scene_type == "login_form"


@pytest.mark.smoke
def test_vlm_stage_outcome_reports_parse_error():
    outcome = vlm_stage_outcome_from_result(
        VLMResult(raw_content="null", parsed=None, usage={}, model="fake", elapsed_ms=1)
    )

    assert outcome.status == "parse_error"
    assert outcome.error == "invalid parsed payload"
    assert outcome.element_intents == {}
    assert outcome.classification is None


# ─── happy path ──────────────────────────────────────────────────────
@pytest.mark.smoke
def test_enrich_scene_fills_intent_and_scene_type():
    scene = _scene_with(
        _ocr_el(0, "登录", type_="button"),
        _ocr_el(1, "忘记密码", type_="text"),
    )
    kimi = FakeKimi(parsed_payload={
        "scene_type": "login_form",
        "elements": [
            {"id": 0, "intent_label": "确认登录", "purpose": "提交账号密码", "confidence": 0.95},
            {"id": 1, "intent_label": "找回密码", "purpose": "进入密码重置流程", "confidence": 0.8},
        ],
    })
    enrich_scene(scene, frame_image=b"<png>", client=kimi)

    assert scene.scene_type == "login_form"
    assert scene.semantic_scene_type == "login_form"
    assert scene.vlm_described is True
    assert scene.vlm_status == "ok"
    assert scene.vlm_model == "fake"
    assert scene.vlm_usage == {"prompt_tokens": 0, "completion_tokens": 0}
    assert scene.elements[0].intent_label == "确认登录"
    assert scene.elements[0].intent_confidence == 0.95
    assert scene.elements[0].intent_source == "vlm"
    assert scene.elements[1].intent_label == "找回密码"
    assert scene.vlm_requested_element_ids == [0, 1]
    assert scene.vlm_returned_element_ids == [0, 1]
    assert scene.vlm_missing_element_ids == []
    assert scene.vlm_intent_coverage == 1.0


@pytest.mark.smoke
def test_enrich_scene_passes_hint_to_kimi():
    scene = _scene_with(_ocr_el(0, "继续"))
    kimi = FakeKimi(parsed_payload={"scene_type": "paywall", "elements": []})
    enrich_scene(scene, b"<png>", kimi, scene_hint="评估订阅按钮位置")
    assert kimi.last_hint == "评估订阅按钮位置"
    # the elements payload must be passed to Kimi following the schema
    assert kimi.last_elements == [
        {"id": 0, "text": "继续", "type": "text", "box": [10, 10, 110, 30]},
    ]


@pytest.mark.smoke
def test_enrich_scene_uses_vlm_request_when_frame_is_available():
    class RequestKimi:
        model = "request-kimi"

        def __init__(self):
            self.request = None

        def describe_scene(self, request):
            self.request = request
            return KimiResponse(
                raw_content="{}",
                parsed={"scene_type": "login_form", "elements": []},
                usage={},
                model="request-kimi",
                elapsed_ms=1,
            )

    scene = _scene_with(_ocr_el(0, "登录"))
    frame = Frame(img=np.zeros((20, 20, 3), dtype=np.uint8), ts=1.0)
    kimi = RequestKimi()

    enrich_scene(scene, frame, kimi, scene_hint="登录")

    assert isinstance(kimi.request, VLMRequest)
    assert kimi.request.image is frame
    assert kimi.request.scene_hint == "登录"
    assert kimi.request.elements[0].text == "登录"
    assert scene.scene_type == "login_form"


# ─── fault tolerance ─────────────────────────────────────────────────
@pytest.mark.smoke
def test_enrich_scene_skips_unknown_ids():
    """Kimi returns a nonexistent id; it should neither crash nor affect others."""
    scene = _scene_with(_ocr_el(0, "登录"))
    kimi = FakeKimi(parsed_payload={
        "scene_type": "login_form",
        "elements": [
            {"id": 999, "intent_label": "??"},      # nonexistent
            {"id": 0, "intent_label": "确认登录"},
        ],
    })
    enrich_scene(scene, b"<png>", kimi)
    assert scene.elements[0].intent_label == "确认登录"


@pytest.mark.smoke
def test_enrich_scene_handles_missing_intent_label():
    existing = _ocr_el(1, "X")
    existing.intent_label = "关闭旧弹窗"
    scene = _scene_with(_ocr_el(0, "登录"), existing)
    kimi = FakeKimi(parsed_payload={
        "scene_type": "modal",
        "elements": [
            {"id": 0},                                # no intent_label
            {"id": 1, "intent_label": "", "confidence": 0.4},  # authoritative clear
        ],
    })
    enrich_scene(scene, b"<png>", kimi)
    assert scene.elements[0].intent_label is None
    assert scene.elements[1].intent_label is None
    assert scene.elements[1].intent_confidence == 0.4
    assert scene.elements[1].intent_source == "vlm"
    assert scene.scene_type == "modal"


@pytest.mark.smoke
def test_enrich_scene_clears_omitted_stale_intent_labels_and_records_coverage():
    omitted = _ocr_el(1, "旧按钮")
    omitted.intent_label = "旧动作"
    omitted.intent_source = "vlm"
    scene = _scene_with(_ocr_el(0, "登录"), omitted)
    kimi = FakeKimi(parsed_payload={
        "scene_type": "login_form",
        "elements": [{"id": 0, "intent_label": "确认登录"}],
    })

    enrich_scene(scene, b"<png>", kimi)

    assert scene.elements[1].intent_label is None
    assert scene.elements[1].intent_source is None
    assert scene.vlm_returned_element_ids == [0]
    assert scene.vlm_missing_element_ids == [1]
    assert scene.vlm_intent_coverage == 0.5


@pytest.mark.smoke
def test_enrich_scene_uses_surrogate_request_ids_for_duplicate_element_ids():
    first = _ocr_el(0, "登录")
    second = _ocr_el(0, "忘记密码")
    scene = _scene_with(first, second)
    kimi = FakeKimi(parsed_payload={
        "scene_type": "login_form",
        "elements": [
            {"id": 0, "intent_label": "确认登录", "confidence": 0.9},
            {"id": 1, "intent_label": "找回密码", "confidence": 0.8},
        ],
    })

    enrich_scene(scene, b"<png>", kimi)

    assert [item["id"] for item in kimi.last_elements] == [0, 1]
    assert first.intent_label == "确认登录"
    assert second.intent_label == "找回密码"
    assert scene.vlm_requested_element_ids == [0, 1]
    assert scene.vlm_returned_element_ids == [0, 1]
    assert scene.vlm_missing_element_ids == []
    assert scene.vlm_intent_coverage == 1.0


@pytest.mark.smoke
def test_enrich_scene_kimi_raises_does_not_propagate():
    """Kimi network error / parse error → enrich_scene swallows the exception and returns the scene unchanged."""
    scene = _scene_with(_ocr_el(0, "登录"))
    kimi = FakeKimi(parsed_payload=None, raise_exc=RuntimeError("kimi down"))
    out = enrich_scene(scene, b"<png>", kimi)
    assert out is scene
    assert scene.vlm_described is False
    assert scene.vlm_status == "error"
    assert scene.vlm_error == "kimi down"
    assert scene.elements[0].intent_label is None
    assert scene.scene_type is None


@pytest.mark.smoke
def test_enrich_scene_empty_elements_skips_call():
    """An empty scene should not waste a Kimi call."""
    scene = _scene_with()
    kimi = FakeKimi(parsed_payload={"scene_type": "x", "elements": []})
    enrich_scene(scene, b"<png>", kimi)
    assert kimi.last_elements is None   # never called
    assert scene.vlm_status == "skipped_empty"
    assert scene.vlm_described is False


@pytest.mark.smoke
def test_enrich_scene_truncates_overlong_label():
    """If Kimi happens to return an overlong label, it should not corrupt the scene."""
    scene = _scene_with(_ocr_el(0, "登录"))
    kimi = FakeKimi(parsed_payload={
        "scene_type": "x",
        "elements": [{"id": 0, "intent_label": "确认" * 30}],
    })
    enrich_scene(scene, b"<png>", kimi)
    assert len(scene.elements[0].intent_label) <= 32


@pytest.mark.smoke
def test_enrich_scene_invalid_parsed_payload():
    """Kimi returns something that is not a dict (null / list / str); the scene stays untouched."""
    scene = _scene_with(_ocr_el(0, "登录"))
    kimi = FakeKimi(parsed_payload=None)
    enrich_scene(scene, b"<png>", kimi)
    assert scene.elements[0].intent_label is None
    assert scene.vlm_status == "parse_error"
    assert scene.vlm_error == "invalid parsed payload"


# ─── app_state ─────────────────────────────────────────────────────
@pytest.mark.smoke
def test_enrich_scene_writes_app_state():
    scene = _scene_with(_ocr_el(0, "设置"))
    kimi = FakeKimi(parsed_payload={
        "scene_type": "settings",
        "app_state": {
            "subscription": "subscribed",
            "auth": "logged_in",
            "current_view": "设置",
            "unread_count": "3",
        },
        "elements": [],
    })
    enrich_scene(scene, b"<png>", kimi)
    assert scene.app_state == {
        "subscription": "subscribed",
        "auth": "logged_in",
        "current_view": "设置",
        "unread_count": "3",
    }


@pytest.mark.smoke
def test_enrich_scene_writes_context_and_available_intents():
    scene = _scene_with(_ocr_el(0, "登录"))
    kimi = FakeKimi(parsed_payload={
        "scene_type": "login_form",
        "context": "  账号登录页  ",
        "available_intents": ["确认登录", "确认登录", "", 42, "找回密码"],
        "elements": [],
    })
    enrich_scene(scene, b"<png>", kimi)

    assert scene.context == "账号登录页"
    assert scene.available_intents == ["确认登录", "找回密码"]


@pytest.mark.smoke
def test_enrich_scene_app_state_keeps_unknown_as_clear_signal_and_filters_non_str():
    scene = _scene_with(_ocr_el(0, "x"))
    kimi = FakeKimi(parsed_payload={
        "scene_type": "main",
        "app_state": {
            "subscription": "unknown",   # kept so memory can clear stale state
            "auth": "logged_in",
            "count": 42,                 # non-string value should be filtered out
            42: "weird",                  # non-string key should be filtered out
            "current_view": " 控制 ",    # should be stripped
        },
        "elements": [],
    })
    enrich_scene(scene, b"<png>", kimi)
    assert scene.app_state == {
        "subscription": "unknown",
        "auth": "logged_in",
        "current_view": "控制",
    }


@pytest.mark.smoke
def test_enrich_scene_app_state_missing_does_not_break():
    """An older Kimi response without app_state keeps scene.app_state at the default {}."""
    scene = _scene_with(_ocr_el(0, "x"))
    kimi = FakeKimi(parsed_payload={"scene_type": "main", "elements": []})
    enrich_scene(scene, b"<png>", kimi)
    assert scene.app_state == {}


@pytest.mark.smoke
def test_enrich_scene_app_state_value_truncates():
    """An overlong value is truncated to 32 characters."""
    scene = _scene_with(_ocr_el(0, "x"))
    kimi = FakeKimi(parsed_payload={
        "app_state": {"current_view": "x" * 100},
        "elements": [],
    })
    enrich_scene(scene, b"<png>", kimi)
    assert len(scene.app_state["current_view"]) == 32
