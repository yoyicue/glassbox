"""ObservationSummary wire-format contract.

The JSONL session (``glassbox.ai_session``) and the MCP server
(``glassbox.mcp.server``) used to hand-roll their own ObservationSummary
serializers and drifted: MCP silently dropped ``scene_type`` /
``visible_texts`` / ``actions`` / ``can_scroll`` / ``event_seq`` plus the
element fields ``suggested_actions`` / ``intent_label`` /
``preferred_tap_point`` / ``whitebox_hint``. Both now call
``glassbox.ai.observation_payload``; these tests push one rich observation
through BOTH real transports and assert dict equality, and pin the field
inventory against the dataclasses so the next drift fails loudly.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from glassbox.ai import (
    ElementBox,
    ObservationElement,
    ObservationSummary,
    RunArtifacts,
    observation_payload,
)
from glassbox.ai_session import AISessionService
from glassbox.mcp.server import HarnessMCPService

MCP_AUTH = {"auth_token": "secret", "session_id": "sess-a", "client_id": "client-a"}


def _rich_observation(run_dir: Path) -> ObservationSummary:
    """One observation exercising every serialized field, including the four
    element fields the MCP serializer used to drop."""
    return ObservationSummary(
        summary="settings root",
        page_id="settings/root",
        scene_type="settings",
        visible_texts=("设置", "通用"),
        actions=("tap", "scroll"),
        can_scroll=True,
        screenshot_path=run_dir / "frames" / "one.png",
        scene_path=run_dir / "scenes" / "one.json",
        event_seq=7,
        elements=(
            ObservationElement(
                element_id=3,
                type="button",
                text="通用",
                confidence=0.91,
                box=ElementBox(x=10, y=20, w=120, h=44, center=(70, 42)),
                suggested_actions=("tap",),
                intent_label="打开通用",
                preferred_tap_point=(70, 40),
                whitebox_hint={"vc": "SettingsVC"},
            ),
        ),
        viewport_size=(390, 844),
        coordinate_space="frame_px",
        crop_bbox=(0, 0, 390, 844),
        source_shape=(1920, 1080),
        projection="letterbox",
        platform_scene_kind="settings_root",
        current_vc="SettingsVC",
        whitebox_evaluated=True,
        app_state={"auth": "logged_in"},
    )


class _FakePhone:
    """Context-manager AIPhone double serving one fixed rich observation."""

    def __init__(self, run_dir: Path):
        self.run_id = "obs-run"
        self.run_dir = run_dir

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def observe(self) -> ObservationSummary:
        return _rich_observation(self.run_dir)

    def save_report(self) -> RunArtifacts:
        return RunArtifacts(
            run_id=self.run_id,
            run_name="obs",
            run_dir=self.run_dir,
            manifest_path=self.run_dir / "manifest.json",
            report_path=self.run_dir / "report.md",
            failure_path=None,
            latest_scene_path=self.run_dir / "scenes" / "one.json",
            latest_screenshot_path=self.run_dir / "frames" / "one.png",
            artifact_schema_version=1,
            ai_api_version="ai-api-v1",
        )


@pytest.mark.smoke
def test_ai_session_and_mcp_serialize_observation_identically(tmp_path):
    run_dir = tmp_path / "obs-run"

    # Path 1: JSONL session transport.
    session = AISessionService(open_phone_fn=lambda **_kw: _FakePhone(run_dir))
    session_obs = session.handle({"command": "observe"})["observation"]
    session.handle({"command": "close"})

    # Path 2: MCP transport.
    mcp = HarnessMCPService(
        artifact_root=tmp_path,
        auth_token="secret",
        open_phone_fn=lambda **_kw: _FakePhone(run_dir),
    )
    result = mcp.call_tool({"name": "observe_summary", "arguments": dict(MCP_AUTH)})
    mcp_payload = json.loads(result["content"][0]["text"])

    # MCP layers run_id/report_path on top and relativizes artifact paths to
    # the run dir — that is its only sanctioned divergence.
    assert mcp_payload.pop("run_id") == "obs-run"
    assert mcp_payload.pop("report_path") == "report.md"
    assert mcp_payload.pop("scene_path") == "scenes/one.json"
    assert mcp_payload.pop("screenshot_path") == "frames/one.png"
    assert session_obs.pop("scene_path") == str(run_dir / "scenes" / "one.json")
    assert session_obs.pop("screenshot_path") == str(run_dir / "frames" / "one.png")

    assert mcp_payload == session_obs

    # The fields the MCP serializer used to drop are now on the wire.
    assert mcp_payload["scene_type"] == "settings"
    assert mcp_payload["visible_texts"] == ["设置", "通用"]
    assert mcp_payload["actions"] == ["tap", "scroll"]
    assert mcp_payload["can_scroll"] is True
    assert mcp_payload["event_seq"] == 7
    element = mcp_payload["elements"][0]
    assert element["suggested_actions"] == ["tap"]
    assert element["intent_label"] == "打开通用"
    assert element["preferred_tap_point"] == [70, 40]
    assert element["whitebox_hint"] == {"vc": "SettingsVC"}


@pytest.mark.smoke
def test_observation_payload_field_inventory_matches_dataclasses(tmp_path):
    """Adding a field to the facade observation types without serializing it
    (or consciously excluding it here) must fail this test, not drift silently."""
    payload = observation_payload(_rich_observation(tmp_path / "obs-run"))

    summary_fields = {f.name for f in dataclasses.fields(ObservationSummary)}
    # source_shape / projection are frame-geometry debug fields that neither
    # wire serializer has ever emitted; keep them off the wire deliberately.
    off_wire = {"source_shape", "projection"}
    assert set(payload) == summary_fields - off_wire

    element_fields = {f.name for f in dataclasses.fields(ObservationElement)}
    expected_element_keys = (element_fields - {"element_id"}) | {"id"}
    assert set(payload["elements"][0]) == expected_element_keys

    box_fields = {f.name for f in dataclasses.fields(ElementBox)}
    assert set(payload["elements"][0]["box"]) == box_fields
