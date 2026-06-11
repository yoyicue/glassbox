"""Run ledger and artifact storage for computer-use runtime."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from glassbox.cognition.base import Scene
from glassbox.perception.source import Frame

_TRACE_LEVEL_RANK = {"off": 0, "summary": 1, "standard": 2, "full": 3}


def _json_default(value: Any):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )


def _count_by(events: list[dict[str, Any]], key_fn) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        key = key_fn(event)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _bucket_key(value: Any) -> str:
    if not isinstance(value, dict):
        return "none"
    return "/".join(
        str(value.get(key) or "unknown")
        for key in ("control_role", "size_bucket", "region_zone")
    )


def _harness_version() -> str:
    repo = Path(__file__).resolve().parents[2]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return "unknown"
    value = result.stdout.strip()
    return f"git:{value}" if value else "unknown"


@dataclass(frozen=True)
class StoredFrame:
    frame_id: str
    ts: float
    file: str | None
    viewport: dict[str, int] | None
    stable: bool | None
    observation_role: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "ts": self.ts,
            "file": self.file,
            "viewport": self.viewport,
            "source": "phone.snapshot",
            "stable": self.stable,
            "capture_mode": "stable" if self.stable else "raw",
            "observation_role": self.observation_role,
        }


@dataclass(frozen=True)
class StoredScene:
    scene_id: str
    frame_id: str | None
    file: str | None
    scene_type: str | None
    page_id: str | None
    observation_role: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "frame_id": self.frame_id,
            "file": self.file,
            "scene_type": self.scene_type,
            "page_id": self.page_id,
            "observation_role": self.observation_role,
        }


class AuditSink:
    """Synchronized append-only audit writer.

    The recorder thread must not write this stream directly. Runtime code calls
    this sink from the orchestrator path only.
    """

    def __init__(self, path: Path, *, run_id: str):
        self.path = path
        self.run_id = run_id
        self._fp = path.open("w", encoding="utf-8")
        self._seq = 0
        self._closed = False
        self._write_failed = False

    def append(
        self,
        type_: str,
        *,
        actor: str = "runtime",
        attempt_id: str | None = None,
        attempt_group_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._closed:
            raise RuntimeError("AuditSink is already closed")
        event = {
            "event_id": f"evt_{self._seq:06d}",
            "seq": self._seq,
            "ts": time.monotonic(),
            "run_id": self.run_id,
            "type": type_,
            "actor": actor,
            "attempt_id": attempt_id,
            "attempt_group_id": attempt_group_id,
            "payload": payload or {},
        }
        self._seq += 1
        if self._write_failed:
            return event
        try:
            self._fp.write(json.dumps(event, ensure_ascii=False, default=_json_default) + "\n")
            self._fp.flush()
        except OSError as exc:
            # The audit stream is observability, not the run itself: a
            # disk-full / IO error mid-run must not kill the live run. Log
            # loudly once, mark the sink dead, and no-op every later write.
            self._write_failed = True
            logger.error(
                "AuditSink write to {} failed ({}); audit recording disabled "
                "for the rest of this run — the run continues unrecorded",
                self.path,
                exc,
            )
        return event

    def close(self) -> None:
        if not self._closed:
            try:
                self._fp.flush()
                self._fp.close()
            except OSError:
                # The sink already failed mid-run (and logged); teardown must
                # not raise again.
                pass
            self._closed = True


class ArtifactStore:
    """Self-contained run artifact directory."""

    def __init__(
        self,
        root: Path | str,
        *,
        run_id: str | None = None,
        platform: str = "ios",
        trace_level: str = "standard",
        manifest_extra: dict[str, Any] | None = None,
    ):
        self.root = Path(root)
        self.run_id = run_id or datetime.now().strftime("run_%Y_%m_%d_%H_%M_%S_%f")
        self.trace_level = trace_level
        self.run_dir = self.root / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.frames_dir = self.run_dir / "frames"
        self.scenes_dir = self.run_dir / "scenes"
        self.diffs_dir = self.run_dir / "diffs"
        self.verifications_dir = self.run_dir / "verifications"
        for directory in (
            self.frames_dir,
            self.scenes_dir,
            self.diffs_dir,
            self.verifications_dir,
        ):
            directory.mkdir(exist_ok=True)
        self.audit = AuditSink(self.run_dir / "audit.jsonl", run_id=self.run_id)
        self.actions_path = self.run_dir / "actions.jsonl"
        self.groups_path = self.run_dir / "attempt_groups.jsonl"
        self.approvals_path = self.run_dir / "approvals.jsonl"
        self.actuation_profile_path = self.run_dir / "actuation_profile.json"
        self.actuation_report_path = self.run_dir / "actuation_report.json"
        self.timeline_path = self.run_dir / "review_timeline.json"
        self.report_md_path = self.run_dir / "report.md"
        self.report_html_path = self.run_dir / "report.html"
        self._frame_seq = 0
        self._scene_seq = 0
        self._diff_seq = 0
        self._frames_promoted = 0
        self._frame_files_saved = 0
        self._frame_artifacts_skipped = 0
        self._scene_files_saved = 0
        self._verification_files_saved = 0
        self._actions_projected = 0
        self._approvals_projected = 0
        self._closed = False
        for path in (self.actions_path, self.groups_path, self.approvals_path):
            path.touch()
        self._manifest = {
            "run_id": self.run_id,
            "started_at": datetime.now().astimezone().isoformat(),
            "started_monotonic": time.monotonic(),
            "harness_version": _harness_version(),
            "platform": platform,
            "device": {
                "name": None,
                "model": None,
                "os_version": None,
                "locale": None,
            },
            "artifact_schema_version": 1,
            "trace_level": trace_level,
            "privacy_mode": "sandbox_phone",
            "observation_buffer": {
                "min_retention_ms": 10000,
                "min_retention_frames": 120,
                "clock": "monotonic",
                "drop_policy": "drop_unpromoted_oldest",
            },
        }
        self._manifest.update(manifest_extra or {})
        _write_json(self.run_dir / "manifest.json", self._manifest)
        self.audit.append("run.started", payload={"run_id": self.run_id})

    def effective_trace_level(self, override: str | None = None) -> str:
        if override is None:
            return self.trace_level
        if override not in _TRACE_LEVEL_RANK:
            raise ValueError(f"unsupported trace level override: {override}")
        current_rank = _TRACE_LEVEL_RANK.get(self.trace_level, _TRACE_LEVEL_RANK["standard"])
        requested_rank = _TRACE_LEVEL_RANK[override]
        return override if requested_rank > current_rank else self.trace_level

    def next_attempt_group_id(self) -> str:
        return f"grp_{int(time.time() * 1000)}_{self._frame_seq:06d}"

    def next_attempt_id(self) -> str:
        return f"act_{int(time.time() * 1000)}_{self._scene_seq:06d}"

    def promote_frame(
        self,
        frame: Frame | None,
        *,
        role: str,
        stable: bool | None = None,
        attempt_id: str | None = None,
        attempt_group_id: str | None = None,
        trace_level: str | None = None,
    ) -> StoredFrame | None:
        if frame is None:
            return None
        frame_id = f"frm_{self._frame_seq:06d}"
        self._frame_seq += 1
        rel_file: str | None = None
        effective_trace_level = self.effective_trace_level(trace_level)
        save_frame = effective_trace_level == "full" or (
            effective_trace_level == "standard"
            and role in {"before_requested", "before_command", "after", "after_window"}
        )
        if save_frame and frame.img is not None:
            try:
                import cv2

                filename = f"{frame_id}.png"
                if cv2.imwrite(str(self.frames_dir / filename), frame.img):
                    rel_file = f"frames/{filename}"
                    self._frame_files_saved += 1
            except Exception:
                rel_file = None
        if frame.img is not None and rel_file is None:
            self._frame_artifacts_skipped += 1
        self._frames_promoted += 1
        viewport = None
        if frame.img is not None:
            h, w = frame.img.shape[:2]
            viewport = {"width": int(w), "height": int(h)}
        stored = StoredFrame(
            frame_id=frame_id,
            ts=frame.ts,
            file=rel_file,
            viewport=viewport,
            stable=stable,
            observation_role=role,
        )
        self.audit.append(
            "frame.captured",
            attempt_id=attempt_id,
            attempt_group_id=attempt_group_id,
            payload=stored.to_dict(),
        )
        return stored

    def store_scene(
        self,
        scene: Scene | None,
        *,
        frame_id: str | None,
        role: str,
        attempt_id: str | None = None,
        attempt_group_id: str | None = None,
        trace_level: str | None = None,
    ) -> StoredScene | None:
        if scene is None:
            return None
        scene_id = f"scn_{self._scene_seq:06d}"
        self._scene_seq += 1
        rel_file: str | None = None
        effective_trace_level = self.effective_trace_level(trace_level)
        if effective_trace_level != "off":
            filename = f"{scene_id}.json"
            rel_file = f"scenes/{filename}"
            if effective_trace_level == "summary":
                payload = {
                    "scene_id": scene_id,
                    "runtime_frame_id": frame_id,
                    "observation_role": role,
                    "texts": [e.text for e in scene.elements if e.text],
                    "scene_type": scene.semantic_scene_type or scene.scene_type,
                    "page_id": scene.page_id,
                    "n_elements": len(scene.elements),
                }
            else:
                payload = scene.model_dump(mode="json")
                payload.update({
                    "scene_id": scene_id,
                    "runtime_frame_id": frame_id,
                    "observation_role": role,
                })
            _write_json(self.scenes_dir / filename, payload)
            self._scene_files_saved += 1
        stored = StoredScene(
            scene_id=scene_id,
            frame_id=frame_id,
            file=rel_file,
            scene_type=scene.semantic_scene_type or scene.scene_type,
            page_id=scene.page_id,
            observation_role=role,
        )
        self.audit.append(
            "scene.observed",
            attempt_id=attempt_id,
            attempt_group_id=attempt_group_id,
            payload=stored.to_dict(),
        )
        return stored

    def store_diff(
        self,
        attempt_id: str,
        payload: dict[str, Any],
        *,
        trace_level: str | None = None,
    ) -> dict[str, str | None]:
        if self.effective_trace_level(trace_level) == "off":
            return {"frame": None, "scene": None}
        frame_path = self.diffs_dir / f"{attempt_id}.frame_diff.json"
        scene_path = self.diffs_dir / f"{attempt_id}.scene_diff.json"
        _write_json(frame_path, payload.get("frame") or {})
        _write_json(scene_path, payload.get("scene") or {})
        self._diff_seq += 1
        return {
            "frame": f"diffs/{frame_path.name}",
            "scene": f"diffs/{scene_path.name}",
        }

    def store_verification(self, attempt_id: str, payload: dict[str, Any]) -> str:
        path = self.verifications_dir / f"{attempt_id}.verification.json"
        _write_json(path, payload)
        self._verification_files_saved += 1
        return f"verifications/{path.name}"

    def append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, ensure_ascii=False, default=_json_default) + "\n")

    def append_action(self, payload: dict[str, Any]) -> None:
        self.append_jsonl(self.actions_path, payload)
        self._actions_projected += 1
        self.audit.append(
            "action.summary.projected",
            attempt_id=payload.get("attempt_id"),
            attempt_group_id=payload.get("attempt_group_id"),
            payload={"path": "actions.jsonl"},
        )

    def append_group(self, payload: dict[str, Any]) -> None:
        self.append_jsonl(self.groups_path, payload)

    def append_approval(self, payload: dict[str, Any]) -> None:
        self.append_jsonl(self.approvals_path, payload)
        self._approvals_projected += 1

    def write_actuation_profile(self, payload: dict[str, Any]) -> None:
        _write_json(self.actuation_profile_path, payload)

    def write_actuation_report(self) -> None:
        events: list[dict[str, Any]] = []
        if self.audit.path.exists():
            for line in self.audit.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if str(event.get("type", "")).startswith("actuation."):
                    events.append(event)
        report = {
            "run_id": self.run_id,
            "event_counts": _count_by(events, lambda event: str(event.get("type") or "unknown")),
            "attempt_labels": _count_by(
                [event for event in events if event.get("type") == "actuation.attempt_attributed"],
                lambda event: str((event.get("payload") or {}).get("label") or "unknown"),
            ),
            "group_labels": _count_by(
                [event for event in events if event.get("type") == "actuation.attributed"],
                lambda event: str((event.get("payload") or {}).get("label") or "unknown"),
            ),
            "skipped_reasons": _count_by(
                [event for event in events if event.get("type") == "actuation.skipped"],
                lambda event: str((event.get("payload") or {}).get("reason") or "unknown"),
            ),
            "landing_signals": _count_by(
                [event for event in events if event.get("type") == "actuation.landing_observed"],
                lambda event: str((event.get("payload") or {}).get("landing_signal") or "unknown"),
            ),
            "control_buckets": _count_by(
                events,
                lambda event: _bucket_key((event.get("payload") or {}).get("control_bucket")),
            ),
        }
        _write_json(self.actuation_report_path, report)

    def update_manifest(self, payload: dict[str, Any]) -> None:
        self._manifest.update(payload)
        _write_json(self.run_dir / "manifest.json", self._manifest)

    def write_review_outputs(self, actions: list[dict[str, Any]]) -> None:
        timeline = {"run_id": self.run_id, "actions": actions}
        _write_json(self.timeline_path, timeline)
        lines = ["# Computer-Use Runtime Report\n", f"Run: `{self.run_id}`\n"]
        html_items: list[str] = []
        for action in actions:
            semantic = action.get("semantic", {})
            before = action.get("before_command") or action.get("before_requested") or {}
            after = action.get("after") or {}
            lines.append(
                f"## `{action.get('op')}` `{action.get('attempt_id')}`\n\n"
                f"transport={action.get('command_result', {}).get('transport_ok')} "
                f"semantic={semantic.get('status')} verifier={semantic.get('verifier')}\n\n"
                f"reason: {semantic.get('reason')}\n"
            )
            if before.get("screenshot"):
                lines.append(f"\nBefore:\n\n![before]({before['screenshot']})\n")
            if after.get("screenshot"):
                lines.append(f"\nAfter:\n\n![after]({after['screenshot']})\n")
            evidence = semantic.get("matched_evidence") or semantic.get("missing_evidence") or []
            if evidence:
                lines.append(f"\nEvidence: `{evidence}`\n")
            if action.get("diff_summary"):
                diff_json = json.dumps(
                    action["diff_summary"],
                    ensure_ascii=False,
                    indent=2,
                    default=_json_default,
                )
                lines.append(f"\nDiff summary:\n\n```json\n{diff_json}\n```\n")
            if action.get("after_window"):
                lines.append("\nAfter window:\n")
                for item in action["after_window"]:
                    lines.append(
                        f"- frame `{item.get('frame_id')}`, scene `{item.get('scene_id')}`, "
                        f"screenshot `{item.get('screenshot')}`\n"
                    )
            before_img = (
                f"<figure><figcaption>Before</figcaption><img src='{before['screenshot']}'></figure>"
                if before.get("screenshot")
                else ""
            )
            after_img = (
                f"<figure><figcaption>After</figcaption><img src='{after['screenshot']}'></figure>"
                if after.get("screenshot")
                else ""
            )
            diff_html = (
                "<details><summary>Diff summary</summary><pre>"
                + json.dumps(action.get("diff_summary"), ensure_ascii=False, indent=2, default=_json_default)
                + "</pre></details>"
                if action.get("diff_summary")
                else ""
            )
            html_items.append(
                "<section>"
                f"<h2>{action.get('op')} {action.get('attempt_id')}</h2>"
                f"<p>transport={action.get('command_result', {}).get('transport_ok')} "
                f"semantic={semantic.get('status')} verifier={semantic.get('verifier')}</p>"
                f"<p>{semantic.get('reason')}</p>"
                f"{before_img}{after_img}"
                f"{diff_html}"
                "</section>"
            )
        self.report_md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.report_html_path.write_text(
            "<html><body><h1>Computer-Use Runtime Report</h1>"
            f"<p>{self.run_id}</p>{''.join(html_items)}</body></html>\n",
            encoding="utf-8",
        )

    def artifact_metrics(self) -> dict[str, Any]:
        total_bytes = 0
        for path in self.run_dir.rglob("*"):
            if path.is_file():
                total_bytes += path.stat().st_size
        return {
            "frames_promoted": self._frames_promoted,
            "frame_files_saved": self._frame_files_saved,
            "frame_artifacts_skipped": self._frame_artifacts_skipped,
            "scene_files_saved": self._scene_files_saved,
            "diff_files_saved": self._diff_seq * 2,
            "verification_files_saved": self._verification_files_saved,
            "actions_projected": self._actions_projected,
            "approvals_projected": self._approvals_projected,
            "total_bytes_written": total_bytes,
        }

    def close(self, *, status: str = "finished") -> None:
        if self._closed:
            return
        metrics = self.artifact_metrics()
        self.update_manifest({"artifact_metrics": metrics})
        self.audit.append("run.finished", payload={"status": status, "artifact_metrics": metrics})
        self.audit.close()
        self._closed = True
