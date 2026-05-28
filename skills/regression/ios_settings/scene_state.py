"""Pure scene classification helpers for the iOS Settings crawler.

This module must stay side-effect free: no taps, no sleeps, no device mutation.
It centralizes policy-backed scene predicates so navigation, recovery, and
records can share the same interpretation without importing ``core.py``.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from contextlib import suppress
from typing import Any

from glassbox.cognition import UIElement
from glassbox.ios.progress import same_visible_page, stable_visible_texts
from glassbox.ios.scene import has_strong_ios_home_evidence, settings_detail_semantic_guess
from skills.regression.ios_settings import graph_state as settings_graph_state
from skills.regression.ios_settings.policy import DEFAULT_SETTINGS_POLICY

_ROW_TAP_PRIOR_TTL_S = 12.0
_SCENE_VLM_CALL_BUDGET = 3
_SCENE_VLM_CACHE: dict[str, str | None] = {}
_scene_vlm_calls = 0
_CONTEXTUAL_DETAIL_BASE_KINDS = frozenset({"unknown", "springboard", "springboard_or_app_library"})
_HARD_COUNTER_KINDS = frozenset({
    "settings_root",
    "settings_search_home",
    "settings_search_results",
    "settings_blocked_safety",
    "system_search",
    "app_library",
    "harness_console",
})


def phone_viewport_size(phone) -> tuple[int, int] | None:
    try:
        w, h = phone._viewport_size()
        return int(w), int(h)
    except Exception:
        return None


def scene_type(scene) -> str:
    return DEFAULT_SETTINGS_POLICY.scene_type(scene)


def classify_ios_scene(scene, phone=None):
    viewport_size = phone_viewport_size(phone) if phone is not None else None
    return DEFAULT_SETTINGS_POLICY.classify_scene(scene, viewport_size=viewport_size)


def scene_kind(scene, phone=None) -> str:
    viewport_size = phone_viewport_size(phone) if phone is not None else None
    classified = DEFAULT_SETTINGS_POLICY.classify_scene(scene, viewport_size=viewport_size)
    kind = classified.kind if classified is not None else DEFAULT_SETTINGS_POLICY.scene_type(
        scene,
        viewport_size=viewport_size,
    )
    graph_kind = settings_graph_state.graph_scene_kind(
        scene,
        phone,
        base_kind=kind,
        viewport_size=viewport_size,
    )
    if graph_kind is not None:
        _record_contextual_scene_kind(
            phone,
            scene,
            source="utg",
            base_kind=kind,
            label=graph_kind.label,
            override=True,
            evidence=graph_kind.evidence,
            confidence=graph_kind.confidence,
        )
        return graph_kind.kind
    if kind in _HARD_COUNTER_KINDS:
        _clear_recent_row_tap_prior(phone)
        return kind
    if _contextual_settings_detail_override(scene, phone, base_kind=kind, viewport_size=viewport_size):
        return "settings_detail"
    return kind


def reset_scene_context_state() -> None:
    global _scene_vlm_calls
    _scene_vlm_calls = 0
    _SCENE_VLM_CACHE.clear()


def record_settings_row_tap(phone, label: str) -> None:
    if phone is None:
        return
    with suppress(Exception):
        phone._ios_settings_last_row_tap = {
            "via": "settings.tap_row",
            "label": (label or "").strip(),
            "created_at": time.monotonic(),
        }


def return_state_signature(scene, phone=None) -> tuple[str, tuple[str, ...]]:
    return scene_kind(scene, phone=phone), tuple(sorted(stable_visible_texts(texts(scene)))[:12])


def is_settings_root(phone) -> bool:
    scene = phone.perceive()
    return scene_is_settings_root(scene)


def scene_is_settings_root(scene) -> bool:
    return DEFAULT_SETTINGS_POLICY.scene_is_settings_root(scene)


def has_visible_back_affordance(scene) -> bool:
    return DEFAULT_SETTINGS_POLICY.has_visible_back_affordance(scene)


def scene_looks_like_settings_detail(scene) -> bool:
    return DEFAULT_SETTINGS_POLICY.scene_looks_like_settings_detail(scene)


def texts(scene) -> list[str]:
    out: list[str] = []
    for element in scene.elements:
        text = (element.text or "").strip()
        if text:
            out.append(text)
    return out


def same_page_after_tap(before_scene, after_scene, *, expected_title: str | None = None) -> bool:
    before_title = page_title(before_scene)
    after_title = page_title(after_scene)
    if (
        expected_title
        and before_title != "?"
        and after_title != "?"
        and before_title != after_title
        and title_matches_navigation_label(after_title, expected_title)
    ):
        return False
    return same_visible_page(texts(before_scene), texts(after_scene))


def title_matches_navigation_label(title: str, label: str) -> bool:
    return DEFAULT_SETTINGS_POLICY.title_matches_navigation_label(title, label)


def page_title(scene) -> str:
    return DEFAULT_SETTINGS_POLICY.page_title(scene)


def safe_navigation_candidates(
    scene,
    *,
    allow_sensitive_root_labels: bool = False,
    allow_known_without_affordance: bool = True,
) -> list[UIElement]:
    return DEFAULT_SETTINGS_POLICY.safe_navigation_candidates(
        scene,
        allow_sensitive_root_labels=allow_sensitive_root_labels,
        allow_known_without_affordance=allow_known_without_affordance,
    )


def potential_navigation_row_text(element: UIElement) -> str | None:
    return DEFAULT_SETTINGS_POLICY.potential_navigation_row_text(element)


def is_settings_section_header(scene, element: UIElement) -> bool:
    return DEFAULT_SETTINGS_POLICY.is_settings_section_header(scene, element)


def is_safe_known_navigation_label(text: str) -> bool:
    return DEFAULT_SETTINGS_POLICY.is_safe_known_navigation_label(text)


def has_navigation_affordance(scene, element: UIElement) -> bool:
    return DEFAULT_SETTINGS_POLICY.has_navigation_affordance(scene, element)


def is_unsafe_navigation_text(text: str, *, allow_sensitive_root_labels: bool = False) -> bool:
    return DEFAULT_SETTINGS_POLICY.is_unsafe_navigation_text(
        text,
        allow_sensitive_root_labels=allow_sensitive_root_labels,
    )


def is_status_bar_clock_text(text: str) -> bool:
    return DEFAULT_SETTINGS_POLICY.is_status_bar_clock_text(text)


def matches_label(text: str, label: str) -> bool:
    return DEFAULT_SETTINGS_POLICY.matches_label(text, label)


def is_exact_safe_navigation_label(text: str) -> bool:
    return DEFAULT_SETTINGS_POLICY.is_exact_safe_navigation_label(text)


def is_root_only_unsafe_override(text: str) -> bool:
    return DEFAULT_SETTINGS_POLICY.is_root_only_unsafe_override(text)


def canonical_expected_root_label(text: str) -> str | None:
    return DEFAULT_SETTINGS_POLICY.canonical_expected_root_label(text)


def blocked_child_navigation_reason(scene) -> str | None:
    return DEFAULT_SETTINGS_POLICY.blocked_child_navigation_reason(scene)


def blocks_child_navigation(scene) -> bool:
    return DEFAULT_SETTINGS_POLICY.blocks_child_navigation(scene)


def is_safe_top_left_back_fallback_scene(scene, phone=None) -> bool:
    viewport_size = phone_viewport_size(phone) if phone is not None else None
    return DEFAULT_SETTINGS_POLICY.is_safe_top_left_back_fallback_scene(scene, viewport_size=viewport_size)


def is_settings_search_scene(scene) -> bool:
    return DEFAULT_SETTINGS_POLICY.is_settings_search_scene(scene)


def settings_search_has_bottom_chrome(scene) -> bool:
    return DEFAULT_SETTINGS_POLICY.settings_search_has_bottom_chrome(scene)


def looks_like_settings_search_results(scene) -> bool:
    return DEFAULT_SETTINGS_POLICY.looks_like_settings_search_results(scene)


def is_settings_search_affordance_text(text: str) -> bool:
    return DEFAULT_SETTINGS_POLICY.is_settings_search_affordance_text(text)


def settings_search_has_query_text(scene) -> bool:
    return DEFAULT_SETTINGS_POLICY.settings_search_has_query_text(scene)


def find_search_result(scene, label: str) -> UIElement | None:
    return DEFAULT_SETTINGS_POLICY.find_search_result(scene, label)


def find_search_query_suggestion(scene, label: str) -> UIElement | None:
    return DEFAULT_SETTINGS_POLICY.find_search_query_suggestion(scene, label)


def find_search_clear_button(scene) -> UIElement | None:
    return DEFAULT_SETTINGS_POLICY.find_search_clear_button(scene)


def find_search_field(scene) -> UIElement | None:
    return DEFAULT_SETTINGS_POLICY.find_search_field(scene)


def is_visible_back_element(element: UIElement) -> bool:
    return DEFAULT_SETTINGS_POLICY.is_visible_back_element(element)


def _contextual_settings_detail_override(
    scene,
    phone,
    *,
    base_kind: str,
    viewport_size: tuple[int, int] | None,
) -> bool:
    if phone is None or base_kind not in _CONTEXTUAL_DETAIL_BASE_KINDS:
        return False
    prior = _recent_row_tap_prior(phone)
    if prior is None:
        return False

    if has_strong_ios_home_evidence(scene, viewport_size=viewport_size):
        _record_contextual_scene_kind(
            phone,
            scene,
            source="transition",
            base_kind=base_kind,
            label=prior.get("label"),
            override=False,
            evidence=("strong_home_evidence",),
        )
        return False

    semantic = settings_detail_semantic_guess(scene, viewport_size=viewport_size)
    vlm_kind = _vlm_verify_settings_scene_kind(
        phone,
        scene,
        base_kind=base_kind,
        transition_label=str(prior.get("label") or ""),
    )
    if vlm_kind == "settings_detail":
        _record_contextual_scene_kind(
            phone,
            scene,
            source="vlm",
            base_kind=base_kind,
            label=prior.get("label"),
            override=True,
            evidence=("settings.tap_row_prior", "vlm:settings_detail"),
        )
        return True
    if vlm_kind in {
        "springboard",
        "app_library",
        "settings_root",
        "settings_search",
        "system_search",
        "settings_blocked_safety",
    }:
        _record_contextual_scene_kind(
            phone,
            scene,
            source="vlm",
            base_kind=base_kind,
            label=prior.get("label"),
            override=False,
            evidence=(f"vlm:{vlm_kind}",),
        )
        return False

    evidence = ["settings.tap_row_prior"]
    if semantic is not None:
        evidence.extend(semantic.evidence)
    _record_contextual_scene_kind(
        phone,
        scene,
        source="transition" if semantic is None else "semantic",
        base_kind=base_kind,
        label=prior.get("label"),
        override=True,
        evidence=tuple(evidence),
    )
    return True


def _recent_row_tap_prior(phone) -> dict[str, Any] | None:
    prior = getattr(phone, "_ios_settings_last_row_tap", None)
    if not isinstance(prior, dict) or prior.get("via") != "settings.tap_row":
        return None
    created_at = prior.get("created_at")
    try:
        age = time.monotonic() - float(created_at)
    except (TypeError, ValueError):
        return None
    if age < 0 or age > _ROW_TAP_PRIOR_TTL_S:
        return None
    return prior


def _clear_recent_row_tap_prior(phone) -> None:
    if phone is None:
        return
    with suppress(Exception):
        if hasattr(phone, "_ios_settings_last_row_tap"):
            delattr(phone, "_ios_settings_last_row_tap")


def _vlm_verify_settings_scene_kind(
    phone,
    scene,
    *,
    base_kind: str,
    transition_label: str,
) -> str | None:
    global _scene_vlm_calls
    kimi = getattr(phone, "kimi", None) if phone is not None else None
    frame = getattr(phone, "_last_frame", None) if phone is not None else None
    frame_img = getattr(frame, "img", None)
    if kimi is None or frame_img is None or not hasattr(kimi, "chat"):
        return None

    cache_key = _scene_vlm_cache_key(
        scene,
        transition_label=transition_label,
        base_kind=base_kind,
        frame_img=frame_img,
    )
    if cache_key in _SCENE_VLM_CACHE:
        return _SCENE_VLM_CACHE[cache_key]
    if _scene_vlm_calls >= _SCENE_VLM_CALL_BUDGET:
        _SCENE_VLM_CACHE[cache_key] = None
        return None

    image = _encode_frame_png(frame_img)
    if image is None:
        _SCENE_VLM_CACHE[cache_key] = None
        return None

    _scene_vlm_calls += 1
    try:
        resp = kimi.chat(
            system=(
                "You verify iOS screen state for a read-only Settings crawler. "
                "Return JSON only: {\"scene_kind\":\"...\",\"evidence\":[\"...\"]}. "
                "Allowed scene_kind values are settings_detail, settings_root, "
                "settings_search, settings_blocked_safety, system_search, "
                "springboard, app_library, unknown. A screen reached immediately "
                "after tapping a Settings row is normally settings_detail unless "
                "there is strong Home/Search/blocked evidence."
            ),
            user_text=_scene_vlm_prompt(scene, base_kind=base_kind, transition_label=transition_label),
            image=image,
            json_object=True,
        )
    except Exception:
        _SCENE_VLM_CACHE[cache_key] = None
        return None

    kind = _normalize_vlm_scene_kind(resp)
    _SCENE_VLM_CACHE[cache_key] = kind
    return kind


def _scene_vlm_cache_key(scene, *, transition_label: str, base_kind: str, frame_img=None) -> str:
    h = hashlib.sha1()
    h.update(base_kind.encode("utf-8", "ignore"))
    h.update(b"\0")
    h.update(transition_label.encode("utf-8", "ignore"))
    shape = getattr(frame_img, "shape", None)
    if shape is not None:
        h.update(b"\0frame:")
        h.update(str(tuple(shape)).encode())
    tobytes = getattr(frame_img, "tobytes", None)
    if callable(tobytes):
        with suppress(Exception):
            h.update(hashlib.sha1(tobytes()).digest())
    for element in scene.elements[:80]:
        text = (getattr(element, "text", None) or "").strip()
        box = getattr(element, "box", None)
        h.update(b"\0")
        h.update(text.encode("utf-8", "ignore"))
        if box is not None:
            h.update(f":{box.x},{box.y},{box.w},{box.h}".encode())
    return h.hexdigest()


def _scene_vlm_prompt(scene, *, base_kind: str, transition_label: str) -> str:
    lines = [
        f"Base OCR classifier kind: {base_kind}",
        f"Previous verified action: settings.tap_row label={transition_label!r}",
        "Visible OCR elements:",
    ]
    for element in scene.elements[:60]:
        text = (getattr(element, "text", None) or "").strip()
        if not text:
            continue
        box = getattr(element, "box", None)
        if box is None:
            lines.append(f"- {text}")
        else:
            lines.append(f"- {text} @ [{box.x},{box.y},{box.w},{box.h}]")
    return "\n".join(lines)


def _encode_frame_png(frame_img) -> bytes | None:
    try:
        import cv2

        ok, png = cv2.imencode(".png", frame_img)
    except Exception:
        return None
    if not ok:
        return None
    return png.tobytes()


def _normalize_vlm_scene_kind(resp: Any) -> str | None:
    payloads: list[dict[str, Any]] = []
    parsed = getattr(resp, "parsed", None)
    if isinstance(parsed, dict):
        payloads.append(parsed)
    raw_payload = _parse_json_object(getattr(resp, "raw_content", ""))
    if raw_payload is not None:
        payloads.append(raw_payload)
    for payload in payloads:
        raw = payload.get("scene_kind") or payload.get("kind") or payload.get("scene")
        if not isinstance(raw, str):
            continue
        normalized = re.sub(r"[^a-z_]+", "_", raw.strip().casefold()).strip("_")
        if normalized in {"settings_detail", "detail", "settings_details"}:
            return "settings_detail"
        if normalized in {"settings_root", "root"}:
            return "settings_root"
        if normalized in {"settings_search", "settings_search_home", "settings_search_results", "search"}:
            return "settings_search"
        if normalized in {"settings_blocked_safety", "blocked", "passcode"}:
            return "settings_blocked_safety"
        if normalized in {"system_search", "spotlight"}:
            return "system_search"
        if normalized in {"springboard", "home", "home_screen"}:
            return "springboard"
        if normalized in {"app_library", "library"}:
            return "app_library"
        if normalized == "unknown":
            return "unknown"
    return None


def _parse_json_object(raw: Any) -> dict[str, Any] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if match is None:
            return None
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def _record_contextual_scene_kind(
    phone,
    scene,
    *,
    source: str,
    base_kind: str,
    label: Any,
    override: bool,
    evidence: tuple[str, ...],
    confidence: float | None = None,
) -> None:
    record = {
        "source": source,
        "base_kind": base_kind,
        "kind": "settings_detail" if override else base_kind,
        "label": label,
        "override": override,
        "evidence": list(evidence),
    }
    with suppress(Exception):
        records = getattr(phone, "_ios_settings_scene_classifications", None)
        if not isinstance(records, list):
            records = []
            phone._ios_settings_scene_classifications = records
        records.append(record)
    if not override:
        return
    with suppress(Exception):
        scene.platform_scene_kind = "settings_detail"
        if getattr(scene, "scene_type", None) in {None, "unknown", "springboard", "springboard_or_app_library"}:
            scene.scene_type = "settings_detail"
        scene.classification_source = source
        scene.classification_confidence = confidence if confidence is not None else (
            0.74 if source == "transition" else 0.82
        )
        scene.classification_evidence = list(evidence)
