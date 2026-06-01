"""skills/smoke/test_replay.py

Unit tests for Recorder.kimi_call + Replay. Fully offline.

Coverage:
  - kimi_call event is written
  - after Phone.describe runs, the recorder receives a kimi_call (hit/miss status correct)
  - Replay.summary counts correctly
  - Replay.iter_timeline output format
  - Replay.failures picks only failures
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from glassbox.cognition import Box, UIElement, VLMResponse
from glassbox.obs import Recorder, Replay
from glassbox.obs.recorder import iter_events


def _make_phone_with_kimi(mock_phone, kimi_obj):
    """Attach a fake kimi to mock_phone."""
    mock_phone.kimi = kimi_obj
    return mock_phone


def _read_events(run_dir: Path) -> list[dict]:
    return list(iter_events(run_dir))


# ─── kimi_call event ─────────────────────────────────────────────────
@pytest.mark.smoke
def test_kimi_call_event_written(tmp_path):
    rec = Recorder(tmp_path)
    rec.kimi_call(model="kimi-k2.6", hit=False, elapsed_ms=7500,
                  usage={"prompt_tokens": 200}, scene_hint="登录走查")
    rec.kimi_call(model="kimi-k2.6", hit=True, elapsed_ms=5)
    rec.close()

    events = _read_events(tmp_path)
    assert len(events) == 2
    assert events[0]["type"] == "kimi_call"
    assert events[0]["hit"] is False
    assert events[0]["elapsed_ms"] == 7500
    assert events[0]["scene_hint"] == "登录走查"
    assert events[1]["hit"] is True


@pytest.mark.smoke
def test_phone_describe_records_kimi_call_miss(tmp_path, mock_phone):
    """When phone.describe runs, the recorder should receive one kimi_call (hit=False)."""

    class MissKimi:
        model = "fake-miss"
        last_hit = False

        def describe_scene(self, *, frame_image, elements, scene_hint=None):
            return VLMResponse(
                raw_content="{}",
                parsed={"scene_type": "x", "elements": []},
                usage={"prompt_tokens": 10}, model="fake-miss", elapsed_ms=42,
            )

    rec = Recorder(tmp_path)
    mock_phone.recorder = rec
    mock_phone.ocr.elements = [
        UIElement(type="text", box=Box(x=0, y=0, w=10, h=10),
                  text="登录", confidence=0.9, element_id=0),
    ]
    _make_phone_with_kimi(mock_phone, MissKimi())

    mock_phone.perceive()
    mock_phone.describe(scene_hint="走查")
    rec.close()

    events = _read_events(tmp_path)
    kimi_evs = [e for e in events if e["type"] == "kimi_call"]
    assert len(kimi_evs) == 1
    assert kimi_evs[0]["hit"] is False
    assert kimi_evs[0]["model"] == "fake-miss"
    assert kimi_evs[0]["scene_hint"] == "走查"
    assert kimi_evs[0]["status"] == "ok"
    assert kimi_evs[0]["parse_ok"] is True
    assert kimi_evs[0]["usage"] == {"prompt_tokens": 10}
    scene_evs = [e for e in events if e["type"] == "scene"]
    assert len(scene_evs) == 2
    assert scene_evs[-1]["scene_type"] == "x"
    assert scene_evs[-1]["vlm_status"] == "ok"


@pytest.mark.smoke
def test_phone_describe_records_kimi_call_hit(tmp_path, mock_phone):
    """Pretend CachedKimi marks last_hit=True; Phone should record hit=True."""

    class HitKimi:
        """Simulate CachedKimi: describe_scene sets last_hit to True internally (simulating a hit)."""
        model = "fake-hit"
        last_hit = False

        def describe_scene(self, *, frame_image, elements, scene_hint=None):
            self.last_hit = True   # mark on call, just like CachedKimi
            return VLMResponse(raw_content="{}", parsed={"elements": []},
                                usage={}, model="fake-hit", elapsed_ms=1)

    rec = Recorder(tmp_path)
    mock_phone.recorder = rec
    mock_phone.ocr.elements = [
        UIElement(type="text", box=Box(x=0, y=0, w=10, h=10),
                  text="x", confidence=0.9, element_id=0),
    ]
    _make_phone_with_kimi(mock_phone, HitKimi())

    mock_phone.perceive()
    mock_phone.describe()
    rec.close()

    kimi_evs = [e for e in _read_events(tmp_path) if e["type"] == "kimi_call"]
    assert kimi_evs[0]["hit"] is True


@pytest.mark.smoke
def test_phone_describe_records_kimi_error_status(tmp_path, mock_phone):
    class ErrorKimi:
        model = "fake-error"
        last_hit = False

        def describe_scene(self, *, frame_image, elements, scene_hint=None):
            raise RuntimeError("network down")

    rec = Recorder(tmp_path)
    mock_phone.recorder = rec
    mock_phone.ocr.elements = [
        UIElement(type="text", box=Box(x=0, y=0, w=10, h=10),
                  text="登录", confidence=0.9, element_id=0),
    ]
    _make_phone_with_kimi(mock_phone, ErrorKimi())

    mock_phone.perceive()
    mock_phone.describe(scene_hint="走查")
    rec.close()

    events = _read_events(tmp_path)
    kimi_ev = next(e for e in events if e["type"] == "kimi_call")
    assert kimi_ev["status"] == "error"
    assert kimi_ev["parse_ok"] is False
    assert kimi_ev["error"] == "network down"
    scene_ev = [e for e in events if e["type"] == "scene"][-1]
    assert scene_ev["vlm_status"] == "error"
    assert scene_ev["vlm_error"] == "network down"


# ─── Replay ─────────────────────────────────────────────────────────
def _populate(rec: Recorder) -> None:
    """Build a typical run."""
    from glassbox.cognition import Scene
    from glassbox.perception.source import Frame
    rec.snapshot(Frame(img=np.zeros((1, 1, 3), dtype=np.uint8), ts=0.0))
    rec.scene(Scene(frame_id=0, timestamp=0.01, elements=[]))
    rec.kimi_call(model="kimi-k2.6", hit=False, elapsed_ms=7400)
    rec.verdict("expect_text(登录)", passed=True)
    rec.action("tap", x=100, y=200, via="tap_intent", target="确认登录")
    rec.snapshot(Frame(img=np.zeros((1, 1, 3), dtype=np.uint8), ts=8.0))
    rec.scene(Scene(frame_id=1, timestamp=8.01, elements=[]))
    rec.kimi_call(model="kimi-k2.6", hit=True, elapsed_ms=4)
    rec.verdict("expect_text(欢迎)", passed=False, message="timeout 5s")


@pytest.mark.smoke
def test_replay_loads_and_counts_types(tmp_path):
    with Recorder(tmp_path, run_id="t1", meta={"app": "demo"}) as rec:
        _populate(rec)

    r = Replay(tmp_path)
    s = r.summary()
    assert s.run_id == "t1"
    assert s.n_events == 9
    assert s.type_counts == {
        "snapshot": 2, "scene": 2, "kimi_call": 2,
        "verdict": 2, "action": 1,
    }
    assert s.verdicts_passed == 1
    assert s.verdicts_failed == 1
    assert s.kimi_hits == 1
    assert s.kimi_misses == 1
    assert s.kimi_failures == 0
    assert s.kimi_parse_errors == 0
    assert s.kimi_hit_rate() == 0.5
    assert s.verdict_pass_rate() == 0.5
    assert abs(s.kimi_avg_ms - (7400 + 4) / 2) < 0.5
    assert s.n_frames == 2
    assert s.duration_s == pytest.approx(8.0, abs=0.1)


@pytest.mark.smoke
def test_replay_failures(tmp_path):
    with Recorder(tmp_path) as rec:
        _populate(rec)
    r = Replay(tmp_path)
    fails = r.failures()
    assert len(fails) == 1
    assert fails[0]["name"] == "expect_text(欢迎)"


@pytest.mark.smoke
def test_replay_timeline_has_all_events(tmp_path):
    with Recorder(tmp_path) as rec:
        _populate(rec)
    r = Replay(tmp_path)
    lines = list(r.iter_timeline())
    assert len(lines) == 9
    text = "\n".join(lines)
    assert "snapshot" in text
    assert "scene" in text
    assert "action" in text
    assert "kimi" in text
    assert "verdict" in text
    # a failed verdict should have ✗
    assert "✗" in text
    # a passed verdict should have ✓
    assert "✓" in text


@pytest.mark.smoke
def test_replay_counts_failed_and_invalid_kimi_calls(tmp_path):
    with Recorder(tmp_path, run_id="kimi-errors") as rec:
        rec.kimi_call(
            model="fake",
            hit=False,
            elapsed_ms=10,
            status="error",
            error="network",
            parse_ok=False,
        )
        rec.kimi_call(
            model="fake",
            hit=False,
            elapsed_ms=10,
            status="parse_error",
            error="invalid parsed payload",
            parse_ok=False,
        )

    summary = Replay(tmp_path).summary()
    assert summary.kimi_misses == 2
    assert summary.kimi_failures == 1
    assert summary.kimi_parse_errors == 1


@pytest.mark.smoke
def test_replay_summary_counts_only_current_snapshot_frame_files(tmp_path):
    from glassbox.perception.source import Frame

    with Recorder(tmp_path) as rec:
        rec.snapshot(Frame(img=np.zeros((1, 1, 3), dtype=np.uint8), ts=1.0))
    stale = tmp_path / "frames" / "99999.png"
    stale.write_bytes(b"old")

    summary = Replay(tmp_path).summary()

    assert summary.n_frames == 1


@pytest.mark.smoke
def test_replay_summary_text_render(tmp_path):
    with Recorder(tmp_path, run_id="t2") as rec:
        _populate(rec)
    r = Replay(tmp_path)
    text = r.summary().render_text()
    assert "Run         t2" in text
    assert "Verdicts    1/2 passed" in text
    assert "Kimi calls" in text
    assert "Failures:" in text
    assert "expect_text(欢迎)" in text
    assert "Actions:" in text
    assert "确认登录" in text


@pytest.mark.smoke
def test_replay_reads_structured_manifest_yaml(tmp_path):
    with Recorder(tmp_path, run_id="nested", meta={"labels": ["a", "b"]}) as rec:
        rec.verdict("ok", passed=True)

    manifest = Replay(tmp_path).manifest()

    assert manifest["run_id"] == "nested"
    assert manifest["labels"] == ["a", "b"]


@pytest.mark.smoke
def test_replay_rejects_non_mapping_manifest_yaml(tmp_path):
    with Recorder(tmp_path, run_id="bad") as rec:
        rec.verdict("ok", passed=True)
    (tmp_path / "manifest.yaml").write_text("- not\n- a\n- mapping\n", encoding="utf-8")

    with pytest.raises(ValueError, match="root must be a YAML mapping"):
        Replay(tmp_path).manifest()


@pytest.mark.smoke
def test_replay_missing_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        Replay(tmp_path / "doesnt-exist")


@pytest.mark.smoke
def test_replay_cli_summary(tmp_path, capsys):
    from glassbox.obs.replay import _main
    with Recorder(tmp_path, run_id="cli-t") as rec:
        _populate(rec)
    rc = _main([str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "Run         cli-t" in captured.out


@pytest.mark.smoke
def test_replay_cli_json(tmp_path, capsys):
    from glassbox.obs.replay import _main
    with Recorder(tmp_path, run_id="cli-json") as rec:
        _populate(rec)
    rc = _main([str(tmp_path), "--json"])
    captured = capsys.readouterr()
    assert rc == 0
    data = json.loads(captured.out)
    assert data["run_id"] == "cli-json"
    assert data["n_events"] == 9
    assert data["kimi_hits"] == 1
