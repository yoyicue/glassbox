"""skills/smoke/test_memory_build_recording.py

Phase c — build a UTG offline by replaying an obs recording. Fully offline.

Coverage:
  - a recorded run (scene → action → scene) builds a 2-node, 1-edge UTG
  - the edge is labelled by the recorded action
  - an empty recording → an empty UTG, no crash
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from glassbox.cognition.base import Box, Scene, UIElement
from glassbox.memory import build_from_recording
from glassbox.obs.recorder import Recorder
from glassbox.perception.source import Frame


def _scene(*texts):
    els = [UIElement(type="button", box=Box(x=i * 10, y=i * 10, w=80, h=30),
                     text=t, confidence=0.9, element_id=i) for i, t in enumerate(texts)]
    return Scene(frame_id=0, timestamp=0.0, elements=els)


@pytest.mark.smoke
def test_build_from_recording_scene_action_scene(tmp_path):
    run_dir = tmp_path / "run1"
    rec = Recorder(run_dir, run_id="run1", save_frames=False)
    rec.snapshot(None)
    rec.scene(_scene("登录", "密码", "忘记密码"))
    rec.action("tap", x=10, y=20, via="tap_text", target="登录")
    rec.snapshot(None)
    rec.scene(_scene("设置", "隐私", "关于", "帮助"))
    rec.close()

    utg = build_from_recording(run_dir, bundle_id="com.x")
    assert len(utg.nodes) == 2
    assert len(utg.edges) == 1
    assert utg.edges[0].action_op == "tap"
    assert utg.edges[0].element_key == "text:登录"
    assert utg.edges[0].action_identity == "element:text:登录"


@pytest.mark.smoke
def test_build_from_recording_multiple_actions_between_scenes_does_not_learn_edge(tmp_path):
    run_dir = tmp_path / "run-multi-action"
    rec = Recorder(run_dir, run_id="run-multi-action", save_frames=False)
    rec.snapshot(None)
    rec.scene(_scene("登录", "密码", "忘记密码"))
    rec.action("tap", x=10, y=20, via="tap_text", target="登录")
    rec.action("key", modifier=0, keycode=40)
    rec.snapshot(None)
    rec.scene(_scene("设置", "隐私", "关于", "帮助"))
    rec.close()

    utg = build_from_recording(run_dir, bundle_id="com.x")
    assert len(utg.nodes) == 2
    assert utg.edges == []


@pytest.mark.smoke
def test_build_from_recording_preserves_layer3_scene_state(tmp_path):
    run_dir = tmp_path / "run-layer3"
    scene = _scene("登录", "密码")
    scene.scene_type = "login_form"
    scene.context = "账号登录页"
    scene.available_intents = ["确认登录", "找回密码"]
    scene.page_id = "login"
    scene.safe_actions = ["tap_login"]
    scene.classification_source = "test"
    scene.classification_confidence = 0.8
    scene.classification_evidence = ["recording"]
    scene.app_state = {"auth": "logged_out"}
    rec = Recorder(run_dir, run_id="run-layer3", save_frames=False)
    rec.snapshot(None)
    rec.scene(scene)
    rec.close()

    utg = build_from_recording(run_dir, bundle_id="com.x")
    node = next(iter(utg.nodes.values()))
    assert node.scene_type == "login_form"
    assert node.context == "账号登录页"
    assert node.available_intents == ["确认登录", "找回密码"]
    assert node.page_id == "login"
    assert node.safe_actions == ["tap_login"]
    assert node.classification_source == "test"
    assert node.classification_confidence == 0.8
    assert node.classification_evidence == ["recording"]
    assert node.app_state == {"auth": "logged_out"}


@pytest.mark.smoke
def test_build_from_recording_replays_metadata_scene_without_new_visit(tmp_path):
    run_dir = tmp_path / "run-metadata"
    scene = _scene("登录", "密码")
    enriched = scene.model_copy(deep=True)
    enriched.scene_type = "login_form"
    enriched.context = "账号登录页"

    rec = Recorder(run_dir, run_id="run-metadata", save_frames=False)
    rec.snapshot(None)
    rec.scene(scene)
    rec.scene(enriched, purpose="metadata")
    rec.close()

    utg = build_from_recording(run_dir, bundle_id="com.x")
    node = next(iter(utg.nodes.values()))

    assert len(utg.nodes) == 1
    assert node.visit_count == 1
    assert node.scene_type == "login_form"
    assert node.context == "账号登录页"


@pytest.mark.smoke
def test_build_from_recording_uses_snapshot_frame_for_signature(tmp_path):
    run_dir = tmp_path / "run-frame"
    rec = Recorder(run_dir, run_id="run-frame", save_frames=True)
    rec.snapshot(Frame(img=np.full((32, 24, 3), 255, dtype=np.uint8), ts=1.0))
    rec.scene(_scene("登录", "密码"))
    rec.close()

    utg = build_from_recording(run_dir, bundle_id="com.x")
    node = next(iter(utg.nodes.values()))

    assert node.signature.phash


@pytest.mark.smoke
def test_build_from_recording_uses_top_level_viewport_for_embedded_scene_without_png(tmp_path):
    run_dir = tmp_path / "run-viewport"
    run_dir.mkdir()
    scene = Scene(
        frame_id=1,
        timestamp=1.0,
        elements=[
            UIElement(type="unknown", box=Box(x=300, y=900, w=20, h=20), text=None, confidence=0.9),
        ],
    )
    (run_dir / "events.jsonl").write_text(
        json.dumps({
            "ts": 1.0,
            "seq": 0,
            "type": "scene",
            "viewport_size": [440, 956],
            "scene": scene.model_dump(mode="json"),
        }) + "\n",
        encoding="utf-8",
    )

    utg = build_from_recording(run_dir, bundle_id="com.x")
    node = next(iter(utg.nodes.values()))

    assert node.elements[0].key == "unknown@4,4"


@pytest.mark.smoke
def test_build_from_empty_recording(tmp_path):
    run_dir = tmp_path / "empty"
    Recorder(run_dir, run_id="empty", save_frames=False).close()
    utg = build_from_recording(run_dir, bundle_id="com.x")
    assert not utg.nodes and not utg.edges


@pytest.mark.smoke
def test_build_from_recording_tolerates_torn_trailing_line(tmp_path):
    """A run that crashed mid-write leaves a truncated final line in
    events.jsonl; the UTG rebuild must skip it instead of raising."""
    run_dir = tmp_path / "run1"
    rec = Recorder(run_dir, run_id="run1", save_frames=False)
    rec.snapshot(None)
    rec.scene(_scene("登录", "密码"))
    rec.action("tap", x=10, y=20, via="tap_text", target="登录")
    rec.snapshot(None)
    rec.scene(_scene("设置", "隐私"))
    rec.close()
    with (run_dir / "events.jsonl").open("a", encoding="utf-8") as fp:
        fp.write('{"ts": 9.0, "seq": 99, "type": "sc')  # crash artifact

    utg = build_from_recording(run_dir, bundle_id="com.x")

    assert len(utg.nodes) == 2
    assert len(utg.edges) == 1
