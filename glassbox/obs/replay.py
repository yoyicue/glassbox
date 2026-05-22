"""glassbox/obs/replay.py — recording replay (reads events.jsonl + frames/)

Without re-running any hardware, this turns an already-recorded run into
human-readable output:
  - summary: line count / type distribution / pass rate / Kimi hit rate / total duration
  - timeline: each event + its linked frame file + key fields
  - failures: only the events where verdict.passed=False

Usage:
    python3 -m glassbox.obs.replay <run_dir>
    python3 -m glassbox.obs.replay <run_dir> --timeline
    python3 -m glassbox.obs.replay <run_dir> --failures
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from glassbox.obs.recorder import iter_events


@dataclass
class ReplaySummary:
    run_id: str
    run_dir: Path
    n_events: int
    type_counts: dict[str, int]
    n_frames: int
    duration_s: float                            # max ts - min ts (monotonic seconds)
    verdicts_passed: int
    verdicts_failed: int
    kimi_hits: int
    kimi_misses: int
    kimi_avg_ms: float
    kimi_failures: int = 0
    kimi_parse_errors: int = 0
    actions: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)

    def kimi_hit_rate(self) -> float:
        total = self.kimi_hits + self.kimi_misses
        return self.kimi_hits / total if total else 0.0

    def verdict_pass_rate(self) -> float:
        total = self.verdicts_passed + self.verdicts_failed
        return self.verdicts_passed / total if total else 1.0

    def render_text(self) -> str:
        lines = [
            f"Run         {self.run_id}",
            f"Dir         {self.run_dir}",
            f"Duration    {self.duration_s:.2f}s",
            f"Events      {self.n_events}  distribution {self.type_counts}",
            f"Frames      {self.n_frames}",
            f"Verdicts    {self.verdicts_passed}/{self.verdicts_passed + self.verdicts_failed}"
            f" passed ({self.verdict_pass_rate() * 100:.0f}%)",
        ]
        if self.kimi_hits + self.kimi_misses:
            lines.append(
                f"Kimi calls  {self.kimi_hits + self.kimi_misses} "
                f"({self.kimi_hits} hit, {self.kimi_misses} miss) "
                f"hit rate={self.kimi_hit_rate() * 100:.0f}% "
                f"avg={self.kimi_avg_ms:.0f}ms "
                f"errors={self.kimi_failures} parse_errors={self.kimi_parse_errors}"
            )
        if self.actions:
            lines.append("")
            lines.append("Actions:")
            for a in self.actions:
                via = a.get("via", "?")
                target = a.get("target", "")
                t = f"x={a.get('x')} y={a.get('y')}" if "x" in a else ""
                lines.append(f"  {a.get('op')}({t}) via {via} target={target!r}")
        if self.failures:
            lines.append("")
            lines.append("Failures:")
            for f in self.failures:
                lines.append(f"  {f.get('name')} — {f.get('message')}")
        return "\n".join(lines)


class Replay:
    """Reads a run_dir and provides summary / timeline / failures."""

    def __init__(self, run_dir: Path | str):
        self.run_dir = Path(run_dir)
        if not (self.run_dir / "events.jsonl").exists():
            raise FileNotFoundError(f"{run_dir}/events.jsonl does not exist")
        self._events: list[dict[str, Any]] | None = None

    # —— reading ——
    @property
    def events(self) -> list[dict[str, Any]]:
        if self._events is None:
            self._events = list(iter_events(self.run_dir))
        return self._events

    def manifest(self) -> dict[str, Any]:
        """Read manifest.yaml with the same YAML parser Recorder writes with."""
        path = self.run_dir / "manifest.yaml"
        if not path.exists():
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ValueError(f"{path} root must be a YAML mapping")
        return data

    # —— aggregation ——
    def summary(self) -> ReplaySummary:
        events = self.events
        type_counts: dict[str, int] = {}
        actions: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        verdicts_passed = verdicts_failed = 0
        kimi_hits = kimi_misses = 0
        kimi_failures = kimi_parse_errors = 0
        kimi_elapsed: list[int] = []
        timestamps: list[float] = []

        for e in events:
            t = e.get("type", "")
            type_counts[t] = type_counts.get(t, 0) + 1
            ts = e.get("ts")
            if isinstance(ts, (int, float)):
                timestamps.append(float(ts))
            if t == "action":
                actions.append({k: v for k, v in e.items() if k not in {"ts", "seq", "type"}})
            elif t == "verdict":
                if e.get("passed"):
                    verdicts_passed += 1
                else:
                    verdicts_failed += 1
                    failures.append({"name": e.get("name"), "message": e.get("message")})
            elif t == "kimi_call":
                if e.get("hit"):
                    kimi_hits += 1
                else:
                    kimi_misses += 1
                if e.get("status") == "error":
                    kimi_failures += 1
                elif e.get("status") == "parse_error":
                    kimi_parse_errors += 1
                el = e.get("elapsed_ms")
                if isinstance(el, (int, float)):
                    kimi_elapsed.append(int(el))

        manifest = self.manifest()
        frame_files = {
            e.get("frame_file") for e in events
            if e.get("type") == "snapshot" and isinstance(e.get("frame_file"), str)
        }
        n_frames = sum(
            1 for frame_file in frame_files
            if (self.run_dir / frame_file).exists()
        )
        # duration only considers snapshot timestamps (the actual frame grab
        # time); other events use a default monotonic ts on a different base
        # than the frame ts, so mixing them would blow up
        snap_ts = [
            float(e["ts"]) for e in events
            if e.get("type") == "snapshot" and isinstance(e.get("ts"), (int, float))
        ]
        duration = (max(snap_ts) - min(snap_ts)) if len(snap_ts) >= 2 else 0.0

        return ReplaySummary(
            run_id=manifest.get("run_id", self.run_dir.name),
            run_dir=self.run_dir,
            n_events=len(events),
            type_counts=type_counts,
            n_frames=n_frames,
            duration_s=duration,
            verdicts_passed=verdicts_passed,
            verdicts_failed=verdicts_failed,
            kimi_hits=kimi_hits,
            kimi_misses=kimi_misses,
            kimi_failures=kimi_failures,
            kimi_parse_errors=kimi_parse_errors,
            kimi_avg_ms=(sum(kimi_elapsed) / len(kimi_elapsed)) if kimi_elapsed else 0.0,
            actions=actions,
            failures=failures,
        )

    # —— Timeline ——
    def iter_timeline(self) -> Iterator[str]:
        """Yield one human-readable line per event."""
        for e in self.events:
            yield self._format_event(e)

    @staticmethod
    def _format_event(e: dict[str, Any]) -> str:
        seq = e.get("seq", "?")
        t = e.get("type", "?")
        ts = e.get("ts")
        ts_str = f"{ts:9.3f}" if isinstance(ts, (int, float)) else "        ?"
        if t == "snapshot":
            f = e.get("frame_file") or "(no frame)"
            return f"[{ts_str}] #{seq:>3} snapshot   frame={f}"
        if t == "scene":
            return (
                f"[{ts_str}] #{seq:>3} scene      type={e.get('scene_type')}"
                f" n={e.get('n_elements')}"
            )
        if t == "action":
            via = e.get("via", "?")
            target = e.get("target", "")
            return (
                f"[{ts_str}] #{seq:>3} action     {e.get('op')}"
                f"(x={e.get('x')}, y={e.get('y')}) via={via} target={target!r}"
            )
        if t == "verdict":
            mark = "✓" if e.get("passed") else "✗"
            msg = e.get("message", "")
            tail = f" — {msg}" if msg else ""
            return f"[{ts_str}] #{seq:>3} verdict {mark}  {e.get('name')}{tail}"
        if t == "kimi_call":
            mark = "↻ hit" if e.get("hit") else "→ miss"
            return (
                f"[{ts_str}] #{seq:>3} kimi {mark}  model={e.get('model')}"
                f" elapsed={e.get('elapsed_ms')}ms"
            )
        return f"[{ts_str}] #{seq:>3} {t} {e}"

    def failures(self) -> list[dict[str, Any]]:
        return [e for e in self.events if e.get("type") == "verdict" and not e.get("passed")]


# ─── CLI ──────────────────────────────────────────────────────────────
def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Replay a recorded agent run.")
    ap.add_argument("run_dir", help="recording directory (contains events.jsonl + frames/)")
    ap.add_argument("--timeline", action="store_true", help="print the timeline event by event")
    ap.add_argument("--failures", action="store_true", help="list only the failed verdicts")
    ap.add_argument("--json", action="store_true", help="output the summary as JSON")
    args = ap.parse_args(argv)

    try:
        r = Replay(args.run_dir)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if args.failures:
        fails = r.failures()
        if not fails:
            print("(no failures)")
        else:
            for f in fails:
                print(json.dumps(f, ensure_ascii=False))
        return 0

    if args.timeline:
        for line in r.iter_timeline():
            print(line)
        return 0

    summary = r.summary()
    if args.json:
        out = {
            "run_id": summary.run_id,
            "run_dir": str(summary.run_dir),
            "n_events": summary.n_events,
            "type_counts": summary.type_counts,
            "n_frames": summary.n_frames,
            "duration_s": summary.duration_s,
            "verdicts_passed": summary.verdicts_passed,
            "verdicts_failed": summary.verdicts_failed,
            "kimi_hits": summary.kimi_hits,
            "kimi_misses": summary.kimi_misses,
            "kimi_failures": summary.kimi_failures,
            "kimi_parse_errors": summary.kimi_parse_errors,
            "kimi_avg_ms": summary.kimi_avg_ms,
            "actions": summary.actions,
            "failures": summary.failures,
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(summary.render_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
