from __future__ import annotations

import numpy as np
import pytest

from glassbox.action import (
    ActuationProfile,
    navigate_via_memory_path,
    prepare_navigation_measurement_origin,
)
from glassbox.cognition import Box, Scene, SceneClassification, SceneClassificationPrior, UIElement
from glassbox.cognition.vlm_kimi import VLMResponse
from glassbox.effector import ActionResult
from glassbox.memory import UTG, ActionRecord, ScreenMemory
from glassbox.perception.source import Frame
from glassbox.phone import Phone


def _el(text: str, x: int = 20, y: int = 120, *, ty: str = "text") -> UIElement:
    return UIElement(type=ty, box=Box(x=x, y=y, w=160, h=30), text=text, confidence=0.9)


def _scene(*elements: UIElement) -> Scene:
    return Scene(frame_id=0, timestamp=0.0, elements=list(elements))


@pytest.mark.smoke
def test_scene_classification_prior_comes_from_recognized_memory_node_and_last_action():
    known = _scene(_el("Dashboard"), _el("Search", y=180))
    known.platform_scene_kind = "app_home"
    known.page_id = "app/home"
    known.classification_source = "app"
    memory = ScreenMemory(UTG(bundle_id="com.example.app"))
    node = memory.observe(known)
    received: list[SceneClassificationPrior | None] = []

    def prior_aware_classifier(
        scene: Scene,
        *,
        viewport_size: tuple[int, int] | None = None,
        prior: SceneClassificationPrior | None = None,
    ) -> SceneClassification | None:
        del scene
        received.append(prior)
        assert viewport_size == (320, 240)
        assert prior is not None
        return SceneClassification(
            page_id=prior.page_id,
            platform_scene_kind=prior.platform_scene_kind,
            confidence=0.9,
            source="app",
            evidence=("memory_prior",),
        )

    phone = Phone(
        source=None,
        ocr=None,
        effector=None,
        memory=memory,
        scene_classifiers=[prior_aware_classifier],
    )
    phone.action_context.pending_actions_for_memory = [
        ActionRecord.from_op("tap", {"target": "Search", "via": "tap_text", "action_ok": True})
    ]
    fresh = _scene(_el("Dashboard"), _el("Search", y=180))

    phone.apply_scene_classifiers(fresh, np.zeros((240, 320, 3), dtype=np.uint8))

    assert len(received) == 1
    prior = received[0]
    assert prior is not None
    assert prior.screen_id == node.screen_id
    assert prior.page_id == "app/home"
    assert prior.platform_scene_kind == "app_home"
    assert prior.last_action_op == "tap"
    assert prior.last_action_target == "Search"
    assert prior.last_action_via == "tap_text"
    assert phone.action_context.pending_actions_for_memory
    assert fresh.page_id == "app/home"
    assert fresh.platform_scene_kind == "app_home"
    assert fresh.classification_evidence == ["memory_prior"]


@pytest.mark.smoke
def test_scene_classifier_without_prior_parameter_remains_compatible():
    calls: list[tuple[int, int] | None] = []

    def legacy_classifier(scene: Scene, viewport_size: tuple[int, int] | None) -> SceneClassification:
        del scene
        calls.append(viewport_size)
        return SceneClassification(
            platform_scene_kind="legacy_surface",
            confidence=0.4,
            source="platform",
        )

    phone = Phone(source=None, ocr=None, effector=None, scene_classifiers=[legacy_classifier])
    scene = _scene(_el("Legacy"))

    phone.apply_scene_classifiers(scene, np.zeros((20, 30, 3), dtype=np.uint8))

    assert calls == [(30, 20)]
    assert scene.platform_scene_kind == "legacy_surface"


@pytest.mark.smoke
def test_uncertain_scene_classifier_triggers_vlm_arbitration_and_vlm_kind_wins():
    class FakeKimi:
        model = "fake"

        def __init__(self):
            self.calls = 0
            self.last_hint = None

        def describe_scene(self, *, frame_image, elements, scene_hint=None):
            del frame_image, elements
            self.calls += 1
            self.last_hint = scene_hint
            return VLMResponse(
                raw_content="{}",
                parsed={
                    "scene_type": "app_store",
                    "platform_scene_kind": "unknown",
                    "elements": [{"id": 0, "intent_label": ""}],
                },
                usage={},
                model="fake",
                elapsed_ms=1,
            )

    def uncertain_classifier(scene: Scene, viewport_size: tuple[int, int] | None) -> SceneClassification:
        del scene, viewport_size
        return SceneClassification(
            page_id="settings/Apps",
            platform_scene_kind="settings_detail",
            confidence=0.7,
            source="platform",
            safe_actions=("trace", "vlm_on_uncertain"),
            evidence=("weak_settings_detail",),
        )

    img = np.zeros((20, 30, 3), dtype=np.uint8)
    kimi = FakeKimi()
    phone = Phone(
        source=None,
        ocr=None,
        effector=None,
        kimi=kimi,
        scene_classifiers=[uncertain_classifier],
    )
    phone.action_context.last_frame = Frame(img=img, ts=0.0)
    scene = _scene(_el("Apps"))

    phone.apply_scene_classifiers(scene, img)

    assert kimi.calls == 1
    assert kimi.last_hint == "scene_arbitration:vlm_on_uncertain"
    assert scene.semantic_scene_type == "app_store"
    assert scene.platform_scene_kind == "unknown"
    assert scene.page_id is None
    assert scene.safe_actions == []
    assert scene.classification_source == "vlm"


@pytest.mark.smoke
def test_existing_vlm_scene_arbitration_survives_classifier_rerun():
    def stale_classifier(scene: Scene, viewport_size: tuple[int, int] | None) -> SceneClassification:
        del scene, viewport_size
        return SceneClassification(
            page_id="settings/Apps",
            platform_scene_kind="settings_detail",
            confidence=0.7,
            source="platform",
            safe_actions=("back", "edge_back"),
            evidence=("stale_settings_detail",),
        )

    phone = Phone(source=None, ocr=None, effector=None, scene_classifiers=[stale_classifier])
    scene = _scene(_el("Apps"))
    scene.vlm_status = "ok"
    scene.semantic_scene_type = "app_store"
    scene.platform_scene_kind = "unknown"
    scene.classification_source = "vlm"
    scene.classification_evidence = ["vlm_platform_scene_kind"]

    phone.apply_scene_classifiers(scene, np.zeros((20, 30, 3), dtype=np.uint8))

    assert scene.semantic_scene_type == "app_store"
    assert scene.platform_scene_kind == "unknown"
    assert scene.page_id is None
    assert scene.safe_actions == []
    assert scene.classification_source == "vlm"


class _HomePhone:
    def __init__(self, result: ActionResult | BaseException):
        self.result = result
        self.calls = 0

    def home(self):
        self.calls += 1
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class _Edge:
    def __init__(self, action_op: str):
        self.action_op = action_op


class _MemoryNavPhone:
    def __init__(self, *, path, arrive_page: str):
        self.memory = self
        self.path = path
        self.arrive_page = arrive_page
        self.replayed = 0
        self.back_calls = 0
        self.home_calls = 0
        self.path_queries: list[dict] = []

    def perceive(self, *, fresh=None):
        del fresh
        return object()

    def recognize(self, scene, frame_img=None):
        del scene, frame_img
        if self.path is None:
            return None
        if self.replayed >= len(self.path):
            return type("Node", (), {"screen_id": "target", "page_id": self.arrive_page})()
        return type("Node", (), {"screen_id": "start", "page_id": "app/detail"})()

    def path_to_page(self, from_id, page_id, *, scene_type=None, allowed_actions=None, min_success_rate=0.0):
        self.path_queries.append(
            {
                "from_id": from_id,
                "page_id": page_id,
                "scene_type": scene_type,
                "allowed_actions": set(allowed_actions or ()),
                "min_success_rate": min_success_rate,
            }
        )
        return self.path

    def back_gesture(self):
        self.back_calls += 1
        self.replayed += 1
        return ActionResult(ok=True, backend="fake", connected=True, semantic_status="succeeded")

    def home(self):
        self.home_calls += 1
        self.replayed += 1
        return ActionResult(ok=True, backend="fake", connected=True, semantic_status="succeeded")


@pytest.mark.smoke
def test_navigate_via_memory_path_replays_learned_path_without_home_fallback():
    phone = _MemoryNavPhone(path=[_Edge("back"), _Edge("back")], arrive_page="app/root")

    result = navigate_via_memory_path(phone, "app/root", min_success_rate=0.75)

    assert result.reached is True
    assert result.reason == "reached"
    assert result.from_id == "start"
    assert result.edge_count == 2
    assert result.replayed_ops == ("back", "back")
    assert phone.back_calls == 2
    assert phone.home_calls == 0
    assert phone.path_queries == [
        {
            "from_id": "start",
            "page_id": "app/root",
            "scene_type": None,
            "allowed_actions": {"home", "back"},
            "min_success_rate": 0.75,
        }
    ]


@pytest.mark.smoke
def test_navigate_via_memory_path_is_proactive_not_home_recovery():
    phone = _MemoryNavPhone(path=None, arrive_page="app/root")

    result = navigate_via_memory_path(phone, "app/root")

    assert result.reached is False
    assert result.reason == "current_screen_unrecognized"
    assert phone.home_calls == 0


@pytest.mark.smoke
def test_navigate_via_memory_path_requires_arrival_confirmation():
    phone = _MemoryNavPhone(path=[_Edge("back")], arrive_page="app/elsewhere")

    result = navigate_via_memory_path(phone, "app/root")

    assert result.reached is False
    assert result.reason == "arrival_unconfirmed"
    assert result.replayed_ops == ("back",)
    assert phone.home_calls == 0


@pytest.mark.smoke
def test_actuation_profile_live_feedback_deadvertises_failed_method_within_run():
    profile = ActuationProfile()
    bucket = {"control_role": "button", "size_bucket": "small", "region_zone": "center"}

    for index in range(4):
        profile.record_attempt(
            control_bucket=bucket,
            method="mouse_tap",
            landing_signal="missed",
            label="missed",
            target_identity={"intent": f"control_{index % 2}"},
        )
        skip, reason = profile.should_skip_bucket(bucket, method="mouse_tap")
        assert (skip, reason) == (False, None)

    profile.record_attempt(
        control_bucket=bucket,
        method="mouse_tap",
        landing_signal="missed",
        label="missed",
        target_identity={"intent": "control_2"},
    )

    skip, reason = profile.should_skip_bucket(bucket, method="mouse_tap")
    assert (skip, reason) == (True, "unactuatable")


@pytest.mark.smoke
def test_navigation_measurement_origin_requires_verified_home_before_clock_starts():
    verified = _HomePhone(
        ActionResult(
            ok=True,
            backend="fake",
            connected=True,
            semantic_status="succeeded",
            semantic_verifier="ios_home_screen_visible",
        )
    )
    unverified = _HomePhone(ActionResult(ok=True, backend="fake", connected=True))

    ready = prepare_navigation_measurement_origin(verified)
    blocked = prepare_navigation_measurement_origin(unverified)

    assert ready.can_start_clock is True
    assert ready.home_reached is True
    assert ready.reason == "verified_home_reached"
    assert verified.calls == 1
    assert blocked.can_start_clock is False
    assert blocked.home_reached is False
    assert blocked.reason == "home_unverified"
    assert unverified.calls == 1


@pytest.mark.smoke
def test_navigation_measurement_origin_reports_home_precondition_failures():
    failed = _HomePhone(
        ActionResult(
            ok=False,
            backend="fake",
            connected=True,
            error="transport unavailable",
        )
    )
    raised = _HomePhone(RuntimeError("boom"))

    failed_origin = prepare_navigation_measurement_origin(failed)
    raised_origin = prepare_navigation_measurement_origin(raised)

    assert failed_origin.to_dict()["can_start_clock"] is False
    assert failed_origin.reason == "home_action_failed"
    assert failed_origin.error == "transport unavailable"
    assert raised_origin.reason == "home_exception"
    assert raised_origin.error == "RuntimeError: boom"
