"""glassbox/obs/recorder.py — recording of the frame + scene + action + verdict streams

While a walkthrough runs, persist to disk every perceived frame / scene /
triggered action / expect assertion, which helps with:
  - replaying failed cases
  - reusing Layer 3 Kimi calls (cache them, given that the frame is known)
  - manual review and showing developers the scene

Layout (one directory per run):

  <run_dir>/
    manifest.yaml         # run metadata
    events.jsonl          # the full chronological event stream (snapshot/scene/action/verdict)
    frames/
      00000.png           # the raw frame of each snapshot
      00001.png
      ...

events.jsonl has one JSON object per line, with fields:
  ts        (float, monotonic seconds)
  seq       (int,  increments in snapshot order)
  type      "snapshot" | "scene" | "action" | "verdict"
  ... fields specific to each type

Design:
- Recorder is entirely optional; Phone does not depend on it -- use it if
  present, skip it otherwise
- writes are synchronous -- simple and reliable; the walkthrough frequency
  (around 1 frame/second) is nowhere near a bottleneck
- unit tests do not need cv2 (snapshot accepts a None img -> writes an empty
  placeholder file)
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from glassbox.cognition.base import Scene
    from glassbox.perception.source import Frame


# ─── Event data structure ─────────────────────────────────────────────
@dataclass
class Event:
    """A single line in events.jsonl; every type uses this schema."""

    ts: float
    seq: int
    type: str                              # snapshot | scene | action | verdict
    payload: dict[str, Any] = field(default_factory=dict)

    def to_json_line(self) -> str:
        return json.dumps(
            {"ts": self.ts, "seq": self.seq, "type": self.type, **self.payload},
            ensure_ascii=False,
        )


# ─── Recorder ──────────────────────────────────────────────────────────
class Recorder:
    """A recording handle for a single run."""

    def __init__(
        self,
        run_dir: Path | str,
        *,
        run_id: str | None = None,
        meta: dict[str, Any] | None = None,
        save_frames: bool = True,
    ):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.frames_dir = self.run_dir / "frames"
        if self.frames_dir.exists():
            shutil.rmtree(self.frames_dir)
        self.frames_dir.mkdir(exist_ok=True)
        self.events_path = self.run_dir / "events.jsonl"
        self.manifest_path = self.run_dir / "manifest.yaml"

        self._events_fp = self.events_path.open("w", encoding="utf-8")
        self._seq = 0
        self._last_snapshot_seq = -1
        self._last_viewport_size: tuple[int, int] | None = None
        self._closed = False
        self.save_frames = save_frames

        self._write_manifest(run_id=run_id, meta=meta or {})

    # —— manifest ——
    def _write_manifest(self, *, run_id: str | None, meta: dict[str, Any]) -> None:
        manifest = {
            "run_id": run_id or self.run_dir.name,
            "started_at": time.time(),
            "started_monotonic": time.monotonic(),
            **meta,
        }
        self.manifest_path.write_text(
            yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    @staticmethod
    def _yaml_scalar(v: Any) -> str:
        if isinstance(v, (int, float, bool)):
            return str(v).lower() if isinstance(v, bool) else str(v)
        if v is None:
            return "null"
        s = str(v)
        # simple escaping: quote with single quotes if it contains special characters
        if any(c in s for c in ":#\n[]{}"):
            return repr(s)
        return s

    # —— internal ——
    def _next_seq(self) -> int:
        s = self._seq
        self._seq += 1
        return s

    def _write_event(self, type_: str, payload: dict[str, Any], *, ts: float | None = None) -> Event:
        if self._closed:
            raise RuntimeError("Recorder is already closed")
        ev = Event(
            ts=ts if ts is not None else time.monotonic(),
            seq=self._next_seq(),
            type=type_,
            payload=payload,
        )
        self._events_fp.write(ev.to_json_line() + "\n")
        self._events_fp.flush()
        return ev

    # —— public API ——
    def snapshot(self, frame: Frame | None, *, frame_id: int | None = None) -> Event:
        """Record one frame (optionally writing a png). Returns an Event
        whose frame_file field is a path relative to run_dir."""
        seq_for_frame = self._seq
        frame_file: str | None = None
        if frame is not None and frame.img is not None:
            self._last_viewport_size = (int(frame.img.shape[1]), int(frame.img.shape[0]))
        if self.save_frames and frame is not None and frame.img is not None:
            try:
                import cv2
                fname = f"{seq_for_frame:05d}.png"
                fpath = self.frames_dir / fname
                if cv2.imwrite(str(fpath), frame.img):
                    frame_file = f"frames/{fname}"
            except ImportError:
                frame_file = None

        payload: dict[str, Any] = {
            "frame_id": frame_id if frame_id is not None else (
                int(frame.ts * 1000) if frame is not None else 0
            ),
        }
        if self._last_viewport_size is not None:
            payload["viewport_size"] = list(self._last_viewport_size)
        if frame_file:
            payload["frame_file"] = frame_file
        ev = self._write_event(
            "snapshot",
            payload,
            ts=frame.ts if frame is not None else None,
        )
        self._last_snapshot_seq = ev.seq
        return ev

    def scene(self, scene: Scene, *, purpose: str = "observe") -> Event:
        """Record a summary of the current scene, linked to the most recent
        snapshot."""
        elements_summary = [
            {
                "id": e.element_id,
                "type": e.type,
                "text": e.text,
                "intent_label": e.intent_label,
                "intent_confidence": (
                    round(e.intent_confidence, 3)
                    if e.intent_confidence is not None else None
                ),
                "intent_source": e.intent_source,
                "box": [e.box.x, e.box.y, e.box.w, e.box.h],
                "confidence": round(e.confidence, 3),
                "type_confidence": (
                    round(e.type_confidence, 3)
                    if e.type_confidence is not None else None
                ),
                "type_source": e.type_source,
                "type_evidence": list(e.type_evidence),
                "suggested_actions": list(e.suggested_actions),
                "whitebox_hint": (
                    e.whitebox_hint.model_dump(mode="json")
                    if e.whitebox_hint is not None else None
                ),
            }
            for e in scene.elements
        ]
        return self._write_event(
            "scene",
            {
                "schema_version": 2,
                "scene_event": purpose,
                "frame_id": scene.frame_id,
                "scene_timestamp": scene.timestamp,
                "source_frame_ids": list(scene.source_frame_ids),
                "source_timestamps": list(scene.source_timestamps),
                "observation_mode": scene.observation_mode,
                "stable_frame": scene.stable_frame,
                "viewport_size": (
                    list(scene.viewport_size)
                    if scene.viewport_size is not None
                    else (list(self._last_viewport_size) if self._last_viewport_size else None)
                ),
                "ocr_vote_metadata": dict(scene.ocr_vote_metadata),
                "snapshot_seq": self._last_snapshot_seq,
                "scene": scene.model_dump(mode="json"),
                "scene_type": scene.scene_type,
                "semantic_scene_type": scene.semantic_scene_type,
                "platform_scene_kind": scene.platform_scene_kind,
                "context": scene.context,
                "available_intents": list(scene.available_intents),
                "vlm_described": scene.vlm_described,
                "vlm_status": scene.vlm_status,
                "vlm_model": scene.vlm_model,
                "vlm_scene_hint": scene.vlm_scene_hint,
                "vlm_elapsed_ms": scene.vlm_elapsed_ms,
                "vlm_usage": dict(scene.vlm_usage),
                "vlm_error": scene.vlm_error,
                "vlm_requested_element_ids": list(scene.vlm_requested_element_ids),
                "vlm_returned_element_ids": list(scene.vlm_returned_element_ids),
                "vlm_missing_element_ids": list(scene.vlm_missing_element_ids),
                "vlm_intent_coverage": scene.vlm_intent_coverage,
                "page_id": scene.page_id,
                "safe_actions": list(scene.safe_actions),
                "classification_source": scene.classification_source,
                "classification_confidence": scene.classification_confidence,
                "classification_evidence": list(scene.classification_evidence),
                "app_state": dict(scene.app_state),
                "current_vc": scene.current_vc,
                "whitebox_evaluated": scene.whitebox_evaluated,
                "n_elements": len(scene.elements),
                "elements": elements_summary,
            },
        )

    def action(self, op: str, **kwargs: Any) -> Event:
        """Record one effector action."""
        return self._write_event("action", {"op": op, **kwargs})

    def verdict(self, name: str, *, passed: bool, message: str = "") -> Event:
        """Record one assertion result (expect_text / expect_no_text / custom)."""
        return self._write_event(
            "verdict",
            {"name": name, "passed": passed, "message": message},
        )

    def kimi_call(
        self,
        *,
        model: str,
        hit: bool,
        elapsed_ms: int,
        usage: dict[str, Any] | None = None,
        scene_hint: str | None = None,
        status: str = "ok",
        error: str | None = None,
        parse_ok: bool | None = None,
    ) -> Event:
        """Record one Kimi (Layer 3 VLM) call. hit=True means a cache hit
        that skipped the network."""
        return self._write_event(
            "kimi_call",
            {
                "model": model,
                "hit": hit,
                "elapsed_ms": elapsed_ms,
                "usage": usage or {},
                "scene_hint": scene_hint,
                "status": status,
                "error": error,
                "parse_ok": parse_ok,
            },
        )

    def close(self) -> None:
        if not self._closed:
            self._events_fp.flush()
            self._events_fp.close()
            self._closed = True

    # —— context manager ——
    def __enter__(self) -> Recorder:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# ─── convenience factory ──────────────────────────────────────────────
def open_recorder(
    base_dir: Path | str,
    *,
    run_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> Recorder:
    """Create a Recorder in a timestamp-based subdirectory under base_dir.

    e.g. open_recorder("recordings/") -> recordings/2026-05-15T18-30-22/
    """
    base = Path(base_dir)
    if run_id is None:
        run_id = datetime.now().strftime("%Y-%m-%dT%H-%M-%S-%f")
    run_dir = base / run_id
    if run_dir.exists():
        stem = run_id
        suffix = 1
        while run_dir.exists():
            run_id = f"{stem}-{suffix}"
            run_dir = base / run_id
            suffix += 1
    return Recorder(run_dir, run_id=run_id, meta=meta)


# ─── read side: events.jsonl parsing (for replay) ─────────────────────
def iter_events(run_dir: Path | str):
    """Read events.jsonl line by line, yielding dicts."""
    path = Path(run_dir) / "events.jsonl"
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)
