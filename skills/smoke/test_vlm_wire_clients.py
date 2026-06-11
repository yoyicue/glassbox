"""Wire-level tests for the billed VLM HTTP clients (vlm_kimi.py).

These cover the transport layer that test_vlm_kimi.py's FakeKimi doubles skip:
``SiliconFlowVLM.chat()`` (stdlib urllib), ``MoonshotAnthropicVLM.chat()``
(anthropic SDK), ``_safe_parse_json`` fallback branches, and the
missing-API-key contract. No network, no API keys: the HTTP layer is
monkeypatched (urllib.request.urlopen) or injected (the anthropic client
object). Real calls are billed — see scripts/probe_kimi_grounding.py.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from glassbox.cognition.vlm_kimi import (
    MS_MODEL,
    SF_MODEL,
    SF_URL,
    MoonshotAnthropicVLM,
    SiliconFlowVLM,
    _safe_parse_json,
)

# ─── _safe_parse_json: one test per branch the code claims to handle ──


@pytest.mark.smoke
def test_safe_parse_json_plain_object():
    assert _safe_parse_json('{"scene_type": "settings"}') == {"scene_type": "settings"}


@pytest.mark.smoke
def test_safe_parse_json_fenced_json_block():
    content = '```json\n{"scene_type": "settings", "elements": []}\n```'
    assert _safe_parse_json(content) == {"scene_type": "settings", "elements": []}


@pytest.mark.smoke
def test_safe_parse_json_object_with_surrounding_prose():
    content = 'Sure, here is the analysis: {"scene_type": "list"} hope that helps.'
    assert _safe_parse_json(content) == {"scene_type": "list"}


@pytest.mark.smoke
def test_safe_parse_json_garbage_without_braces_returns_none():
    assert _safe_parse_json("I could not read the screenshot.") is None


@pytest.mark.smoke
def test_safe_parse_json_braced_but_unparseable_returns_none():
    assert _safe_parse_json("{not valid json}") is None


# ─── SiliconFlowVLM: urllib wire path ─────────────────────────────────


class _FakeHTTPResponse:
    def __init__(self, payload: dict[str, Any]):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _sf_body(content: str) -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        "model": "served-model-name",
    }


@pytest.fixture
def sf_client(monkeypatch) -> SiliconFlowVLM:
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sf-test-key")
    return SiliconFlowVLM()


@pytest.mark.smoke
def test_siliconflow_chat_parses_well_formed_response(monkeypatch, sf_client):
    captured: dict[str, Any] = {}

    def fake_urlopen(req, timeout=None):
        captured["req"] = req
        captured["timeout"] = timeout
        return _FakeHTTPResponse(_sf_body('{"scene_type": "settings"}'))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    resp = sf_client.chat(system="sys", user_text="hello", image=b"\x89PNGfake")

    req = captured["req"]
    assert req.full_url == SF_URL
    assert req.get_method() == "POST"
    assert req.get_header("Authorization") == "Bearer sf-test-key"
    assert captured["timeout"] == 180

    body = json.loads(req.data.decode("utf-8"))
    assert body["model"] == SF_MODEL
    assert body["response_format"] == {"type": "json_object"}  # json_object default True
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    user_content = body["messages"][1]["content"]
    assert user_content[0] == {"type": "text", "text": "hello"}
    assert user_content[1]["image_url"]["url"].startswith("data:image/png;base64,")

    assert resp.raw_content == '{"scene_type": "settings"}'
    assert resp.parsed == {"scene_type": "settings"}
    assert resp.usage["total_tokens"] == 15
    assert resp.model == "served-model-name"
    assert resp.elapsed_ms >= 0


@pytest.mark.smoke
def test_siliconflow_chat_fenced_content_still_parses(monkeypatch, sf_client):
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=None: _FakeHTTPResponse(_sf_body('```json\n{"a": 1}\n```')),
    )
    resp = sf_client.chat(system="s", user_text="u")
    assert resp.parsed == {"a": 1}


@pytest.mark.smoke
def test_siliconflow_chat_unparseable_content_yields_parsed_none(monkeypatch, sf_client):
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=None: _FakeHTTPResponse(_sf_body("no json here")),
    )
    resp = sf_client.chat(system="s", user_text="u")
    assert resp.parsed is None
    assert resp.raw_content == "no json here"


@pytest.mark.smoke
def test_siliconflow_describe_scene_round_trip(monkeypatch, sf_client):
    """The billed describe_scene path: elements go into the prompt, the JSON
    response surfaces as VLMResult.parsed."""
    captured: dict[str, Any] = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeHTTPResponse(
            _sf_body('{"scene_type": "settings", "elements": [{"id": 1, "intent_label": "打开通用"}]}')
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    resp = sf_client.describe_scene(
        frame_image=b"\x89PNGfake",
        elements=[{"id": 1, "text": "通用", "type": "text", "box": [0, 0, 10, 10]}],
    )

    user_text = captured["body"]["messages"][1]["content"][0]["text"]
    assert "id=1" in user_text and "通用" in user_text
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert resp.parsed["scene_type"] == "settings"
    assert resp.parsed["elements"][0]["intent_label"] == "打开通用"


@pytest.mark.smoke
def test_siliconflow_http_error_raises_runtime_error_with_code_and_body(monkeypatch, sf_client):
    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            SF_URL, 429, "Too Many Requests", hdrs=None, fp=io.BytesIO(b'{"error":"rate limited"}')
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match=r"Kimi HTTP 429.*rate limited"):
        sf_client.chat(system="s", user_text="u")


@pytest.mark.smoke
def test_siliconflow_timeout_propagates_unwrapped(monkeypatch, sf_client):
    """Contract: only HTTPError is converted to RuntimeError; a socket timeout
    (URLError) propagates as-is for the caller's except-Exception guards."""

    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(urllib.error.URLError):
        sf_client.chat(system="s", user_text="u")


@pytest.mark.smoke
def test_siliconflow_unexpected_response_structure_raises(monkeypatch, sf_client):
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=None: _FakeHTTPResponse({"detail": "no choices"}),
    )
    with pytest.raises(RuntimeError, match="Unexpected VLM response structure"):
        sf_client.chat(system="s", user_text="u")


@pytest.mark.smoke
def test_siliconflow_missing_api_key_raises_actionable_error(monkeypatch):
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match=r"Missing API key.*SILICONFLOW_API_KEY"):
        SiliconFlowVLM()


# ─── MoonshotAnthropicVLM: anthropic SDK wire path ────────────────────


@dataclass
class _FakeMessages:
    result: Any = None
    exc: Exception | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc is not None:
            raise self.exc
        return self.result


def _ms_message(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking="(reasoning, no .text)"),
            SimpleNamespace(type="text", text=text),
        ],
        usage=SimpleNamespace(input_tokens=7, output_tokens=3),
        model="kimi-served",
    )


def _ms_client(monkeypatch, *, result=None, exc=None) -> tuple[MoonshotAnthropicVLM, _FakeMessages]:
    monkeypatch.setenv("MOONSHOT_API_KEY", "ms-test-key")
    monkeypatch.delenv("KIMI_ANTHROPIC_MODEL", raising=False)
    client = MoonshotAnthropicVLM()
    fake = _FakeMessages(result=result, exc=exc)
    client._client = SimpleNamespace(messages=fake)
    return client, fake


@pytest.mark.smoke
def test_moonshot_chat_parses_well_formed_response(monkeypatch):
    client, fake = _ms_client(monkeypatch, result=_ms_message('{"scene_type": "settings"}'))

    resp = client.chat(system="sys", user_text="hello", image=b"\x89PNGfake")

    call = fake.calls[0]
    assert call["model"] == MS_MODEL
    assert call["system"] == "sys"
    blocks = call["messages"][0]["content"]
    assert blocks[0]["type"] == "image"
    assert blocks[0]["source"]["type"] == "base64"
    assert blocks[0]["source"]["media_type"] == "image/png"
    assert blocks[-1] == {"type": "text", "text": "hello"}

    # non-text blocks are filtered, text blocks joined
    assert resp.raw_content == '{"scene_type": "settings"}'
    assert resp.parsed == {"scene_type": "settings"}
    assert resp.usage == {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}
    assert resp.model == "kimi-served"
    assert resp.elapsed_ms >= 0


@pytest.mark.smoke
def test_moonshot_chat_fenced_content_still_parses(monkeypatch):
    client, _ = _ms_client(monkeypatch, result=_ms_message('```json\n{"a": 1}\n```'))
    assert client.chat(system="s", user_text="u").parsed == {"a": 1}


@pytest.mark.smoke
def test_moonshot_chat_json_object_false_skips_parsing(monkeypatch):
    client, _ = _ms_client(monkeypatch, result=_ms_message('{"a": 1}'))
    resp = client.chat(system="s", user_text="u", json_object=False)
    assert resp.parsed is None
    assert resp.raw_content == '{"a": 1}'


@pytest.mark.smoke
def test_moonshot_sdk_error_wraps_in_runtime_error(monkeypatch):
    """Contract: any SDK failure (HTTP error, timeout, ...) surfaces as one
    RuntimeError carrying the original message."""
    client, _ = _ms_client(monkeypatch, exc=ConnectionError("api timed out"))
    with pytest.raises(RuntimeError, match="MoonshotAnthropicVLM chat failed: api timed out"):
        client.chat(system="s", user_text="u")


@pytest.mark.smoke
def test_moonshot_missing_api_key_raises_actionable_error(monkeypatch):
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match=r"Missing API key.*MOONSHOT_API_KEY"):
        MoonshotAnthropicVLM()


@pytest.mark.smoke
def test_moonshot_model_env_override(monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "ms-test-key")
    monkeypatch.setenv("KIMI_ANTHROPIC_MODEL", "kimi-custom")
    assert MoonshotAnthropicVLM().model == "kimi-custom"
