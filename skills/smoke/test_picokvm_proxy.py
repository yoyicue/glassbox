"""Proxy-bypass policy for the PicoKVM rig clients.

Regression guard for the 2026-06-13 incident: a host-level
http_proxy/all_proxy that cannot route to the LAN silently broke every rig
connection (FFmpeg stream open + httpx RPC/diagnose) and looked like a hardware
wedge. The fix bypasses the proxy when the rig host is private/loopback.
"""

from __future__ import annotations

import os

import pytest

from glassbox.effectors.picokvm.config import PicoKVMEffectorConfig
from glassbox.effectors.picokvm.rpc import PicoKVMRpcClient
from glassbox.perception.picokvm_proxy import (
    host_from_url,
    host_is_proxy_exempt,
    no_proxy_env,
    should_bypass_proxy,
)
from glassbox.perception.picokvm_source import PicoKVMFrameSource

_PRIVATE_HOSTS = [
    "127.0.0.1",
    "127.0.0.5",
    "::1",
    "[::1]",
    "localhost",
    "LocalHost",
    "192.168.20.185",  # the actual incident rig
    "10.0.0.1",
    "10.255.255.255",
    "172.16.0.1",
    "172.31.255.255",
    "169.254.10.20",  # link-local
    "fe80::1",
    "fe80::1%en0",  # zone id
    "100.64.0.1",  # CGNAT
    "100.127.255.255",
    "foo.local",
    "rig.LAN",
    "picokvm.local",  # the default base_url host
]

_PUBLIC_HOSTS = [
    "8.8.8.8",
    "1.1.1.1",
    "example.com",
    "rig",  # bare hostname is NOT assumed private
    "172.32.0.1",  # just outside RFC1918 172.16/12
    "100.128.0.1",  # just outside CGNAT 100.64/10
    "11.0.0.1",  # just outside 10/8
    "",
    None,
]


@pytest.mark.smoke
@pytest.mark.parametrize("host", _PRIVATE_HOSTS)
def test_private_hosts_are_proxy_exempt(host):
    assert host_is_proxy_exempt(host) is True


@pytest.mark.smoke
@pytest.mark.parametrize("host", _PUBLIC_HOSTS)
def test_public_hosts_are_not_proxy_exempt(host):
    assert host_is_proxy_exempt(host) is False


@pytest.mark.smoke
def test_host_from_url_handles_scheme_and_bare_hostport():
    assert host_from_url("http://192.168.20.185/video/stream") == "192.168.20.185"
    assert host_from_url("192.168.1.5:8080") == "192.168.1.5"
    assert host_from_url("http://picokvm.local") == "picokvm.local"
    assert host_from_url(None) is None


@pytest.mark.smoke
def test_should_bypass_proxy_auto_uses_host_predicate():
    assert should_bypass_proxy("http://192.168.20.185/api/rpc", mode="auto") is True
    assert should_bypass_proxy("http://example.com/api/rpc", mode="auto") is False


@pytest.mark.smoke
def test_should_bypass_proxy_force_on_off_override_host():
    # force-off keeps the proxy even for a LAN rig (genuinely-proxied remote rig)
    assert should_bypass_proxy("http://192.168.20.185", mode="off") is False
    # force-on bypasses even for a public host
    assert should_bypass_proxy("http://example.com", mode="on") is True


@pytest.mark.smoke
def test_should_bypass_proxy_reads_env_when_mode_unset(monkeypatch):
    monkeypatch.delenv("GLASSBOX_PICOKVM_BYPASS_PROXY", raising=False)
    assert should_bypass_proxy("http://192.168.20.185") is True  # default auto
    monkeypatch.setenv("GLASSBOX_PICOKVM_BYPASS_PROXY", "off")
    assert should_bypass_proxy("http://192.168.20.185") is False
    monkeypatch.setenv("GLASSBOX_PICOKVM_BYPASS_PROXY", "on")
    assert should_bypass_proxy("http://example.com") is True


# --- env-clearing context manager -----------------------------------------

_ALL_PROXY_VARS = (
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "ftp_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "FTP_PROXY",
)


@pytest.mark.smoke
def test_no_proxy_env_clears_then_restores_exactly(monkeypatch):
    # Start from a clean slate, then set a mix of present / absent vars.
    for name in _ALL_PROXY_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:7890")
    monkeypatch.setenv("all_proxy", "socks5://127.0.0.1:7890")
    monkeypatch.setenv("HTTPS_PROXY", "")  # present but empty (must be restored as "")
    # https_proxy / others intentionally absent.

    before = {n: os.environ.get(n, "<<absent>>") for n in _ALL_PROXY_VARS}

    with no_proxy_env(True):
        # Every proxy var is cleared inside the block.
        for name in _ALL_PROXY_VARS:
            assert name not in os.environ

    # Restored byte-for-byte: present vars back to old values (incl. empty
    # string), absent vars stay absent.
    after = {n: os.environ.get(n, "<<absent>>") for n in _ALL_PROXY_VARS}
    assert after == before


@pytest.mark.smoke
def test_no_proxy_env_restores_on_exception(monkeypatch):
    for name in _ALL_PROXY_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:7890")
    monkeypatch.delenv("https_proxy", raising=False)

    with pytest.raises(ValueError), no_proxy_env(True):
        assert "http_proxy" not in os.environ
        raise ValueError("boom")

    assert os.environ["http_proxy"] == "http://127.0.0.1:7890"
    assert "https_proxy" not in os.environ


@pytest.mark.smoke
def test_no_proxy_env_inactive_is_noop(monkeypatch):
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:7890")
    with no_proxy_env(False):
        # active=False leaves the env untouched (caller decided not to bypass).
        assert os.environ["http_proxy"] == "http://127.0.0.1:7890"
    assert os.environ["http_proxy"] == "http://127.0.0.1:7890"


# --- frame source wiring ---------------------------------------------------


class _FakeCapture:
    def isOpened(self):
        return True

    def release(self):
        pass


@pytest.mark.smoke
def test_frame_source_clears_proxy_env_during_private_open(monkeypatch):
    """The dominant incident path: FFmpeg open of a private rig must run with
    proxy env cleared, then restored."""
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:7890")
    monkeypatch.setenv("all_proxy", "socks5://127.0.0.1:7890")

    cfg = PicoKVMEffectorConfig(_env_file=None, base_url="http://192.168.20.185")
    seen_env = {}

    def factory(_url):
        # Lowercase env names are deliberate (FFmpeg/libcurl read them).
        seen_env["http_proxy"] = os.environ.get("http_proxy", "<<absent>>")
        seen_env["all_proxy"] = os.environ.get("all_proxy", "<<absent>>")  # noqa: SIM112
        return _FakeCapture()

    source = PicoKVMFrameSource(config=cfg, capture_factory=factory)
    assert source._bypass_proxy is True
    source.open()

    # Inside the VideoCapture open, proxy env was cleared...
    assert seen_env["http_proxy"] == "<<absent>>"
    assert seen_env["all_proxy"] == "<<absent>>"
    # ...and restored afterward. Lowercase names are deliberate: FFmpeg/libcurl
    # consult the lowercase spellings, which is exactly the incident path.
    assert os.environ["http_proxy"] == "http://127.0.0.1:7890"
    assert os.environ["all_proxy"] == "socks5://127.0.0.1:7890"  # noqa: SIM112


@pytest.mark.smoke
def test_frame_source_leaves_proxy_env_for_public_open(monkeypatch):
    """A genuinely-remote (public) rig keeps the proxy in the FFmpeg path."""
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:7890")

    cfg = PicoKVMEffectorConfig(_env_file=None, base_url="http://rig.example.com")
    seen = {}

    def factory(_url):
        seen["http_proxy"] = os.environ.get("http_proxy", "<<absent>>")
        return _FakeCapture()

    source = PicoKVMFrameSource(config=cfg, capture_factory=factory)
    assert source._bypass_proxy is False
    source.open()

    # Proxy env was NOT cleared for a public host.
    assert seen["http_proxy"] == "http://127.0.0.1:7890"


@pytest.mark.smoke
def test_frame_source_bypass_force_off_keeps_proxy_for_private(monkeypatch):
    monkeypatch.setenv("GLASSBOX_PICOKVM_BYPASS_PROXY", "off")
    cfg = PicoKVMEffectorConfig(_env_file=None, base_url="http://192.168.20.185")
    source = PicoKVMFrameSource(config=cfg, capture_factory=lambda _u: _FakeCapture())
    assert source._bypass_proxy is False


# --- httpx RPC client wiring -----------------------------------------------


@pytest.mark.smoke
def test_rpc_client_disables_proxy_for_private_host_even_with_trust_env():
    """An operator who opts trust_env on (for a remote rig) must NOT route a
    private rig through the proxy: trust_env is forced off there."""
    cfg = PicoKVMEffectorConfig(_env_file=None, base_url="http://192.168.20.185", trust_env=True)
    rpc = PicoKVMRpcClient(cfg)
    try:
        assert rpc._trust_env is False
        assert rpc._client.trust_env is False
    finally:
        rpc.close()


@pytest.mark.smoke
def test_rpc_client_respects_trust_env_for_public_host():
    """For a genuinely-remote (public) rig with trust_env on, the proxy is NOT
    forced off — the operator's proxy choice is honored."""
    cfg = PicoKVMEffectorConfig(_env_file=None, base_url="http://rig.example.com", trust_env=True)
    rpc = PicoKVMRpcClient(cfg)
    try:
        assert rpc._trust_env is True
        assert rpc._client.trust_env is True
    finally:
        rpc.close()


@pytest.mark.smoke
def test_rpc_client_default_ignores_proxy():
    """Default config (trust_env False) ignores env proxies regardless of host —
    byte-identical to the pre-fix default, just now host-aware on top."""
    cfg = PicoKVMEffectorConfig(_env_file=None, base_url="http://picokvm.local")
    rpc = PicoKVMRpcClient(cfg)
    try:
        assert rpc._trust_env is False
        assert rpc._client.trust_env is False
    finally:
        rpc.close()


@pytest.mark.smoke
def test_rpc_client_force_off_lets_private_host_use_proxy(monkeypatch):
    """GLASSBOX_PICOKVM_BYPASS_PROXY=off makes even a private host honor
    trust_env (escape hatch for an intentionally-proxied LAN setup)."""
    monkeypatch.setenv("GLASSBOX_PICOKVM_BYPASS_PROXY", "off")
    cfg = PicoKVMEffectorConfig(_env_file=None, base_url="http://192.168.20.185", trust_env=True)
    rpc = PicoKVMRpcClient(cfg)
    try:
        assert rpc._trust_env is True
        assert rpc._client.trust_env is True
    finally:
        rpc.close()
