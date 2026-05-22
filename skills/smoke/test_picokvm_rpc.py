from __future__ import annotations

import json

import httpx
import pytest

from glassbox.effectors.picokvm.config import PicoKVMEffectorConfig
from glassbox.effectors.picokvm.rpc import (
    PicoKVMRpcClient,
    PicoKVMRpcError,
    PicoKVMRpcUnsupportedError,
)


def _client(handler):
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    cfg = PicoKVMEffectorConfig(_env_file=None, base_url="http://picokvm.test", retries=0)
    return PicoKVMRpcClient(cfg, client=http)


@pytest.mark.smoke
def test_picokvm_rpc_sends_jsonrpc_envelope_and_accepts_null_result():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Session-ID"] == "codex-glassbox"
        body = json.loads(request.content.decode())
        seen.append(body)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": None})

    rpc = _client(handler)
    response = rpc.call("wheelReport", {"wheelY": -1})

    assert response.id == 1
    assert seen == [{
        "jsonrpc": "2.0",
        "method": "wheelReport",
        "params": {"wheelY": -1},
        "id": 1,
    }]


@pytest.mark.smoke
def test_picokvm_rpc_accepts_frontend_combined_response_envelope():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "response": {"jsonrpc": "2.0", "id": body["id"], "result": "configured"},
                "event": {"method": "noop", "params": {}},
            },
        )

    rpc = _client(handler)
    response = rpc.call("getUSBState", {})

    assert response.id == 1
    assert response.result == "configured"


@pytest.mark.smoke
def test_picokvm_rpc_jsonrpc_error_is_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "error": {"message": "bad"}})

    rpc = _client(handler)

    with pytest.raises(PicoKVMRpcError, match="JSON-RPC error"):
        rpc.call("keyboardReport", {"modifier": 0, "keys": []})


@pytest.mark.smoke
def test_picokvm_rpc_4xx_is_typed_unsupported_failure():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "missing"})

    rpc = _client(handler)

    with pytest.raises(PicoKVMRpcUnsupportedError, match="unsupported or unauthorized: HTTP 404"):
        rpc.call("missingMethod", {})


@pytest.mark.smoke
def test_picokvm_rpc_refreshes_invalidated_session_id():
    seen_sessions = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        seen_sessions.append(request.headers["X-Session-ID"])
        if len(seen_sessions) == 1:
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "error": {"code": -32001, "message": "Session invalidated"},
                },
            )
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": "unit-device"})

    rpc = _client(handler)
    response = rpc.call("getDeviceID")

    assert response.result == "unit-device"
    assert seen_sessions[0] == "codex-glassbox"
    assert seen_sessions[1].startswith("codex-glassbox-")
    assert seen_sessions[1] != seen_sessions[0]
