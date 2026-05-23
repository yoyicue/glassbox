"""glassbox/config.py — centralized configuration

All "environment / hardware" related config is defined in one place,
eliminating hard-coded values scattered across files. The previous
problem: capture card index, HID bridge PID, and controlled-device
resolution were spread across source.py / bridge.py / conftest.py and even
contradicted each other (index 0 vs 1, model 13Pro vs 17PM).

Source precedence (pydantic-settings default):
    explicit constructor args > environment variables > .env file > field defaults

Environment variables use a uniform `GLASSBOX_` prefix: field `hdmi_index` ←
`GLASSBOX_HDMI_INDEX`, `phone_model` ← `GLASSBOX_PHONE_MODEL`, and so on.

Usage:
    from glassbox.config import get_config
    cfg = get_config()
    src = AVFFrameSource(device_index=cfg.hdmi_index)

To override in tests: construct `AgentConfig(hdmi_index=2, ...)` directly,
or use monkeypatch to set environment variables and then call
`get_config.cache_clear()`.

Note: the VLM API key is not here — the key goes through `.env` +
`_require_api_key()` (see vlm_kimi.py); this config file never touches
secrets.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[1]


class AgentConfig(BaseSettings):
    """Agent runtime config. Environment variable prefix GLASSBOX_."""

    model_config = SettingsConfigDict(
        env_prefix="GLASSBOX_",
        env_file=str(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # ─── Capture card (HDMI frame grabbing) ──────────────────────────
    hdmi_index: int = 0
    """AVFoundation device index. A USB HDMI capture card is usually 0; it
    is 1+ only when 0 is taken by the built-in camera. Check with
    `python -m glassbox.demo.list_devices`."""

    hdmi_fps: int = 30
    """Frame rate requested from the capture card. The actual rate depends on the card's capability."""

    no_hdmi: bool = False
    """Explicitly disable HDMI (CI / no-capture-card environment)."""

    frame_dir: str | None = None
    """Point at a png directory → use static images instead of HDMI frame grabbing (hardware-free dev / replay)."""

    auto_recover_capture: bool = False
    """Automatically restart macOS CoreMediaIO camera daemons when the capture
    card appears locked. This can affect other camera clients, so it is opt-in.
    env GLASSBOX_AUTO_RECOVER_CAPTURE=1."""

    # ─── Effector startup ────────────────────────────────────────────
    allow_noop_fallback: bool = False
    """Allow an explicitly configured hardware effector to downgrade to
    NoOpEffector when startup fails. Defaults off so hardware failures are
    visible in production runs."""

    effector_backend: str = Field(
        default="noop",
        validation_alias=AliasChoices("GLASSBOX_EFFECTOR", "AGENT_EFFECTOR", "AGENT_EFFECTOR_BACKEND"),
    )
    """Effector backend selector. GLASSBOX_EFFECTOR is the plugin-facing spelling."""

    wheel_ticks_per_scroll: int = 90
    """Default wheel report count for one semantic wheel scroll."""

    wheel_interval_ms: int = 40
    """Delay between synthetic mouse-wheel reports. env GLASSBOX_WHEEL_INTERVAL_MS."""

    wheel_invert: bool = False
    """Flip vertical wheel direction for effectors that do not declare their own default."""

    effector_crop_bbox: tuple[int, int, int, int] | None = None
    """Generic calibrated content crop bbox (x, y, w, h) for plugin effectors."""

    effector_crop_cache: str | None = None
    """Generic path for the last-good calibrated crop JSON for plugin effectors."""

    effector_crop_retries: int = 3
    """Generic crop auto-detection retry count for plugin effectors."""

    picokvm: bool = Field(
        default=False,
        validation_alias=AliasChoices("GLASSBOX_PICOKVM", "AGENT_PICOKVM"),
    )
    """Use Luckfox PicoKVM for HID output and HDMI frame input.
    Private PicoKVM settings use GLASSBOX_PICOKVM_*."""

    stable_after_action: bool = False
    """Wait for consecutive stable frames before the first semantic read after
    an action. env GLASSBOX_STABLE_AFTER_ACTION=1."""

    stable_timeout: float = 3.0
    """Maximum seconds to wait for a stable frame when stable_after_action is enabled."""

    stable_diff_threshold: float = 0.005
    """Mean frame diff threshold below which two frames count as stable."""

    stable_consecutive: int = 2
    """Required consecutive stable frame comparisons."""

    stable_poll_interval: float = 0.05
    """Seconds between frame grabs while waiting for stability."""

    # ─── Controlled phone ────────────────────────────────────────────
    phone_model: str = "iphone_17_pro_max"
    """Controlled iPhone model key, see the DEVICES table in
    glassbox/perception/device.py. Determines the phone logical resolution
    used by the letterbox coordinate transform."""

    platform: str = "ios"
    """Controlled phone platform provider selector."""

    # ─── Locale (device language + region) ───────────────────────────
    language: str = "zh-Hans"
    """Device UI language pack (see glassbox/locale.py). Default zh-Hans keeps
    current behavior; English-first is the migration target and the global
    default flip is the last step. env GLASSBOX_LANGUAGE."""

    region: str | None = None
    """Optional region overlay (e.g. "CN") for region-specific label variants
    such as China-region English WLAN / Mobile Service. env GLASSBOX_REGION."""

    # ─── OCR ────────────────────────────────────────────────────────
    ocr: Literal["vision", "ocrmac"] = "vision"
    """OCR engine: vision = direct PyObjC call (default) / ocrmac = legacy fallback path."""

    icon_detector: str = "classical"
    """Icon detector backend selector."""

    # ─── Controlled App profile ──────────────────────────────────────
    profile_bundle: str | None = None
    """bundle_id of the walkthrough target App. When set, the matching
    profile is loaded from profiles/; when unset, the walkthrough carries
    no App white-box knowledge (the framework itself is not bound to a
    specific App)."""

    crawl_policy: str = "generic"
    """CrawlPolicy backend selector for generic crawler/explorer drivers."""

    # ─── VLM Layer 3 / recording ─────────────────────────────────────
    enable_vlm: bool | None = None
    """Enable VLM Layer 3. Preferred neutral selector; when unset, enable_kimi is used."""

    enable_kimi: bool = False
    """Legacy Kimi Layer 3 switch. Prefer GLASSBOX_ENABLE_VLM."""

    vlm: str = "moonshot"
    """VLM backend selector. `kimi*` names remain accepted as legacy aliases."""

    vlm_cache_dir: str | None = None
    """VLM describe disk cache directory (preferred neutral name)."""

    kimi_cache_dir: str | None = None
    """Legacy Kimi describe cache directory. Prefer GLASSBOX_VLM_CACHE_DIR."""

    enable_coldstart: bool = False
    """Enable the cold-start VLM annotator: a brand-new UTG node triggers one
    VLM annotation, fused onto OCR boxes (slow + billed, off by default).
    Needs a VLM client — pairs with enable_kimi / a key in .env."""

    coldstart_max_calls: int = 80
    """Per-run cap on cold-start VLM annotation calls."""

    recording_dir: str | None = None
    """obs.Recorder recording output directory (recording happens only when this is set)."""

    computer_use_artifact_dir: str | None = None
    """Computer-use runtime artifact root. When set, Phone actions are routed
    through ActionOrchestrator and produce audit/actions/diff/verification
    artifacts under this directory."""

    computer_use_trace_level: str = "standard"
    """Computer-use artifact trace level: off, summary, standard, or full."""

    computer_use_guarded: bool = False
    """Block high-risk actions unless explicit approval metadata is supplied."""

    computer_use_semantic_fail_fast: bool = False
    """Raise when computer-use verification returns semantic failed/blocked.
    Transport fail-fast remains controlled by GLASSBOX_ACTION_FAIL_FAST."""

    computer_use_observation_producer_mode: str = "scoped_source_owner"
    """Computer-use observation producer mode. v1 defaults to
    scoped_source_owner, where ActionOrchestrator owns the frame source during
    the run. recorder_buffer is reserved for a continuous recorder feeding the
    ObservationBuffer."""

    action_fail_fast: bool = True
    """Raise after recording a failed physical action result. Unit tests and
    diagnostic probes can disable this when they need to inspect ActionResult."""

    # ─── Screen memory (UTG) ─────────────────────────────────────────
    enable_memory: bool = False
    """Enable the UTG screen-memory layer (learned screen/element memory, off by default)."""

    memory_dir: str | None = None
    """UTG store directory (defaults to <repo_root>/memory/utg/ when memory is enabled)."""

    actuation_profile_dir: str | None = None
    """ActuationProfile store directory (defaults to <repo_root>/memory/actuation/)."""

    actuation_seed_path: str | None = None
    """Optional static actuation_seed JSON; contains only ActuationProfile-compatible facts."""

    recovery_seed_path: str | None = None
    """Optional static recovery_seed JSON; contains blocking overlay/recovery facts, not profile stats."""

    memory_bundle: str | None = None
    """Optional UTG bundle id override. Use this for system apps or glassbox
    walkthroughs without a profile, e.g. com.apple.Preferences."""

    ios_device: str | None = None
    """Optional devicectl device identifier/name for connected-iOS helpers."""

    # ─── Derived ─────────────────────────────────────────────────────
    def phone_size(self) -> tuple[int, int]:
        """Look up the model's native rendered pixel size (W, H)."""
        from glassbox.perception import device
        return device.get(self.phone_model)

    def phone_points(self) -> tuple[int, int]:
        """Look up the model's UIKit point size (W, H)."""
        from glassbox.perception import device
        return device.get_points(self.phone_model)


@lru_cache(maxsize=1)
def get_config() -> AgentConfig:
    """Process-level singleton. To re-read environment variables in tests, call `get_config.cache_clear()` first."""
    return AgentConfig()
