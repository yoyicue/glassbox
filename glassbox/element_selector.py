"""Element lookup, VLM regrounding, and expectation helpers."""

from __future__ import annotations

import time
from typing import Any

from glassbox.cognition import Scene, UIElement, find_by_intent, find_by_whitebox_hint, find_text
from glassbox.cognition.vlm_kimi import enrich_scene


class ElementSelector:
    """Resolve UI elements from OCR/VLM/memory signals for Phone."""

    def __init__(self, phone: Any) -> None:
        self._phone = phone

    def describe(self, *, scene_hint: str | None = None, set_of_mark: bool | None = None) -> Scene:
        host = self._phone
        if host.last_scene is None:
            host.perceive()
        if host.kimi is None or host.last_scene is None:
            return host.last_scene

        if host.last_frame is None:
            return host.last_scene

        if hasattr(host.kimi, "last_hit"):
            host.kimi.last_hit = False
        t0 = time.monotonic()
        use_som = host.vlm_set_of_mark_enabled if set_of_mark is None else bool(set_of_mark)
        enrich_scene(
            host.last_scene,
            host.last_frame,
            host.kimi,
            scene_hint=scene_hint,
            set_of_mark=use_som,
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        vlm_ok = host.last_scene.vlm_status == "ok"
        if vlm_ok:
            frame_img = host.last_frame.img if host.last_frame is not None else None
            host.apply_profile(host.last_scene, frame_img)
            host.apply_scene_classifiers(host.last_scene, frame_img)
            host.cache_scene(host.last_scene)
            if host.memory is not None:
                host.memory.merge_scene_metadata(host.last_scene, frame_img)

        if host.recorder is not None:
            host.recorder.kimi_call(
                model=host.last_scene.vlm_model or getattr(host.kimi, "model", "?"),
                hit=bool(getattr(host.kimi, "last_hit", False)),
                elapsed_ms=elapsed_ms,
                usage=dict(host.last_scene.vlm_usage),
                scene_hint=scene_hint,
                status=host.last_scene.vlm_status or "unknown",
                error=host.last_scene.vlm_error,
                parse_ok=vlm_ok,
            )
            host.recorder.scene(host.last_scene, purpose="metadata")
        return host.last_scene

    def find_text(self, target: str, *, fuzzy_ratio: float = 0.8) -> UIElement | None:
        element, _source = self._find_text_or_intent(target, fuzzy_ratio=fuzzy_ratio)
        return element

    def _find_text_or_intent(
        self,
        target: str,
        *,
        fuzzy_ratio: float = 0.8,
    ) -> tuple[UIElement | None, str | None]:
        scene = self._phone.perceive()
        elements = self.rows_before_nav_title(scene.elements)
        hit = find_text(
            elements,
            target,
            fuzzy_ratio=fuzzy_ratio,
            ambiguity_guard=self._phone.strict_target_matching_enabled,
        )
        if hit is not None:
            return hit, "ocr"
        hit = find_by_intent(
            elements,
            target,
            fuzzy_ratio=fuzzy_ratio,
            ambiguity_guard=self._phone.strict_target_matching_enabled,
        )
        if hit is not None:
            return hit, hit.intent_source or "intent"
        return None, None

    def vlm_reground_selection(self, target: str, *, fuzzy_ratio: float) -> UIElement | None:
        host = self._phone
        if not host.vlm_reground_selection_enabled or host.kimi is None:
            return None
        from glassbox.cognition.vlm_gate import VLMEscalationGate, VLMGateInput

        gate = VLMEscalationGate(enabled=True, max_calls_per_action=1, max_calls_per_attempt=1)
        gate_input = VLMGateInput(ocr_confidence=None, target_found=False)
        described = gate.escalate(gate_input, lambda: self.describe(scene_hint=f"find:{target}"))
        if described is None:
            return None
        elements = self.rows_before_nav_title(described.elements)
        hit = find_text(
            elements, target, fuzzy_ratio=fuzzy_ratio,
            ambiguity_guard=host.strict_target_matching_enabled,
        )
        if hit is None:
            hit = find_by_intent(
                elements, target, fuzzy_ratio=fuzzy_ratio,
                ambiguity_guard=host.strict_target_matching_enabled,
            )
        return hit

    def memory_locate_selection(self, target: str, *, fuzzy_ratio: float) -> UIElement | None:
        host = self._phone
        if not host.memory_locate_priors_enabled:
            return None
        memory = host.memory
        if memory is None or host.last_scene is None:
            return None
        recognize = getattr(memory, "recognize", None)
        expected_elements = getattr(memory, "expected_elements", None)
        if not callable(recognize) or not callable(expected_elements):
            return None
        frame_img = host.last_frame.img if host.last_frame is not None else None
        try:
            node = recognize(host.last_scene, frame_img)
            if node is None:
                return None
            remembered = expected_elements(node.screen_id)
        except Exception:
            return None
        candidates = [
            UIElement(type=row.type, box=row.box, text=row.text, confidence=0.0, element_id=i)
            for i, row in enumerate(remembered)
            if getattr(row, "text", None) and not getattr(row, "volatile", False)
        ]
        if not candidates:
            return None
        return find_text(
            candidates, target, fuzzy_ratio=fuzzy_ratio,
            ambiguity_guard=host.strict_target_matching_enabled,
        )

    def rows_before_nav_title(self, elements: list[UIElement]) -> list[UIElement]:
        try:
            width, height = self._phone.viewport_size()
        except Exception:
            return elements

        def is_nav_title(element: UIElement) -> bool:
            cx, cy = element.box.center
            return cy < height * 0.13 and abs(cx - width / 2) < width * 0.18

        rows = [element for element in elements if not is_nav_title(element)]
        titles = [element for element in elements if is_nav_title(element)]
        return rows + titles if titles else elements

    def expect_text(
        self,
        target: str,
        *,
        timeout: float = 5.0,
        fuzzy_ratio: float = 0.8,
        poll_interval: float = 0.5,
    ) -> UIElement:
        host = self._phone
        deadline = time.monotonic() + timeout
        last_seen_texts: list[str] = []
        while time.monotonic() < deadline:
            element, selection_source = self._find_text_or_intent(target, fuzzy_ratio=fuzzy_ratio)
            if element is not None:
                host.set_last_selection_source(selection_source or "ocr")
                if host.recorder is not None:
                    host.recorder.verdict(f"expect_text({target!r})", passed=True)
                return element
            if host.whitebox_hint_selection_enabled and host.last_scene is not None:
                whitebox = find_by_whitebox_hint(host.last_scene.elements, target)
                if whitebox is not None:
                    host.set_last_selection_source("whitebox")
                    if host.recorder is not None:
                        host.recorder.verdict(
                            f"expect_text({target!r})", passed=True, message="whitebox_hint"
                        )
                    return whitebox
            if host.last_scene:
                last_seen_texts = [element.text for element in host.last_scene.elements if element.text]
            time.sleep(poll_interval)
        from_memory = self.memory_locate_selection(target, fuzzy_ratio=fuzzy_ratio)
        if from_memory is not None:
            host.set_last_selection_source("memory")
            if host.recorder is not None:
                host.recorder.verdict(f"expect_text({target!r})", passed=True, message="memory_prior")
            return from_memory
        grounded = self.vlm_reground_selection(target, fuzzy_ratio=fuzzy_ratio)
        if grounded is not None:
            host.set_last_selection_source("vlm")
            if host.recorder is not None:
                host.recorder.verdict(f"expect_text({target!r})", passed=True, message="vlm_grounded")
            return grounded
        if host.recorder is not None:
            host.recorder.verdict(
                f"expect_text({target!r})",
                passed=False,
                message=f"timeout {timeout}s; last seen={last_seen_texts[:10]}",
            )
        raise AssertionError(
            f"expect_text({target!r}) timed out ({timeout}s). "
            f"Last seen text: {last_seen_texts[:10]}..."
        )

    def expect_no_text(self, target: str, *, fuzzy_ratio: float = 0.9) -> None:
        element = self.find_text(target, fuzzy_ratio=fuzzy_ratio)
        if self._phone.recorder is not None:
            self._phone.recorder.verdict(
                f"expect_no_text({target!r})",
                passed=element is None,
                message=f"found={element.text!r}" if element is not None else "",
            )
        if element is not None:
            raise AssertionError(f"expect_no_text({target!r}) but found: {element.text!r}")


__all__ = ["ElementSelector"]
