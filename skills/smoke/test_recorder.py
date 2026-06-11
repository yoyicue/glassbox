"""skills/smoke/test_recorder.py

obs.Recorder unit tests. Fully offline, writing to tmp_path.

Coverage:
  - manifest.yaml generation
  - snapshot writes a png + one line in events.jsonl
  - scene links to the seq of the most recent snapshot
  - action / verdict written individually
  - multi-event ordering and monotonically increasing seq
  - cannot write after close
  - when Phone uses a recorder, the tap_text chain is fully recorded
    (snapshot/scene/verdict/action)
  - an OSError mid-run disables the Recorder / AuditSink without killing
    the run (one loud log, no-op afterwards); non-IO errors still raise
  - iter_events tolerates a torn trailing line (crash artifact) but still
    raises on mid-file corruption
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from loguru import logger

from glassbox.cognition import Box, Scene, UIElement
from glassbox.obs import Recorder, open_recorder
from glassbox.obs.artifacts import AuditSink
from glassbox.obs.recorder import iter_events
from glassbox.perception.source import Frame


def _read_events(run_dir: Path) -> list[dict]:
    return list(iter_events(run_dir))


def _make_frame(w=10, h=10) -> Frame:
    return Frame(img=np.zeros((h, w, 3), dtype=np.uint8), ts=123.456)


# ─── basic read/write ────────────────────────────────────────────────
@pytest.mark.smoke
def test_recorder_creates_layout(tmp_path):
    rec = Recorder(tmp_path / "r1", run_id="r1", meta={"app": "demoapp"})
    rec.close()

    assert (tmp_path / "r1" / "manifest.yaml").exists()
    assert (tmp_path / "r1" / "events.jsonl").exists()
    assert (tmp_path / "r1" / "frames").is_dir()

    manifest = (tmp_path / "r1" / "manifest.yaml").read_text()
    assert "run_id: r1" in manifest
    assert "app: demoapp" in manifest


@pytest.mark.smoke
def test_snapshot_writes_png_and_event(tmp_path):
    rec = Recorder(tmp_path)
    ev = rec.snapshot(_make_frame())
    rec.close()

    assert ev.type == "snapshot"
    assert ev.seq == 0
    assert (tmp_path / "frames" / "00000.png").exists()

    events = _read_events(tmp_path)
    assert events == [
        {"ts": 123.456, "seq": 0, "type": "snapshot",
         "frame_id": int(123.456 * 1000), "viewport_size": [10, 10],
         "frame_file": "frames/00000.png"},
    ]


@pytest.mark.smoke
def test_snapshot_omits_frame_file_when_imwrite_fails(tmp_path, monkeypatch):
    import cv2

    monkeypatch.setattr(cv2, "imwrite", lambda *_args, **_kwargs: False)
    rec = Recorder(tmp_path)
    ev = rec.snapshot(_make_frame())
    rec.close()

    assert ev.type == "snapshot"
    assert not (tmp_path / "frames" / "00000.png").exists()
    events = _read_events(tmp_path)
    assert "frame_file" not in events[0]


@pytest.mark.smoke
def test_scene_attaches_to_last_snapshot(tmp_path):
    rec = Recorder(tmp_path)
    rec.snapshot(_make_frame())  # seq=0
    scene = Scene(frame_id=42, timestamp=123.5, elements=[
        UIElement(type="button", box=Box(x=10, y=10, w=100, h=44),
                  text="登录", confidence=0.9, element_id=0,
                  intent_label="确认登录"),
    ])
    scene.context = "登录页"
    scene.available_intents = ["确认登录"]
    scene.viewport_size = (100, 200)
    scene.semantic_scene_type = "login_form"
    scene.platform_scene_kind = "unit_platform"
    scene.vlm_requested_element_ids = [0, 1]
    scene.vlm_returned_element_ids = [0]
    scene.vlm_missing_element_ids = [1]
    scene.vlm_intent_coverage = 0.5
    scene.page_id = "login"
    scene.safe_actions = ["tap_login"]
    scene.classification_source = "test"
    scene.classification_confidence = 0.7
    scene.classification_evidence = ["unit"]
    scene.app_state = {"auth": "logged_out"}
    ev = rec.scene(scene)
    rec.close()

    assert ev.type == "scene"
    events = _read_events(tmp_path)
    scene_ev = events[1]
    assert scene_ev["type"] == "scene"
    assert scene_ev["snapshot_seq"] == 0
    assert scene_ev["scene_timestamp"] == 123.5
    assert scene_ev["source_frame_ids"] == []
    assert scene_ev["source_timestamps"] == []
    assert scene_ev["observation_mode"] == "raw"
    assert scene_ev["stable_frame"] is None
    assert scene_ev["viewport_size"] == [100, 200]
    assert scene_ev["scene_type"] is None
    assert scene_ev["semantic_scene_type"] == "login_form"
    assert scene_ev["platform_scene_kind"] == "unit_platform"
    assert scene_ev["vlm_described"] is False
    assert scene_ev["vlm_status"] is None
    assert scene_ev["vlm_requested_element_ids"] == [0, 1]
    assert scene_ev["vlm_returned_element_ids"] == [0]
    assert scene_ev["vlm_missing_element_ids"] == [1]
    assert scene_ev["vlm_intent_coverage"] == 0.5
    assert scene_ev["context"] == "登录页"
    assert scene_ev["available_intents"] == ["确认登录"]
    assert scene_ev["page_id"] == "login"
    assert scene_ev["safe_actions"] == ["tap_login"]
    assert scene_ev["classification_source"] == "test"
    assert scene_ev["classification_confidence"] == 0.7
    assert scene_ev["classification_evidence"] == ["unit"]
    assert scene_ev["app_state"] == {"auth": "logged_out"}
    assert scene_ev["schema_version"] == 2
    assert scene_ev["scene"]["page_id"] == "login"
    assert scene_ev["scene"]["safe_actions"] == ["tap_login"]
    assert scene_ev["n_elements"] == 1
    assert scene_ev["elements"][0]["intent_label"] == "确认登录"
    assert scene_ev["elements"][0]["intent_confidence"] is None
    assert scene_ev["elements"][0]["intent_source"] is None
    assert scene_ev["elements"][0]["suggested_actions"] == []
    assert scene_ev["elements"][0]["type_confidence"] is None
    assert scene_ev["elements"][0]["type_source"] is None


@pytest.mark.smoke
def test_phone_perceive_voted_records_multi_frame_provenance(tmp_path, mock_phone):
    class AdvancingSource:
        def __init__(self):
            self.timestamps = [1.0, 2.0]

        def snapshot(self):
            ts = self.timestamps.pop(0)
            return Frame(img=np.zeros((2, 2, 3), dtype=np.uint8), ts=ts)

    mock_phone.source = AdvancingSource()
    mock_phone.recorder = Recorder(tmp_path)
    mock_phone.ocr.elements = [
        UIElement(type="text", box=Box(x=0, y=0, w=10, h=10), text="设置", confidence=0.9),
    ]

    scene = mock_phone.perceive_voted(n=2)
    mock_phone.recorder.close()

    events = _read_events(tmp_path)
    snapshots = [e for e in events if e["type"] == "snapshot"]
    scene_ev = next(e for e in events if e["type"] == "scene")
    assert scene.frame_id == snapshots[-1]["frame_id"] == 2000
    assert scene.source_frame_ids == [1000, 2000]
    assert scene_ev["frame_id"] == snapshots[-1]["frame_id"]
    assert scene_ev["snapshot_seq"] == snapshots[-1]["seq"]
    assert scene_ev["source_frame_ids"] == [1000, 2000]
    assert scene_ev["scene"]["source_frame_ids"] == [1000, 2000]
    assert scene_ev["ocr_vote_metadata"]["samples_requested"] == 2
    assert scene_ev["scene"]["ocr_vote_metadata"]["samples_used"] == 2
    assert scene_ev["scene"]["ocr_vote_metadata"]["distinct_frames"] == 1
    assert scene_ev["scene"]["ocr_vote_metadata"]["degrade_reason"] == "duplicate_frames"


@pytest.mark.smoke
def test_scene_event_ts_uses_write_time_and_preserves_capture_time(tmp_path):
    rec = Recorder(tmp_path)
    rec.snapshot(_make_frame())
    scene = Scene(frame_id=42, timestamp=1.0, elements=[])
    ev = rec.scene(scene)
    rec.close()

    assert ev.ts != scene.timestamp
    scene_ev = _read_events(tmp_path)[1]
    assert scene_ev["ts"] != scene.timestamp
    assert scene_ev["scene_timestamp"] == scene.timestamp


@pytest.mark.smoke
def test_scene_records_type_confidence_metadata(tmp_path):
    rec = Recorder(tmp_path)
    scene = Scene(frame_id=42, timestamp=1.0, elements=[
        UIElement(
            type="button",
            box=Box(x=10, y=10, w=100, h=44),
            text="登录",
            confidence=0.95,
            type_confidence=0.7,
            type_source="rule_button",
            type_evidence=["fill"],
            element_id=0,
        ),
    ])

    rec.scene(scene)
    rec.close()

    element = _read_events(tmp_path)[0]["elements"][0]
    assert element["confidence"] == 0.95
    assert element["type_confidence"] == 0.7
    assert element["type_source"] == "rule_button"
    assert element["type_evidence"] == ["fill"]


@pytest.mark.smoke
def test_action_and_verdict(tmp_path):
    rec = Recorder(tmp_path)
    rec.action("tap", x=100, y=200, via="tap_text", target="登录")
    rec.verdict("expect_text(已登录)", passed=True)
    rec.verdict("expect_text(timeout)", passed=False, message="timed out after 5s")
    rec.close()

    events = _read_events(tmp_path)
    assert [e["type"] for e in events] == ["action", "verdict", "verdict"]
    assert events[0]["op"] == "tap"
    assert events[0]["target"] == "登录"
    assert events[1]["passed"] is True
    assert events[2]["passed"] is False
    assert events[2]["message"] == "timed out after 5s"


@pytest.mark.smoke
def test_seq_monotonic_across_types(tmp_path):
    rec = Recorder(tmp_path)
    rec.snapshot(_make_frame())  # seq=0
    rec.action("tap", x=1, y=2)  # seq=1
    rec.snapshot(_make_frame())  # seq=2
    rec.verdict("x", passed=True)  # seq=3
    rec.close()

    events = _read_events(tmp_path)
    assert [e["seq"] for e in events] == [0, 1, 2, 3]


@pytest.mark.smoke
def test_close_then_write_raises(tmp_path):
    rec = Recorder(tmp_path)
    rec.close()
    with pytest.raises(RuntimeError, match="closed"):
        rec.action("tap", x=1, y=2)


@pytest.mark.smoke
def test_open_recorder_creates_timestamped_dir(tmp_path):
    rec = open_recorder(tmp_path, run_id="custom-run")
    rec.close()
    assert (tmp_path / "custom-run").is_dir()


@pytest.mark.smoke
def test_open_recorder_default_run_id_is_unique(tmp_path):
    rec1 = open_recorder(tmp_path)
    rec2 = open_recorder(tmp_path)
    try:
        assert rec1.run_dir != rec2.run_dir
        assert rec1.run_dir.is_dir()
        assert rec2.run_dir.is_dir()
    finally:
        rec1.close()
        rec2.close()


@pytest.mark.smoke
def test_recorder_reused_directory_truncates_events(tmp_path):
    rec1 = Recorder(tmp_path)
    rec1.action("tap", x=1, y=2)
    rec1.close()

    rec2 = Recorder(tmp_path)
    rec2.verdict("fresh", passed=True)
    rec2.close()

    events = _read_events(tmp_path)
    assert [e["type"] for e in events] == ["verdict"]
    assert events[0]["seq"] == 0


@pytest.mark.smoke
def test_recorder_reused_directory_clears_stale_frames(tmp_path):
    rec1 = Recorder(tmp_path)
    rec1.snapshot(_make_frame())
    rec1.close()
    assert list((tmp_path / "frames").glob("*.png"))

    rec2 = Recorder(tmp_path, save_frames=False)
    rec2.verdict("fresh", passed=True)
    rec2.close()

    assert list((tmp_path / "frames").glob("*.png")) == []


@pytest.mark.smoke
def test_recorder_as_context_manager(tmp_path):
    with Recorder(tmp_path) as rec:
        rec.snapshot(_make_frame())
    # close should have happened already
    with pytest.raises(RuntimeError):
        rec.action("tap", x=1, y=2)


# ─── Phone x Recorder end-to-end ─────────────────────────────────────
@pytest.mark.smoke
def test_phone_records_full_chain(tmp_path, mock_phone):
    """The tap_text chain should produce snapshot -> scene -> verdict -> action."""
    mock_phone.recorder = Recorder(tmp_path)
    mock_phone.ocr.elements = [
        UIElement(type="text", box=Box(x=100, y=200, w=80, h=44),
                  text="登录", confidence=0.95, element_id=0),
    ]
    mock_phone.tap_text("登录")
    mock_phone.recorder.close()

    types = [e["type"] for e in _read_events(tmp_path)]
    # must have at least snapshot + scene + verdict(passed) + action(tap)
    assert "snapshot" in types
    assert "scene" in types
    assert "verdict" in types
    assert "action" in types
    # ordering: snapshot -> scene must come before action
    snap_i = types.index("snapshot")
    act_i = types.index("action")
    assert snap_i < act_i


@pytest.mark.smoke
def test_phone_records_expect_text_timeout(tmp_path, mock_phone):
    """expect_text times out -> verdict passed=False."""
    mock_phone.recorder = Recorder(tmp_path)
    mock_phone.ocr.elements = []
    with pytest.raises(AssertionError):
        mock_phone.expect_text("登录", timeout=0.05, poll_interval=0.02)
    mock_phone.recorder.close()

    events = _read_events(tmp_path)
    verdicts = [e for e in events if e["type"] == "verdict"]
    assert len(verdicts) == 1
    assert verdicts[0]["passed"] is False
    assert "timeout" in verdicts[0]["message"]


# ─── write-failure robustness (sinks must not kill the live run) ─────
class _ExplodingFp:
    """File stub whose write always raises the given exception."""

    def __init__(self, exc: Exception):
        self.exc = exc
        self.writes = 0

    def write(self, _data: str) -> None:
        self.writes += 1
        raise self.exc

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


@pytest.mark.smoke
def test_recorder_oserror_disables_recording_but_run_continues(tmp_path):
    rec = Recorder(tmp_path, save_frames=False)
    errors: list[str] = []
    handler_id = logger.add(lambda msg: errors.append(str(msg)), level="ERROR")
    try:
        fp = _ExplodingFp(OSError(28, "No space left on device"))
        rec._events_fp = fp
        ev1 = rec.action("tap", x=1, y=2)      # first write fails → one loud error
        ev2 = rec.verdict("v", passed=True)    # sink dead → no-op, no raise
        ev3 = rec.snapshot(None)
    finally:
        logger.remove(handler_id)

    assert rec._write_failed is True
    assert fp.writes == 1                       # later events never touch the fp
    assert (ev1.seq, ev2.seq, ev3.seq) == (0, 1, 2)
    disabled = [e for e in errors if "recording disabled" in e]
    assert len(disabled) == 1
    assert str(rec.events_path) in disabled[0]
    rec.close()                                 # teardown must not raise either


@pytest.mark.smoke
def test_recorder_non_io_write_error_still_raises(tmp_path):
    rec = Recorder(tmp_path, save_frames=False)
    rec._events_fp = _ExplodingFp(ValueError("bug, not disk"))
    with pytest.raises(ValueError):
        rec.action("tap")
    assert rec._write_failed is False


@pytest.mark.smoke
def test_audit_sink_oserror_disables_audit_but_run_continues(tmp_path):
    sink = AuditSink(tmp_path / "audit.jsonl", run_id="r1")
    errors: list[str] = []
    handler_id = logger.add(lambda msg: errors.append(str(msg)), level="ERROR")
    try:
        fp = _ExplodingFp(OSError(28, "No space left on device"))
        sink._fp = fp
        ev1 = sink.append("frame.captured")
        ev2 = sink.append("scene.observed")
    finally:
        logger.remove(handler_id)

    assert sink._write_failed is True
    assert fp.writes == 1
    assert (ev1["seq"], ev2["seq"]) == (0, 1)
    disabled = [e for e in errors if "audit recording disabled" in e]
    assert len(disabled) == 1
    assert str(sink.path) in disabled[0]
    sink.close()


@pytest.mark.smoke
def test_audit_sink_non_io_write_error_still_raises(tmp_path):
    sink = AuditSink(tmp_path / "audit.jsonl", run_id="r1")
    sink._fp = _ExplodingFp(TypeError("bug, not disk"))
    with pytest.raises(TypeError):
        sink.append("frame.captured")
    assert sink._write_failed is False


# ─── torn trailing line (crash artifact) tolerance ───────────────────
@pytest.mark.smoke
def test_iter_events_skips_torn_trailing_line(tmp_path):
    rec = Recorder(tmp_path, save_frames=False)
    rec.action("tap", x=1)
    rec.action("swipe", x=2)
    rec.close()
    with (tmp_path / "events.jsonl").open("a", encoding="utf-8") as fp:
        fp.write('{"ts": 3.0, "seq": 2, "type": "act')  # crash mid-write

    events = list(iter_events(tmp_path))

    assert len(events) == 2
    assert [e["type"] for e in events] == ["action", "action"]


@pytest.mark.smoke
def test_iter_events_raises_on_mid_file_corruption(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text(
        '{"ts": 1.0, "seq": 0, "type": "action"}\n'
        '{"ts": 2.0, "seq": 1, "type": "act\n'      # torn but NOT final → corruption
        '{"ts": 3.0, "seq": 2, "type": "action"}\n',
        encoding="utf-8",
    )
    with pytest.raises(json.JSONDecodeError):
        list(iter_events(tmp_path))
