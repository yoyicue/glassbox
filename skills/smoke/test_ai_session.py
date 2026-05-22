from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from glassbox.ai import (
    ActionOutcome,
    ElementBox,
    ObservationElement,
    ObservationSummary,
    RunArtifacts,
)
from glassbox.ai_session import AISessionService, serve_jsonl


@dataclass
class FakeSessionPhone:
    run_id: str = "run-session"
    run_dir: Path = Path("run-session")
    observes: int = 0

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def observe(self):
        self.observes += 1
        return ObservationSummary(
            summary=f"screen {self.observes}",
            page_id="page",
            scene_type="fake",
            visible_texts=("设置",),
            actions=("tap",),
            can_scroll=True,
            screenshot_path=self.run_dir / "frames" / "one.png",
            scene_path=self.run_dir / "scenes" / "one.json",
            event_seq=self.observes,
            elements=(
                ObservationElement(
                    element_id=1,
                    type="button",
                    text="设置",
                    confidence=0.9,
                    box=ElementBox(x=1, y=2, w=3, h=4, center=(2, 4)),
                ),
            ),
            viewport_size=(80, 40),
        )

    def tap_xy(self, x, y):
        return ActionOutcome(
            ok=True,
            transport_ok=True,
            semantic_status="succeeded",
            action="tap_xy",
            target=f"{x},{y}",
            reason=None,
            artifact_path=None,
        )

    def save_report(self):
        return RunArtifacts(
            run_id=self.run_id,
            run_name="session",
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
def test_ai_session_reuses_one_open_phone_runtime():
    opened: list[FakeSessionPhone] = []

    def open_phone_fn(**_kwargs):
        phone = FakeSessionPhone()
        opened.append(phone)
        return phone

    service = AISessionService(open_phone_fn=open_phone_fn)

    first = service.handle({"command": "observe"})
    second = service.handle({"command": "tap_xy", "x": 10, "y": 20})
    third = service.handle({"command": "save_report"})
    closed = service.handle({"command": "close"})

    assert len(opened) == 1
    assert first["observation"]["elements"][0]["box"]["center"] == [2, 4]
    assert second["outcome"]["semantic_status"] == "succeeded"
    assert third["artifacts"]["run_id"] == "run-session"
    assert closed["ok"] is True


@pytest.mark.smoke
def test_ai_session_jsonl_protocol_reuses_runtime():
    opened = 0

    def open_phone_fn(**_kwargs):
        nonlocal opened
        opened += 1
        return FakeSessionPhone()

    service = AISessionService(open_phone_fn=open_phone_fn)
    input_stream = io.StringIO(
        json.dumps({"command": "observe"}) + "\n"
        + json.dumps({"command": "observe"}) + "\n"
        + json.dumps({"command": "close"}) + "\n"
    )
    output_stream = io.StringIO()

    serve_jsonl(service, input_stream=input_stream, output_stream=output_stream)

    rows = [json.loads(line) for line in output_stream.getvalue().splitlines()]
    assert opened == 1
    assert [row["ok"] for row in rows] == [True, True, True]
    assert rows[1]["result"]["observation"]["event_seq"] == 2
