"""Proxy-bypass policy for PicoKVM rig clients.

The 2026-06-13 incident: a dev host had ``http_proxy``/``https_proxy``/
``all_proxy`` exported by a VPN/proxy app pointing at a loopback SOCKS/HTTP
proxy that **cannot route to RFC1918**. Every glassbox connection to the LAN
rig — the OpenCV/FFmpeg ``GET /video/stream`` and the httpx RPC/diagnose API —
honored those env vars and was routed through the proxy, which silently failed
to reach ``192.168.x.x``. The symptom ("video stream did not open after 4
attempts") was indistinguishable from a hardware wedge and cost hours.

A proxy that can't route to private address space should never be in the path
for a LAN rig. This module centralizes:

- :func:`host_is_proxy_exempt` — the private-host predicate (loopback / RFC1918
  / link-local / CGNAT / ``.local``/``.lan``).
- :func:`should_bypass_proxy` — applies that predicate under the
  ``GLASSBOX_PICOKVM_BYPASS_PROXY`` override (``auto`` / ``on`` / ``off``).
- :func:`no_proxy_env` — a save/restore context manager that strips proxy env
  vars for the duration of a block (used to wrap the FFmpeg capture open, whose
  own ``no_proxy`` support is unreliable).

It is a leaf module: it imports only the stdlib so both the perception frame
source and the effector RPC client can use it without a layering edge.
"""

from __future__ import annotations

import contextlib
import ipaddress
import os
from collections.abc import Iterator
from urllib.parse import urlparse

# The proxy env vars FFmpeg / requests / httpx / urllib consult. Both the
# lower- and upper-case spellings are honored by libcurl/FFmpeg, so we must
# clear (and later restore) both.
_PROXY_ENV_VARS = (
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "ftp_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "FTP_PROXY",
)

# Hostname suffixes that name a LAN host even though they are not parseable as
# an IP literal (mDNS / common home-router search domains).
_PRIVATE_HOST_SUFFIXES = (".local", ".lan")

# 100.64.0.0/10 — RFC 6598 carrier-grade NAT / Tailscale-style overlay space.
_CGNAT_NET = ipaddress.ip_network("100.64.0.0/10")


def host_is_proxy_exempt(host: str | None) -> bool:
    """True when *host* is a private / loopback / link-local address.

    Such a host is unreachable through a typical egress proxy, so the proxy must
    be bypassed. Exempt:

    - loopback: ``127.0.0.0/8``, ``::1``, the literal ``localhost``
    - RFC1918 private: ``10/8``, ``172.16/12``, ``192.168/16``
    - link-local: ``169.254/16`` (IPv4), ``fe80::/10`` (IPv6)
    - CGNAT: ``100.64.0.0/10``
    - ``*.local`` / ``*.lan`` hostnames (unparseable as IPs but LAN by name)

    NOT exempt (the proxy is respected): a bare hostname like ``rig`` or a public
    name/IP like ``example.com`` / ``8.8.8.8``.
    """
    if not host:
        return False
    host = host.strip()
    if not host:
        return False

    lowered = host.lower()
    if lowered == "localhost":
        return True
    if lowered.endswith(_PRIVATE_HOST_SUFFIXES):
        return True

    # ipaddress rejects a bracketed IPv6 literal ("[::1]") and zone ids
    # ("fe80::1%en0"); normalize both before parsing.
    candidate = host
    if candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1]
    candidate = candidate.split("%", 1)[0]
    try:
        ip = ipaddress.ip_address(candidate)
    except ValueError:
        # A bare hostname (no dots, not *.local/*.lan) is NOT assumed private —
        # respect the proxy there.
        return False

    if ip.is_loopback or ip.is_private or ip.is_link_local:
        return True
    # ``is_private`` already covers CGNAT on modern stdlib, but check it
    # explicitly so the behavior is independent of the Python patch level.
    return ip.version == 4 and ip in _CGNAT_NET


def host_from_url(url: str | None) -> str | None:
    """Extract the hostname from a base URL or ``host[:port]`` string."""
    if not url:
        return None
    parsed = urlparse(url if "://" in url else f"http://{url}")
    return parsed.hostname


def should_bypass_proxy(url: str | None, *, mode: str | None = None) -> bool:
    """Decide whether to bypass the env-configured proxy for *url*.

    ``mode`` (or ``GLASSBOX_PICOKVM_BYPASS_PROXY`` when ``mode`` is None):

    - ``"auto"`` (default) — bypass only when the host is private/loopback
      (:func:`host_is_proxy_exempt`). This is the safe default that fixed the
      incident without breaking a genuinely-remote proxied rig.
    - ``"on"`` / ``"true"`` / ``"1"`` — always bypass.
    - ``"off"`` / ``"false"`` / ``"0"`` — never bypass (force the proxy back into
      the path even for a LAN rig).
    """
    resolved = mode if mode is not None else os.environ.get("GLASSBOX_PICOKVM_BYPASS_PROXY", "auto")
    resolved = (resolved or "auto").strip().lower()
    if resolved in ("on", "true", "1", "yes", "force"):
        return True
    if resolved in ("off", "false", "0", "no", "never"):
        return False
    # "auto" and any unrecognized value fall back to host-based detection.
    return host_is_proxy_exempt(host_from_url(url))


@contextlib.contextmanager
def no_proxy_env(active: bool = True) -> Iterator[None]:
    """Temporarily remove proxy env vars, restoring them exactly on exit.

    Used to wrap a single ``cv2.VideoCapture`` open: FFmpeg honors
    ``http_proxy``/``all_proxy`` but its ``no_proxy`` handling is unreliable, so
    the robust fix is to clear the proxy vars for just the duration of the open.

    Restoration is exact and exception-safe: a var that was **absent** stays
    absent, and a var that was **present** is restored to its exact old value,
    even if the body raises.

    Thread-safety: this mutates the process-global ``os.environ``, so it is NOT
    safe to run two of these concurrently. In glassbox a frame-source open is not
    concurrent — ``PicoKVMFrameSource`` opens its single capture serially from
    one Phone (``open()``/``snapshot()``/``fresh_snapshot()`` all run on the
    caller's thread; the only lock in the rig path is httpx's per-call lock in
    :class:`PicoKVMRpcClient`, a separate client). The window is also tight (just
    the ``VideoCapture(...)`` call), so the global mutation is bounded.

    When ``active`` is False the context manager is a no-op (so callers can guard
    it with the bypass decision without an ``if``).
    """
    if not active:
        yield
        return
    # Sentinel distinguishes "var was absent" from "var was empty string".
    _ABSENT = object()
    saved: dict[str, object] = {name: os.environ.get(name, _ABSENT) for name in _PROXY_ENV_VARS}
    for name in _PROXY_ENV_VARS:
        os.environ.pop(name, None)
    try:
        yield
    finally:
        for name, old in saved.items():
            if old is _ABSENT:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old  # type: ignore[assignment]
