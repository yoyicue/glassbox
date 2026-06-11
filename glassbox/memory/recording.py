"""glassbox/memory/recording.py — build a UTG offline from an obs recording.

Replays an `events.jsonl` (glassbox/obs/recorder.py) into a UTG. This turns
already-captured walkthrough runs into memory — no live device needed.
Kept separate from graph.py so the core graph carries no glassbox.obs import.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from glassbox.cognition.base import Box, Scene, UIElement
from glassbox.memory.graph import ScreenMemory
from glassbox.memory.schema import UTG, ActionRecord
from glassbox.obs.recorder import iter_events


def _iter_events(run_dir: str | Path):
    # Shared hardened reader: tolerates a torn trailing line (crash artifact),
    # still raises on mid-file corruption.
    yield from iter_events(run_dir)


def _scene_from_event(ev: dict) -> Scene:
    """Rebuild a minimal Scene from a recorder 'scene' event payload."""
    if isinstance(ev.get("scene"), dict):
        scene = Scene.model_validate(ev["scene"])
        viewport_size = _coerce_viewport_size(ev.get("viewport_size"))
        if scene.viewport_size is None and viewport_size is not None:
            scene = scene.model_copy(update={"viewport_size": viewport_size})
        return scene
    elements: list[UIElement] = []
    for e in ev.get("elements", []) or []:
        b = e.get("box") or [0, 0, 0, 0]
        elements.append(UIElement(
            type=e.get("type", "text"),
            box=Box(x=b[0], y=b[1], w=b[2], h=b[3]),
            text=e.get("text"),
            confidence=e.get("confidence", 0.9),
            suggested_actions=e.get("suggested_actions") or [],
            type_confidence=e.get("type_confidence"),
            type_source=e.get("type_source"),
            type_evidence=e.get("type_evidence") or [],
            intent_label=e.get("intent_label"),
            intent_confidence=e.get("intent_confidence"),
            intent_source=e.get("intent_source"),
            element_id=e.get("id", 0),
            whitebox_hint=e.get("whitebox_hint"),
        ))
    app_state = ev.get("app_state")
    available_intents = ev.get("available_intents")
    safe_actions = ev.get("safe_actions")
    classification_evidence = ev.get("classification_evidence")
    source_frame_ids = ev.get("source_frame_ids")
    source_timestamps = ev.get("source_timestamps")
    viewport_size = _coerce_viewport_size(ev.get("viewport_size"))
    return Scene(
        frame_id=ev.get("frame_id", 0),
        timestamp=ev.get("scene_timestamp", ev.get("ts", 0.0)),
        elements=elements,
        source_frame_ids=source_frame_ids if isinstance(source_frame_ids, list) else [],
        source_timestamps=source_timestamps if isinstance(source_timestamps, list) else [],
        observation_mode=(
            ev.get("observation_mode") if isinstance(ev.get("observation_mode"), str) else "raw"
        ),
        stable_frame=(
            bool(ev.get("stable_frame")) if isinstance(ev.get("stable_frame"), bool) else None
        ),
        viewport_size=viewport_size,
        scene_type=ev.get("scene_type"),
        semantic_scene_type=(
            ev.get("semantic_scene_type")
            if isinstance(ev.get("semantic_scene_type"), str) else None
        ),
        platform_scene_kind=(
            ev.get("platform_scene_kind")
            if isinstance(ev.get("platform_scene_kind"), str) else None
        ),
        context=ev.get("context") if isinstance(ev.get("context"), str) else None,
        available_intents=available_intents if isinstance(available_intents, list) else [],
        vlm_described=bool(ev.get("vlm_described", False)),
        vlm_status=ev.get("vlm_status") if isinstance(ev.get("vlm_status"), str) else None,
        vlm_model=ev.get("vlm_model") if isinstance(ev.get("vlm_model"), str) else None,
        vlm_scene_hint=(
            ev.get("vlm_scene_hint") if isinstance(ev.get("vlm_scene_hint"), str) else None
        ),
        vlm_elapsed_ms=(
            int(ev.get("vlm_elapsed_ms"))
            if isinstance(ev.get("vlm_elapsed_ms"), (int, float)) else None
        ),
        vlm_usage=ev.get("vlm_usage") if isinstance(ev.get("vlm_usage"), dict) else {},
        vlm_error=ev.get("vlm_error") if isinstance(ev.get("vlm_error"), str) else None,
        vlm_requested_element_ids=_int_list(ev.get("vlm_requested_element_ids")),
        vlm_returned_element_ids=_int_list(ev.get("vlm_returned_element_ids")),
        vlm_missing_element_ids=_int_list(ev.get("vlm_missing_element_ids")),
        vlm_intent_coverage=(
            float(ev.get("vlm_intent_coverage"))
            if isinstance(ev.get("vlm_intent_coverage"), (int, float)) else None
        ),
        page_id=ev.get("page_id") if isinstance(ev.get("page_id"), str) else None,
        safe_actions=safe_actions if isinstance(safe_actions, list) else [],
        classification_source=(
            ev.get("classification_source")
            if isinstance(ev.get("classification_source"), str) else None
        ),
        classification_confidence=(
            ev.get("classification_confidence")
            if isinstance(ev.get("classification_confidence"), (int, float)) else None
        ),
        classification_evidence=(
            classification_evidence if isinstance(classification_evidence, list) else []
        ),
        app_state=app_state if isinstance(app_state, dict) else {},
        current_vc=ev.get("current_vc"),       # absent in pre-2026-05-16 recordings
        whitebox_evaluated=bool(ev.get("whitebox_evaluated", False)),
    )


def _coerce_viewport_size(value: Any) -> tuple[int, int] | None:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            return int(value[0]), int(value[1])
        except (TypeError, ValueError):
            return None
    return None


def _int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    out: list[int] = []
    for item in value:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


def _snapshot_frames(run_dir: Path, events: list[dict]) -> dict[int, Path]:
    frames: dict[int, Path] = {}
    for ev in events:
        if ev.get("type") != "snapshot":
            continue
        frame_file = ev.get("frame_file")
        if not isinstance(frame_file, str) or not frame_file:
            continue
        try:
            seq = int(ev.get("seq"))
        except (TypeError, ValueError):
            continue
        frames[seq] = run_dir / frame_file
    return frames


def _load_frame_img(path: Path | None):
    if path is None or not path.exists():
        return None
    try:
        import cv2
    except ImportError:
        return None
    return cv2.imread(str(path))


def build_from_recording(
    run_dir: str | Path,
    bundle_id: str,
    *,
    app_version: str | None = None,
    memory: ScreenMemory | None = None,
) -> UTG:
    """Replay a run's events.jsonl into a UTG.

    If `memory` is given, observations fold into its existing graph; otherwise
    a fresh UTG is built. A 'scene' event is paired with exactly one 'action'
    event since the previous scene → that becomes the transition edge. If
    multiple actions occurred, no single-step edge is learned.
    """
    run_path = Path(run_dir)
    events = list(_iter_events(run_path))
    snapshot_frames = _snapshot_frames(run_path, events)
    mem = memory or ScreenMemory(UTG(bundle_id=bundle_id, app_version=app_version))
    pending: list[ActionRecord] = []
    last_scene_snapshot_seq: int | None = None
    last_scene_frame_id: int | None = None
    for ev in events:
        kind = ev.get("type")
        if kind == "action":
            kwargs = {k: v for k, v in ev.items() if k not in ("ts", "seq", "type", "op")}
            pending.append(ActionRecord.from_op(ev.get("op", ""), kwargs))
        elif kind == "scene":
            action = pending[0] if len(pending) == 1 else None
            snapshot_seq = ev.get("snapshot_seq")
            try:
                snapshot_seq = int(snapshot_seq)
            except (TypeError, ValueError):
                snapshot_seq = None
            scene = _scene_from_event(ev)
            frame_img = _load_frame_img(snapshot_frames.get(snapshot_seq))
            scene_event = ev.get("scene_event")
            is_metadata_refresh = scene_event in {"metadata", "metadata_refresh"}
            if not is_metadata_refresh and not pending:
                is_metadata_refresh = (
                    snapshot_seq is not None and snapshot_seq == last_scene_snapshot_seq
                ) or (
                    last_scene_frame_id is not None and scene.frame_id == last_scene_frame_id
                )
            if is_metadata_refresh:
                mem.merge_scene_metadata(scene, frame_img=frame_img)
            else:
                mem.observe(scene, action, frame_img=frame_img)
                pending = []
                last_scene_snapshot_seq = snapshot_seq
                last_scene_frame_id = scene.frame_id
    return mem.utg
