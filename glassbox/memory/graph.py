"""glassbox/memory/graph.py — ScreenMemory: the live UI Transition Graph.

Holds a UTG and grows it from observations. No Phone / obs dependency — it is
fed Scenes (online via Phone.perceive, or offline via recording.py).
See docs/design/screen_memory.md §5/§6.
"""

from __future__ import annotations

import contextlib
import time
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING

from glassbox.cognition.text_match import norm_text
from glassbox.memory.element_key import element_key, merge_element, to_remembered
from glassbox.memory.schema import UTG, ActionRecord, RememberedElement, ScreenEdge, ScreenNode
from glassbox.memory.signature import (
    SIGNATURE_MATCH_THRESHOLD,
    compute_signature,
    dhash,
    similarity,
)

if TYPE_CHECKING:
    import numpy as np

    from glassbox.cognition.base import Box, Scene, ScreenSignature

Action = ActionRecord | tuple[str, dict]


class ScreenMemory:
    """A live UTG. `observe()` grows it; `recognize/locate/path` query it."""

    def __init__(
        self,
        utg: UTG,
        *,
        match_threshold: float = SIGNATURE_MATCH_THRESHOLD,
        autosave: Callable[[UTG], None] | None = None,
        autosave_every: int = 0,
    ):
        self.utg = utg
        self.match_threshold = match_threshold
        self._last_node_id: str | None = None
        # continue the scr_N counter past whatever was loaded from disk
        self._sig_counter = max(
            (int(n[4:]) for n in utg.nodes if n.startswith("scr_") and n[4:].isdigit()),
            default=0,
        )
        # CUQ-3.22: persist the growing UTG periodically so a mid-run crash/kill
        # does not lose the whole session's learned graph (it was previously
        # saved only on runtime.close()). The callback does the IO so this module
        # stays IO-free; default off for externally-owned memory.
        self._autosave = autosave
        self._autosave_every = max(0, int(autosave_every))
        self._observes_since_save = 0
        # CUQ-3.20: set by the last observe() when an action landed on a
        # different node than a learned high-success edge predicted — a strong
        # failure / node-identity-drift signal. None when the last transition
        # matched (or there was no prior edge to compare against).
        self.last_transition_mismatch: dict[str, object] | None = None

    # ─── write ───────────────────────────────────────────────────────
    def observe(
        self,
        scene: Scene,
        last_action: Action | None = None,
        frame_img: np.ndarray | None = None,
    ) -> ScreenNode:
        """Fold one perceived Scene into the graph. If an action preceded it,
        record the transition edge. Returns the resolved node."""
        phash = dhash(frame_img) if frame_img is not None else ""
        sig = compute_signature(scene, phash=phash)
        node = self._resolve_node(scene, sig)

        self._merge_scene_fields(node, scene, frame_img)
        node.visit_count += 1
        node.last_seen = time.time()

        self.last_transition_mismatch = None
        if self._last_node_id is not None and last_action is not None:
            action = self._coerce_action(last_action)
            if self._action_is_learnable(action):
                self.last_transition_mismatch = self._detect_transition_mismatch(
                    self._last_node_id, node.screen_id, action
                )
                self._bump_edge(self._last_node_id, node.screen_id, action)
        self._last_node_id = node.screen_id
        self._maybe_autosave()
        return node

    def _detect_transition_mismatch(
        self, from_id: str, to_id: str, action: ActionRecord
    ) -> dict[str, object] | None:
        """CUQ-3.20: did this action land somewhere other than a learned
        high-success edge predicted? Same (from_node, action) previously
        succeeding to a *different* node is a strong failure / node-drift
        signal. Returns the mismatch details, or None when it matched (or there
        is no successful prior edge for this action)."""
        identity = self._action_identity(action)
        for e in self.utg.edges:
            existing_identity = e.action_identity or self._legacy_edge_identity(e)
            if e.from_id != from_id or e.action_op != action.op or existing_identity != identity:
                continue
            if e.to_id != to_id and e.success_count > 0:
                return {
                    "from_id": from_id,
                    "action_identity": identity,
                    "predicted_to_id": e.to_id,
                    "observed_to_id": to_id,
                    "predicted_success_count": e.success_count,
                }
        return None

    def _maybe_autosave(self) -> None:
        """Best-effort periodic persistence (CUQ-3.22). Never let a save error
        break the observation path."""
        if self._autosave is None or self._autosave_every <= 0:
            return
        self._observes_since_save += 1
        if self._observes_since_save >= self._autosave_every:
            self._observes_since_save = 0
            with contextlib.suppress(Exception):
                self._autosave(self.utg)

    def merge_scene_metadata(
        self,
        scene: Scene,
        frame_img: np.ndarray | None = None,
    ) -> ScreenNode:
        """Refresh the current node with Layer 3/profile metadata.

        Unlike observe(), this does not add a visit or transition edge; it is
        used when describe() enriches the same frame that perceive() already
        folded into memory.
        """
        phash = dhash(frame_img) if frame_img is not None else ""
        sig = compute_signature(scene, phash=phash)
        node = self._existing_node_for_signature(scene, sig)
        if node is None:
            node = self._resolve_node(scene, sig)
        else:
            node.signature = sig
        self._merge_scene_fields(node, scene, frame_img)
        node.last_seen = time.time()
        self._last_node_id = node.screen_id
        return node

    # ─── read ────────────────────────────────────────────────────────
    def recognize(
        self, scene: Scene, frame_img: np.ndarray | None = None
    ) -> ScreenNode | None:
        """Which node this scene shows — WITHOUT mutating the graph. None if unseen."""
        sig = compute_signature(scene, phash=dhash(frame_img) if frame_img is not None else "")
        node, score = self._nearest_signature_node(sig, scene)
        return node if node is not None and score >= self.match_threshold else None

    def locate(self, screen_id: str, element_key: str) -> Box | None:
        """Last-known position of an element on a screen — a prior, not truth."""
        node = self.utg.nodes.get(screen_id)
        if node is None:
            return None
        el = node.element(element_key)
        return el.box if el is not None else None

    def expected_elements(
        self,
        screen_id: str,
        *,
        include_stale: bool = False,
    ) -> list[RememberedElement]:
        node = self.utg.nodes.get(screen_id)
        if node is None:
            return []
        if include_stale:
            return list(node.elements)
        return [element for element in node.elements if element.present]

    def path(self, from_id: str, to_id: str) -> list[ScreenEdge] | None:
        """Shortest action sequence from one screen to another (BFS over edges).
        [] if already there, None if unreachable / unknown node."""
        if from_id == to_id:
            return []
        if from_id not in self.utg.nodes or to_id not in self.utg.nodes:
            return None
        return self._path_to_targets(from_id, {to_id})

    def nodes_for_page(
        self,
        page_id: str,
        *,
        scene_type: str | None = None,
    ) -> list[ScreenNode]:
        """Known nodes for a semantic page id, optionally restricted by scene type."""
        return [
            node for node in self.utg.nodes.values()
            if node.page_id == page_id
            and (
                scene_type is None
                or scene_type in {
                    node.scene_type,
                    node.semantic_scene_type,
                    node.platform_scene_kind,
                }
            )
        ]

    def path_to_page(
        self,
        from_id: str,
        page_id: str,
        *,
        scene_type: str | None = None,
        allowed_actions: set[str] | None = None,
        min_success_rate: float = 0.0,
    ) -> list[ScreenEdge] | None:
        """Shortest safe-enough path from one node to any remembered page.

        This is the planning primitive used by higher-level recovery code:
        callers supply the safety gate (`allowed_actions`) and a minimum
        historical success rate. The memory layer only ranks learned edges; it
        does not decide whether an action is safe for a specific app state.
        """
        if from_id not in self.utg.nodes:
            return None
        targets = {
            node.screen_id
            for node in self.nodes_for_page(page_id, scene_type=scene_type)
        }
        if not targets:
            return None
        if from_id in targets:
            return []
        return self._path_to_targets(
            from_id,
            targets,
            allowed_actions=allowed_actions,
            min_success_rate=min_success_rate,
        )

    def _path_to_targets(
        self,
        from_id: str,
        targets: set[str],
        *,
        allowed_actions: set[str] | None = None,
        min_success_rate: float = 0.0,
    ) -> list[ScreenEdge] | None:
        prev: dict[str, ScreenEdge] = {}
        seen = {from_id}
        q: deque[str] = deque([from_id])
        while q:
            cur = q.popleft()
            for e in self.utg.outgoing(cur):
                if allowed_actions is not None and not self._edge_allowed(e, allowed_actions):
                    continue
                if e.count and e.success_rate < min_success_rate:
                    continue
                if e.to_id in seen:
                    continue
                seen.add(e.to_id)
                prev[e.to_id] = e
                if e.to_id in targets:
                    chain: list[ScreenEdge] = []
                    n = e.to_id
                    while n != from_id:
                        edge = prev[n]
                        chain.append(edge)
                        n = edge.from_id
                    return list(reversed(chain))
                q.append(e.to_id)
        return None

    # ─── internals ───────────────────────────────────────────────────
    def _resolve_node(self, scene: Scene, sig: ScreenSignature) -> ScreenNode:
        now = time.time()
        # VC/profile hits scope the search, but do not become the node id:
        # one ViewController can render multiple distinct UI states.
        node, score = self._nearest_signature_node(sig, scene)
        if node is not None and score >= self.match_threshold:
            node.signature = sig
            return node
        # New signature node.
        self._sig_counter += 1
        while f"scr_{self._sig_counter}" in self.utg.nodes:
            self._sig_counter += 1
        sid = f"scr_{self._sig_counter}"
        node = ScreenNode(
            screen_id=sid,
            vc_name=scene.current_vc,
            signature=sig,
            first_seen=now,
            last_seen=now,
        )
        self.utg.nodes[sid] = node
        return node

    def _nearest_signature_node(
        self, sig: ScreenSignature, scene: Scene | None = None
    ) -> tuple[ScreenNode | None, float]:
        best: ScreenNode | None = None
        best_score = 0.0
        for node in self.utg.nodes.values():
            if not self._node_scope_matches(node, scene):
                continue
            s = similarity(sig, node.signature)
            if s > best_score:
                best, best_score = node, s
        return best, best_score

    def _existing_node_for_signature(
        self, scene: Scene, sig: ScreenSignature
    ) -> ScreenNode | None:
        node, score = self._nearest_signature_node(sig, scene)
        if node is not None and score >= self.match_threshold:
            return node
        return None

    @staticmethod
    def _node_scope_matches(node: ScreenNode, scene: Scene | None) -> bool:
        if scene is None:
            return node.vc_name is None
        if scene.current_vc is not None and scene.current_vc != node.vc_name:
            return False
        if scene.page_id is not None and node.page_id is not None and scene.page_id != node.page_id:
            return False
        for key, value in scene.app_state.items():
            if ScreenMemory._is_unknown_app_state(value):
                continue
            if key in node.app_state and node.app_state[key] != value:
                return False
        return True

    @staticmethod
    def _is_unknown_app_state(value: str) -> bool:
        return str(value).strip().lower() == "unknown"

    def _merge_scene_fields(
        self,
        node: ScreenNode,
        scene: Scene,
        frame_img: np.ndarray | None,
    ) -> None:
        self._merge_elements(node, scene, self._frame_size(scene, frame_img))
        semantic_scene_type = scene.semantic_scene_type or (
            scene.scene_type if not scene.classification_source else None
        )
        platform_scene_kind = scene.platform_scene_kind or (
            scene.scene_type if scene.classification_source else None
        )
        if scene.scene_type:
            node.scene_type = scene.scene_type
        if semantic_scene_type:
            node.semantic_scene_type = semantic_scene_type
        if platform_scene_kind:
            node.platform_scene_kind = platform_scene_kind
        if scene.context:
            node.context = scene.context
        if scene.available_intents:
            node.available_intents = list(scene.available_intents)
        if scene.classification_source:
            node.page_id = scene.page_id
            node.safe_actions = list(scene.safe_actions)
        elif scene.page_id is not None:
            node.page_id = scene.page_id
        if scene.safe_actions:
            node.safe_actions = list(scene.safe_actions)
        if scene.classification_source:
            node.classification_source = scene.classification_source
        if scene.classification_confidence is not None:
            node.classification_confidence = scene.classification_confidence
        if scene.classification_evidence:
            node.classification_evidence = list(scene.classification_evidence)
        if scene.app_state:
            for key, value in scene.app_state.items():
                if self._is_unknown_app_state(value):
                    node.app_state.pop(key, None)
                else:
                    node.app_state[key] = value

    def _merge_elements(
        self, node: ScreenNode, scene: Scene, frame_size: tuple[int, int]
    ) -> None:
        by_key: dict[str, RememberedElement] = {e.key: e for e in node.elements}
        clear_missing_intent = scene.vlm_status == "ok"
        clear_missing_whitebox = bool(getattr(scene, "whitebox_evaluated", False))
        authoritative = clear_missing_intent or clear_missing_whitebox
        current_visit = node.visit_count + 1
        seen_keys: set[str] = set()
        for el in scene.elements:
            if el.type == "status_bar":
                continue
            k = element_key(el, frame_size)
            seen_keys.add(k)
            fresh = to_remembered(el, k).model_copy(
                update={
                    "present": True,
                    "missing_count": 0,
                    "last_seen_visit": current_visit,
                },
            )
            remembered = (
                merge_element(
                    by_key[k],
                    fresh,
                    clear_missing_intent=clear_missing_intent,
                    clear_missing_whitebox=clear_missing_whitebox,
                )
                if k in by_key else fresh
            )
            by_key[k] = remembered.model_copy(
                update={
                    "present": True,
                    "missing_count": 0,
                    "last_seen_visit": current_visit,
                },
            )
        if authoritative:
            for key, remembered in list(by_key.items()):
                if key in seen_keys:
                    continue
                updates = {
                    "present": False,
                    "missing_count": remembered.missing_count + 1,
                }
                if clear_missing_intent:
                    updates["intent_label"] = None
                if clear_missing_whitebox:
                    updates["whitebox_hint"] = None
                by_key[key] = remembered.model_copy(update=updates)
        node.elements = list(by_key.values())

    def _bump_edge(self, from_id: str, to_id: str, action: ActionRecord) -> None:
        identity = self._action_identity(action)
        edge_element_key = self._edge_element_key(action)
        edge_action = self._edge_action(action, edge_element_key)
        policy_action = self._policy_action(edge_action)
        action_kwargs = action.to_kwargs()
        for e in self.utg.edges:
            existing_identity = e.action_identity or self._legacy_edge_identity(e)
            if (e.from_id, e.to_id, e.action_op, existing_identity) == (
                from_id, to_id, action.op, identity,
            ):
                e.action_kwargs = action_kwargs
                e.action_identity = identity
                e.action = edge_action
                e.element_key = edge_element_key
                e.policy_action = policy_action
                self._apply_edge_outcome(e, action)
                return
        edge = ScreenEdge(
            from_id=from_id,
            to_id=to_id,
            action_op=action.op,
            element_key=edge_element_key,
            action_kwargs=action_kwargs,
            action_identity=identity,
            action=edge_action,
            policy_action=policy_action,
        )
        self._apply_edge_outcome(edge, action)
        self.utg.edges.append(edge)

    @classmethod
    def _apply_edge_outcome(cls, edge: ScreenEdge, action: ActionRecord) -> None:
        if edge.count and edge.success_count == 0 and edge.no_progress_count == 0:
            if edge.from_id == edge.to_id:
                edge.no_progress_count = edge.count
            else:
                edge.success_count = edge.count
        outcome = cls._explicit_action_outcome(action)
        if outcome is None:
            outcome = "no_progress" if edge.from_id == edge.to_id else "progress"
        edge.count += 1
        if outcome in {"no_progress", "stuck", "failed", "failure"}:
            edge.no_progress_count += 1
        elif outcome == "overshoot":
            edge.overshoot_count += 1
        else:
            edge.success_count += 1
        edge.last_outcome = outcome
        edge.success_rate = edge.success_count / edge.count if edge.count else 0.0

    @staticmethod
    def _explicit_action_outcome(action: ActionRecord) -> str | None:
        value = action.params.get("action_outcome", action.params.get("outcome"))
        if not isinstance(value, str):
            return None
        outcome = value.strip().lower()
        if outcome in {"progress", "overshoot", "success", "succeeded"}:
            return "progress" if outcome in {"success", "succeeded"} else outcome
        if outcome in {"no_progress", "stuck", "failed", "failure"}:
            return "no_progress" if outcome in {"failed", "failure"} else outcome
        return None

    @staticmethod
    def _coerce_action(action: Action) -> ActionRecord:
        if isinstance(action, ActionRecord):
            return action
        op, kwargs = action
        return ActionRecord.from_op(op, kwargs)

    @staticmethod
    def _action_is_learnable(action: ActionRecord) -> bool:
        ok = action.params.get("action_ok")
        synthetic = action.params.get("action_synthetic")
        if ok is not None and ok is not True:
            return False
        return synthetic is None or synthetic is False

    @staticmethod
    def _edge_allowed(edge: ScreenEdge, allowed_actions: set[str]) -> bool:
        candidates = {edge.action_op}
        if edge.policy_action:
            candidates.add(edge.policy_action)
        action = edge.action
        if action is not None:
            maybe_policy = action.params.get("policy_action")
            if isinstance(maybe_policy, str) and maybe_policy:
                candidates.add(maybe_policy)
        return bool(candidates & allowed_actions)

    def _legacy_edge_identity(self, edge: ScreenEdge) -> str:
        action = edge.action or ActionRecord.from_op(edge.action_op, edge.action_kwargs)
        edge_element_key = edge.element_key or self._edge_element_key(action)
        action = self._edge_action(action, edge_element_key)
        return self._action_identity(action)

    def _action_identity(self, action: ActionRecord) -> str:
        edge_element_key = self._edge_element_key(action)
        if edge_element_key:
            return f"element:{edge_element_key}"
        if action.op in {"key"}:
            return (
                "key:"
                f"{self._param(action, 'modifier', default=0)}:"
                f"{self._param(action, 'keycode', default=0)}"
            )
        if action.op in {"scroll_wheel", "wheel"}:
            ticks = self._int_param(action, "ticks", default=0)
            horizontal = self._int_param(action, "horizontal", default=0)
            return f"wheel:h{self._sign(horizontal)}:v{self._sign(ticks)}:b{self._ticks_bucket(ticks)}"
        if action.op in {"swipe", "drag"}:
            return self._gesture_identity(action)
        if action.x is not None and action.y is not None:
            return (
                f"coord:{action.coordinate_space}:"
                f"{action.x // 80}:{action.y // 80}"
            )
        if action.via:
            return f"via:{action.via}"
        return "op"

    @staticmethod
    def _edge_element_key(action: ActionRecord) -> str | None:
        if action.element_key:
            return action.element_key
        if action.target:
            return f"text:{norm_text(action.target)}"
        return None

    @staticmethod
    def _edge_action(action: ActionRecord, edge_element_key: str | None) -> ActionRecord:
        if edge_element_key and not action.element_key:
            return action.model_copy(update={"element_key": edge_element_key})
        return action

    @classmethod
    def _gesture_identity(cls, action: ActionRecord) -> str:
        x1 = cls._int_param(action, "x1")
        y1 = cls._int_param(action, "y1")
        x2 = cls._int_param(action, "x2")
        y2 = cls._int_param(action, "y2")
        dx = x2 - x1
        dy = y2 - y1
        if abs(dx) >= abs(dy):
            direction = "right" if dx > 0 else "left" if dx < 0 else "still"
        else:
            direction = "down" if dy > 0 else "up"
        duration = (
            cls._int_param(action, "end_hold_ms", default=0)
            + cls._int_param(action, "down_hold_ms", default=0)
            + cls._int_param(action, "up_hold_ms", default=0)
        )
        steps = cls._int_param(action, "steps", default=0)
        return (
            f"gesture:{action.coordinate_space}:{direction}:"
            f"s{x1 // 120},{y1 // 120}:e{x2 // 120},{y2 // 120}:"
            f"d{duration // 100}:n{steps // 10}"
        )

    @classmethod
    def _policy_action(cls, action: ActionRecord) -> str:
        explicit = action.params.get("policy_action")
        if isinstance(explicit, str) and explicit:
            return explicit
        if action.via == "back_gesture":
            return "back"
        if action.via in {"swipe_up", "swipe_down"}:
            return "scroll"
        if action.via in {"swipe_left", "swipe_right"}:
            return "page"
        if action.op in {"scroll_wheel", "wheel", "swipe"}:
            return "scroll"
        if action.op == "home":
            return "home"
        if action.op == "recents":
            return "recents"
        if action.op == "control_center":
            return "control_center"
        if action.op == "notification_center":
            return "notification_center"
        if action.op == "key":
            modifier = cls._int_param(action, "modifier", default=0)
            keycode = cls._int_param(action, "keycode", default=0)
            if modifier == 0x08 and keycode == 0x2F:
                return "back"
            return "key"
        if action.via:
            return action.via
        return action.op

    @staticmethod
    def _param(action: ActionRecord, name: str, *, default=None):
        return action.params.get(name, default)

    @classmethod
    def _int_param(cls, action: ActionRecord, name: str, *, default: int = 0) -> int:
        try:
            return int(cls._param(action, name, default=default))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _sign(value: int) -> int:
        if value > 0:
            return 1
        if value < 0:
            return -1
        return 0

    @staticmethod
    def _ticks_bucket(ticks: int) -> int:
        return min(9, abs(int(ticks)) // 30)

    @staticmethod
    def _frame_size(scene: Scene, frame_img) -> tuple[int, int]:
        if frame_img is not None and getattr(frame_img, "ndim", 0) >= 2:
            return frame_img.shape[1], frame_img.shape[0]
        if scene.viewport_size is not None:
            return scene.viewport_size
        w = max((e.box.x2 for e in scene.elements), default=1) or 1
        h = max((e.box.y2 for e in scene.elements), default=1) or 1
        return w, h
