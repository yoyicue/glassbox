"""Neutral PicoKVM video-stream configuration.

This module intentionally lives under perception so the frame-source layer does
not depend on the PicoKVM effector package. The effector config remains usable
as a structural superset when backend glue wants one shared env-backed object.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class PicoKVMVideoSettings(Protocol):
    base_url: str
    stream_path: str
    robust_capture: bool
    snapshot_reconnect_attempts: int


class PicoKVMVideoConfig(BaseSettings):
    """PicoKVM HTTP video stream settings.

    Uses the same ``GLASSBOX_PICOKVM_`` prefix as the PicoKVM effector so a
    standalone frame source and a full PicoKVM backend read the same stream env.
    """

    model_config = SettingsConfigDict(
        env_prefix="GLASSBOX_PICOKVM_",
        env_file=None,
        extra="ignore",
    )

    base_url: str = "http://picokvm.local"
    stream_path: str = "/video/stream"
    robust_capture: bool = False
    snapshot_reconnect_attempts: int = 4

    @field_validator("base_url")
    @classmethod
    def _strip_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value:
            raise ValueError("GLASSBOX_PICOKVM_BASE_URL must not be empty")
        return value

    @field_validator("stream_path")
    @classmethod
    def _normalize_stream_path(cls, value: str) -> str:
        value = value.strip() or "/video/stream"
        return value if value.startswith("/") else f"/{value}"

    @field_validator("snapshot_reconnect_attempts")
    @classmethod
    def _positive_attempts(cls, value: int) -> int:
        if int(value) <= 0:
            raise ValueError("snapshot_reconnect_attempts must be > 0")
        return int(value)
