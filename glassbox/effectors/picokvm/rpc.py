"""JSON-RPC client for Luckfox PicoKVM."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from glassbox.effectors.picokvm.config import PicoKVMEffectorConfig
from glassbox.perception.picokvm_proxy import should_bypass_proxy


class PicoKVMRpcError(RuntimeError):
    """PicoKVM RPC failed or returned a JSON-RPC error."""


class PicoKVMRpcUnsupportedError(PicoKVMRpcError):
    """PicoKVM RPC endpoint is missing or unavailable on this firmware."""


@dataclass(frozen=True)
class PicoKVMRpcResponse:
    id: int
    result: Any = None


class PicoKVMRpcClient:
    """Small synchronous JSON-RPC client.

    HID RPCs in kvm_app are Go ``func(...) error`` methods, so successful
    responses often omit ``result`` or set it to ``null``. That is success.
    """

    def __init__(
        self,
        config: PicoKVMEffectorConfig | None = None,
        *,
        client: httpx.Client | None = None,
    ):
        self.config = config or PicoKVMEffectorConfig()
        timeout = httpx.Timeout(
            timeout=self.config.request_timeout_s,
            connect=self.config.connect_timeout_s,
        )
        # 2026-06-13 incident: a host-level proxy that cannot route to the LAN
        # made the RPC/diagnose API unreachable. httpx honors env proxies only
        # when trust_env is True; force it False (proxy bypassed) whenever the
        # rig host is private/loopback, so a LAN rig never goes through a proxy
        # even if the operator opts trust_env on for a genuinely-remote rig.
        # GLASSBOX_PICOKVM_BYPASS_PROXY (auto / on / off) overrides the host test.
        trust_env = self.config.trust_env and not should_bypass_proxy(self.config.base_url)
        self._client = client or httpx.Client(timeout=timeout, trust_env=trust_env)
        self._trust_env = trust_env
        self._owns_client = client is None
        self._seq = 0
        self._lock = threading.Lock()
        self._auth_token: str | None = None
        self._session_id = self._new_session_id()

    @property
    def rpc_url(self) -> str:
        return f"{self.config.base_url}/api/rpc"

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def login(self) -> None:
        if self.config.auth_mode != "password":
            return
        if not self.config.password:
            raise PicoKVMRpcError("picokvm password auth requires GLASSBOX_PICOKVM_PASSWORD")
        response = self._client.post(
            f"{self.config.base_url}/auth/login-local",
            json={"username": self.config.username, "password": self.config.password},
        )
        if response.status_code >= 400:
            raise PicoKVMRpcError(f"picokvm login failed: HTTP {response.status_code}")
        cookie = response.cookies.get("authToken") or self._client.cookies.get("authToken")
        if not cookie:
            raise PicoKVMRpcError("picokvm login did not return authToken cookie")
        self._auth_token = cookie
        self._client.cookies.set("authToken", cookie)

    def call(self, method: str, params: dict[str, Any] | None = None) -> PicoKVMRpcResponse:
        with self._lock:
            self._seq += 1
            seq = self._seq
            return self._call_with_id(seq, method, params)

    def _call_with_id(
        self,
        seq: int,
        method: str,
        params: dict[str, Any] | None,
    ) -> PicoKVMRpcResponse:
        if self.config.auth_mode == "password" and not self._auth_token:
            self.login()
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
            "id": seq,
        }
        if params is not None:
            payload["params"] = params
        attempts = max(0, int(self.config.retries)) + 1
        session_refresh_used = False
        attempt = 0
        last_exc: Exception | None = None
        while attempt < attempts:
            try:
                response = self._client.post(self.rpc_url, json=payload, headers=self._headers())
                if response.status_code == 401 and self.config.auth_mode == "password" and attempt == 0:
                    self._auth_token = None
                    self.login()
                    response = self._client.post(self.rpc_url, json=payload, headers=self._headers())
                if 400 <= response.status_code < 500:
                    raise PicoKVMRpcUnsupportedError(
                        f"{method} unsupported or unauthorized: HTTP {response.status_code}"
                    )
                if response.status_code >= 500:
                    raise PicoKVMRpcError(f"{method} server error: HTTP {response.status_code}")
                data = response.json()
                if isinstance(data, dict) and isinstance(data.get("response"), dict):
                    data = data["response"]
                if data.get("error"):
                    if self._is_session_invalidated(data["error"]) and not session_refresh_used:
                        session_refresh_used = True
                        attempts += 1
                        self._refresh_session_id()
                        attempt += 1
                        continue
                    raise PicoKVMRpcError(f"{method} JSON-RPC error: {data['error']!r}")
                return PicoKVMRpcResponse(id=int(data.get("id", seq)), result=data.get("result"))
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError, PicoKVMRpcError) as exc:
                last_exc = exc
                if isinstance(exc, PicoKVMRpcUnsupportedError):
                    break
                if attempt + 1 >= attempts:
                    break
            attempt += 1
        if isinstance(last_exc, PicoKVMRpcUnsupportedError):
            raise last_exc
        raise PicoKVMRpcError(f"{method} failed after {attempts} attempt(s): {last_exc}") from last_exc

    def ping(self) -> PicoKVMRpcResponse:
        return self.call("ping")

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._session_id:
            headers["X-Session-ID"] = self._session_id
        return headers

    @staticmethod
    def _is_session_invalidated(error: Any) -> bool:
        if not isinstance(error, dict):
            return False
        message = str(error.get("message") or "")
        return "Session invalidated" in message

    def _refresh_session_id(self) -> None:
        self._session_id = self._new_session_id(refresh=True)

    def _new_session_id(self, *, refresh: bool = False) -> str:
        configured = str(self.config.session_id or "").strip()
        if configured and not refresh:
            return configured
        base = configured or "glassbox"
        return f"{base}-{uuid.uuid4().hex[:8]}"
