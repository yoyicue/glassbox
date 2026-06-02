from __future__ import annotations

import numpy as np
import pytest

from glassbox.action import prepare_navigation_measurement_origin
from glassbox.cognition import Box, Scene, SceneClassification, SceneClassificationPrior, UIElement
from glassbox.effector import ActionResult
from glassbox.memory import UTG, ActionRecord, ScreenMemory
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


class _HomePhone:
    def __init__(self, result: ActionResult | BaseException):
        self.result = result
        self.calls = 0

    def home(self):
        self.calls += 1
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


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
