"""Risk policy for computer-use actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


@dataclass(frozen=True)
class RiskDecision:
    level: str
    approval_required: bool
    allowed: bool = True
    reason: str = ""
    source: str = "policy"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "approval_required": self.approval_required,
            "allowed": self.allowed,
            "reason": self.reason,
            "source": self.source,
            "metadata": dict(self.metadata),
        }


class RiskPolicy:
    """Conservative policy owner.

    Agent-supplied risk metadata may raise risk but never lower the effective
    policy result.
    """

    _BASE: ClassVar[dict[str, str]] = {
        "tap": "low",
        "long_press": "low",
        "double_tap": "low",
        "swipe": "low",
        "drag": "low",
        "scroll": "low",
        "scroll_wheel": "low",
        "home": "medium",
        "recents": "medium",
        "control_center": "medium",
        "notification_center": "medium",
        "back_gesture": "low",
        "key": "medium",
        "type": "medium",
        "paste": "medium",
        "set_clipboard": "medium",
    }

    _HIGH_TARGETS: ClassVar[tuple[str, ...]] = (
        "wi-fi",
        "wifi",
        "蓝牙",
        "bluetooth",
        "蜂窝",
        "cellular",
        "vpn",
        "定位",
        "location",
        "密码",
        "password",
        "支付",
        "payment",
        "删除",
        "delete",
        "发送",
        "send",
    )

    def __init__(self, *, guarded: bool = False):
        self.guarded = guarded

    def evaluate(self, op: str, metadata: dict[str, Any] | None = None) -> RiskDecision:
        metadata = metadata or {}
        base = self._BASE.get(op, "medium")
        target_text = " ".join(self._iter_text_values(metadata)).lower()
        if any(marker in target_text for marker in self._HIGH_TARGETS):
            base = self._max(base, "high")
        requested = metadata.get("risk_level")
        if isinstance(requested, str) and requested in _RANK:
            base = self._max(base, requested)
        approval_required = _RANK[base] >= _RANK["high"]
        allowed = not (self.guarded and approval_required and not metadata.get("approved"))
        reason = "approval required" if approval_required else "allowed by default policy"
        if not allowed:
            reason = "blocked by guarded policy: approval required"
        return RiskDecision(
            level=base,
            approval_required=approval_required,
            allowed=allowed,
            reason=reason,
            metadata={"op": op},
        )

    @staticmethod
    def _max(a: str, b: str) -> str:
        return a if _RANK[a] >= _RANK[b] else b

    @classmethod
    def _iter_text_values(cls, value: Any):
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                yield stripped
            return
        if isinstance(value, dict):
            for item in value.values():
                yield from cls._iter_text_values(item)
            return
        if isinstance(value, list | tuple | set | frozenset):
            for item in value:
                yield from cls._iter_text_values(item)
