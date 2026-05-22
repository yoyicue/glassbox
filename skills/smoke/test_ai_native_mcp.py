from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from glassbox.ai import ElementBox, ObservationElement, ObservationSummary, RunArtifacts
from glassbox.mcp.server import HarnessMCPService

AUTH = {"auth_token": "secret", "session_id": "sess-a", "client_id": "client-a"}


@dataclass
class FakeAIPhone:
    run_id: str = "fake-run"

    def __post_init__(self):
        self.run_dir = Path(self.run_id)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def observe(self):
        scene_path = self.run_dir / "scenes" / "scn_000000.json"
        scene_path.parent.mkdir(parents=True, exist_ok=True)
        scene_path.write_text('{"texts":["设置"]}\n', encoding="utf-8")
        return ObservationSummary(
            summary="settings root",
            page_id="settings/root",
            scene_type="settings",
            visible_texts=("设置",),
            actions=("scroll",),
            can_scroll=True,
            screenshot_path=None,
            scene_path=scene_path,
            event_seq=1,
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

    def explore(self, goal, *, max_steps=12):
        self.observe()
        artifact = self.run_dir / "exploration" / "trail_000.json"
        artifact.parent.mkdir(exist_ok=True)
        artifact.write_text('{"success": true}\n', encoding="utf-8")

        class Trail:
            success = True
            matched_path = ("visible:" + goal,)
            artifact_path = artifact

            @staticmethod
            def summary():
                return "success"

        return Trail()

    def save_path_as(self, name):
        path = self.run_dir / "paths" / f"{name}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")

        class Artifact:
            pass

        artifact = Artifact()
        artifact.path = path
        return artifact

    def save_report(self):
        self.run_dir.mkdir(parents=True, exist_ok=True)
        report = self.run_dir / "report.md"
        manifest = self.run_dir / "manifest.json"
        report.write_text("# report\n", encoding="utf-8")
        manifest.write_text('{"artifact_schema_version":1}\n', encoding="utf-8")
        return RunArtifacts(
            run_id=self.run_id,
            run_name="fake",
            run_dir=self.run_dir,
            manifest_path=manifest,
            report_path=report,
            failure_path=None,
            latest_scene_path=None,
            latest_screenshot_path=None,
            artifact_schema_version=1,
            ai_api_version="ai-api-v1",
        )


def _service(tmp_path, *, open_phone_fn=None, allow_debug_tools=False, allow_run_script=False):
    def default_open_phone(**_kwargs):
        phone = FakeAIPhone("fake-run")
        phone.run_dir = tmp_path / phone.run_id
        return phone

    return HarnessMCPService(
        artifact_root=tmp_path,
        auth_token="secret",
        allow_debug_tools=allow_debug_tools,
        allow_run_script=allow_run_script,
        open_phone_fn=open_phone_fn or default_open_phone,
    )


def _call(service, name, **kwargs):
    return service.call_tool({"name": name, "arguments": {**AUTH, **kwargs}})


def _content(result):
    return json.loads(result["content"][0]["text"])


@pytest.mark.smoke
def test_mcp_jsonrpc_initialize_and_tool_search_require_auth(tmp_path):
    service = _service(tmp_path)

    init = service.handle_jsonrpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert init["result"]["serverInfo"]["name"] == "glassbox-ai-native"

    bad = service.handle_jsonrpc({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "tool_search", "arguments": {**AUTH, "auth_token": "bad", "query": "artifact"}},
    })
    assert bad["error"]["code"] == -32001

    good = _content(_call(service, "tool_search", query="artifact"))
    assert any(tool["name"] == "get_artifact" for tool in good["tools"])


@pytest.mark.smoke
def test_mcp_observe_registers_session_owned_run_and_artifact_read(tmp_path):
    service = _service(tmp_path)

    observed = _content(_call(service, "observe_summary"))
    assert observed["summary"] == "settings root"
    assert observed["coordinate_space"] == "frame_px"
    assert observed["elements"][0]["text"] == "设置"
    run_id = observed["run_id"]

    runs = _content(_call(service, "list_runs"))
    assert [run["run_id"] for run in runs["runs"]] == [run_id]

    artifact = _content(_call(service, "get_artifact", run_id=run_id, path="report.md"))
    assert artifact["text"].startswith("# report")
    assert "artifact.read" in service.audit_path.read_text(encoding="utf-8")


@pytest.mark.smoke
def test_mcp_artifact_access_rejects_escape_hidden_and_other_session(tmp_path):
    service = _service(tmp_path)
    observed = _content(_call(service, "observe_summary"))
    run_id = observed["run_id"]

    with pytest.raises(Exception, match="cannot contain"):
        _call(service, "get_artifact", run_id=run_id, path="../secret")
    hidden = tmp_path / run_id / ".hidden"
    hidden.write_text("secret", encoding="utf-8")
    with pytest.raises(Exception, match="hidden"):
        _call(service, "get_artifact", run_id=run_id, path=".hidden")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = tmp_path / run_id / "link.txt"
    link.symlink_to(outside)
    with pytest.raises(Exception, match="symlink"):
        _call(service, "get_artifact", run_id=run_id, path="link.txt")
    with pytest.raises(Exception, match="does not own"):
        service.call_tool({
            "name": "get_artifact",
            "arguments": {
                "auth_token": "secret",
                "session_id": "sess-b",
                "client_id": "client-b",
                "run_id": run_id,
                "path": "report.md",
            },
        })


@pytest.mark.smoke
def test_mcp_run_script_uses_child_process_and_persists_script(tmp_path):
    service = _service(tmp_path, allow_run_script=True)

    result = _content(_call(service, "run_script", source="print('hello from child')", timeout_s=5))

    assert result["ok"] is True
    assert result["stdout"].strip() == "hello from child"
    run_dir = tmp_path / result["run_id"]
    assert (run_dir / result["script_path"]).exists()
    assert (run_dir / "mcp_result.json").exists()
    assert "script.started" in service.audit_path.read_text(encoding="utf-8")


@pytest.mark.smoke
def test_mcp_run_script_is_disabled_by_default(tmp_path):
    service = _service(tmp_path)

    with pytest.raises(Exception, match="disabled by default"):
        _call(service, "run_script", source="print('nope')", timeout_s=5)


@pytest.mark.smoke
def test_mcp_get_artifact_binary_requires_debug_capability(tmp_path):
    service = _service(tmp_path, allow_run_script=True)
    result = _content(_call(service, "run_script", source="from pathlib import Path\nPath('x').write_text('ok')"))
    run_id = result["run_id"]
    binary = tmp_path / run_id / "blob.bin"
    binary.write_bytes(b"\x00\x01")

    with pytest.raises(Exception, match="debug capability"):
        _call(service, "get_artifact", run_id=run_id, path="blob.bin", include_binary=True)

    debug_service = _service(tmp_path, allow_debug_tools=True)
    debug_service.runs = service.runs
    payload = _content(_call(debug_service, "get_artifact", run_id=run_id, path="blob.bin", include_binary=True))
    assert payload["base64"] == "AAE="


@pytest.mark.smoke
def test_mcp_execute_task_uses_registered_source_not_user_source(tmp_path):
    service = _service(tmp_path)
    service.tasks["unit_echo"] = ("Unit echo task.", "print('registered task')")

    result = _content(_call(service, "execute_task", task_id="unit_echo", timeout_s=5, source="print('ignored')"))

    assert result["task_id"] == "unit_echo"
    assert result["ok"] is True
    assert result["stdout"].strip() == "registered task"
