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

from pydantic import AliasChoices, Field, field_validator
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

    replay_dir: str | None = None
    """Point at an obs/recorder run directory (events.jsonl + frames/) → replay
    its recorded frames through the real perception stack (Tier B perception
    replay, docs/design/log_sim_replay_regression.md §5). Mutually exclusive
    with frame_dir; takes precedence over it. env GLASSBOX_REPLAY_DIR."""

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

    wheel_invert: bool = False
    """Flip vertical wheel direction for effectors that do not declare their own default."""

    effector_crop_bbox: tuple[int, int, int, int] | None = None
    """Reserved plugin-effector crop bbox (x, y, w, h); no built-in consumer."""

    app_viewport_bbox: tuple[int, int, int, int] | None = None
    """Optional foreground app viewport bbox inside the device-cropped frame.

    Use this for iPhone-only apps running in an iPad compatibility window:
    hardware/device geometry remains the iPad, while app OCR/VLM can be scoped
    to this inner bbox.
    """

    app_viewport_mode: Literal["auto", "device", "iphone_compat"] = "auto"
    """How ``phone.snapshot(scope="app")`` resolves the app viewport.

    ``device`` disables inner cropping, ``iphone_compat`` enables iPhone-shaped
    app-window detection, and ``auto`` uses an explicit bbox when provided then
    otherwise tries the safe iPhone-compat detector only when app scope is
    requested. Use app scope only for real iPhone-compat apps on iPad; keep
    device scope for SpringBoard, Settings, and other iPad-native split views.
    """

    default_observation_scope: Literal["device", "app"] = "device"
    """Default scope for snapshot/perceive when callers do not pass scope.

    ``app`` means "crop to an iPhone-compat foreground app window". It is not
    appropriate for SpringBoard, Settings, or iPad-native split-view tasks.
    """

    effector_crop_cache: str | None = None
    """Reserved plugin-effector last-good crop JSON path; no built-in consumer."""

    effector_crop_retries: int = 3
    """Reserved plugin-effector crop retry count; no built-in consumer."""

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
    """Controlled iOS/iPadOS model key, see the DEVICES table in
    glassbox/perception/device.py. Determines the device logical resolution
    used by the letterbox coordinate transform."""

    platform: str = "ios"
    """Controlled device platform provider selector."""

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

    text_detector: Literal["vision"] = "vision"
    """CUQ-TEXT-DETECTOR: conditional text-detection seam selector. Only
    ``vision`` is accepted until docs/goals/text_detector_dbnet_craft.md's
    on-rig trigger fires; DBNet/CRAFT must not enter the default install or
    runtime path before Vision knobs/tiling prove insufficient. Env
    GLASSBOX_TEXT_DETECTOR."""

    en_ocr_correction: bool = False
    """CUQ-OCR-EN: EXPERIMENTAL, rig-gated, default OFF (vision backend only — a
    no-op on ocr=ocrmac, whose AppleVisionOCR has no correction knobs). When set,
    English locales feed Apple Vision's NL language correction + an iOS
    proper-noun custom-word whitelist (see glassbox/locale.py `_EN_CUSTOM_WORDS`).
    Validation: a local offline OCR-replay over the en/HK corpus (frames under
    gitignored artifacts/, no committed harness) measured correction net-negative
    on raw coverage — it re-spaces status-bar / timestamp text — so it MUST clear
    an on-rig task_completion A/B before defaulting on (promote-or-remove once
    that runs). zh is NEVER affected — the overlay is English-only. env
    GLASSBOX_EN_OCR_CORRECTION."""

    ocr_minimum_text_height: float | None = None
    """CUQ-OCR-VISION: Apple Vision `minimumTextHeight` passthrough for dense /
    tiny UI text experiments. None means "do not call setMinimumTextHeight_"
    and preserves Apple's library default byte-for-byte; set 0.0 explicitly to
    ask Vision for no minimum-height filtering. Vision backend only; ocrmac
    ignores it. Default None until on-rig A/B proves task-level benefit. Env
    GLASSBOX_OCR_MINIMUM_TEXT_HEIGHT."""

    ocr_confidence_threshold: float | None = None
    """CUQ-OCR-VISION: Apple Vision OCR confidence threshold passthrough. None
    leaves `VisionOCR` at its constructor default; explicit values are
    experimental and must clear on-rig A/B before becoming the default. Vision
    backend only. Env GLASSBOX_OCR_CONFIDENCE_THRESHOLD."""

    ocr_unsharp_mask: bool | None = None
    """CUQ-OCR-VISION: Apple Vision OCR unsharp-mask toggle passthrough. None
    leaves `VisionOCR` at its constructor default; explicit values are
    experimental. Vision backend only. Env GLASSBOX_OCR_UNSHARP_MASK."""

    ocr_unsharp_sigma: float | None = None
    """CUQ-OCR-VISION: Apple Vision OCR unsharp-mask sigma passthrough. None
    leaves `VisionOCR` at its constructor default. Vision backend only. Env
    GLASSBOX_OCR_UNSHARP_SIGMA."""

    ocr_unsharp_amount: float | None = None
    """CUQ-OCR-VISION: Apple Vision OCR unsharp-mask amount passthrough. None
    leaves `VisionOCR` at its constructor default. Vision backend only. Env
    GLASSBOX_OCR_UNSHARP_AMOUNT."""

    # CUQ — live-camera OCR hardening. A live camera preview (e.g. the 操作按钮
    # Action-Button carousel) makes OCR emit chaotic, high-volume text; feeding
    # that pathological set to every downstream scene/text regex is what once
    # stalled perceive (a rare regex hang inside OCR text handling). These bound
    # the INPUT at the OCR→element chokepoint so no real iOS screen is affected
    # (limits are far above any genuine UI) while pathological frames are clipped.
    max_ocr_elements: int = 800
    """Cap on OCR text elements kept per frame (extras after this count are
    dropped). A real iPhone/iPad screen yields well under this; only a chaotic
    live-camera frame exceeds it, and such a frame should classify `unknown`
    (recovery backs out) anyway. 0 disables the cap. env GLASSBOX_MAX_OCR_ELEMENTS."""

    max_ocr_text_chars: int = 1024
    """Per-element OCR text is truncated to this many characters before any
    downstream regex/text-match runs, so a single multi-KB garbage token cannot
    drive pathological regex cost. Real UI labels/paragraphs are far shorter.
    0 disables truncation. env GLASSBOX_MAX_OCR_TEXT_CHARS."""

    ocr_timeout: float = 0.0
    """Watchdog: max seconds for one OCR recognize() call before perceive gives
    up and returns an empty element set (→ `unknown` scene → recovery backs out)
    instead of hanging. Effective because Apple Vision releases the GIL during
    recognition (a pure-Python `re` stall cannot be interrupted this way — the
    element/char caps above are the defense for that). Default 0 = disabled
    (default path byte-identical; spawns no watchdog thread); enable on the live
    rig where the camera-preview hang exists. env GLASSBOX_OCR_TIMEOUT."""

    ocr_tiling_enabled: bool = False
    """CUQ-OCR-VISION: opt-in OCR tiling pass for dense/tiny UI text. When on,
    perceive runs the normal full-frame OCR plus overlapping cropped tile OCR
    and deduplicates seam duplicates. Default off because it multiplies OCR
    cost and changes the element set; promote only after on-rig A/B shows
    task-level benefit at acceptable latency. Env GLASSBOX_OCR_TILING_ENABLED."""

    ocr_tiling_rows: int = 2
    """CUQ-OCR-VISION: row count for the opt-in OCR tiling pass. Env
    GLASSBOX_OCR_TILING_ROWS."""

    ocr_tiling_cols: int = 2
    """CUQ-OCR-VISION: column count for the opt-in OCR tiling pass. Env
    GLASSBOX_OCR_TILING_COLS."""

    ocr_tiling_overlap: float = 0.15
    """CUQ-OCR-VISION: fractional tile overlap for seam recall/dedup. Env
    GLASSBOX_OCR_TILING_OVERLAP."""

    ocr_tiling_include_full_frame: bool = True
    """CUQ-OCR-VISION: include the normal full-frame OCR sample before tile OCR
    in the opt-in tiling pass. Env GLASSBOX_OCR_TILING_INCLUDE_FULL_FRAME."""

    ocr_tiling_nms_iou: float = 0.55
    """CUQ-OCR-VISION: IoU threshold for deduplicating OCR regions recovered by
    overlapping tiles. Env GLASSBOX_OCR_TILING_NMS_IOU."""

    ocr_temporal_voting_enabled: bool = False
    """CUQ-OCR-TV: enable temporal OCR voting on validated perception paths only.
    Default off because it adds N x OCR cost and changes element text. Promote
    only after on-rig A/B shows task-level improvement. Env
    GLASSBOX_OCR_TEMPORAL_VOTING_ENABLED."""

    ocr_temporal_voting_frames: int = 3
    """CUQ-OCR-TV: number of OCR frames requested when temporal voting is enabled.
    Env GLASSBOX_OCR_TEMPORAL_VOTING_FRAMES."""

    ocr_temporal_voting_min_presence: int = 2
    """CUQ-OCR-TV: minimum distinct sampled frames a region must appear in before
    it is marked stable rather than transient. Env
    GLASSBOX_OCR_TEMPORAL_VOTING_MIN_PRESENCE."""

    ocr_temporal_voting_pos_tol: int = 20
    """CUQ-OCR-TV: pixel tolerance for the existing vote_scenes geometry matcher.
    Env GLASSBOX_OCR_TEMPORAL_VOTING_POS_TOL."""

    ocr_temporal_voting_sample_spacing_ms: int = 0
    """CUQ-OCR-TV: optional delay between voting samples. Default 0 preserves the
    existing back-to-back perceive_voted behavior. Env
    GLASSBOX_OCR_TEMPORAL_VOTING_SAMPLE_SPACING_MS."""

    ocr_temporal_voting_outer_timeout: float = 0.0
    """CUQ-OCR-TV: optional wall-clock budget for the full voting sample loop.
    Per-frame OCR cancellation still uses GLASSBOX_OCR_TIMEOUT. 0 disables the
    outer budget. Env GLASSBOX_OCR_TEMPORAL_VOTING_OUTER_TIMEOUT."""

    ocr_temporal_voting_keep_raw_samples: bool = False
    """CUQ-OCR-TV: retain raw per-frame OCR samples in vote metadata/artifacts for
    diagnostics. Default off to avoid hot-path IO/large scene payloads. Env
    GLASSBOX_OCR_TEMPORAL_VOTING_KEEP_RAW_SAMPLES."""

    icon_detector: str = "classical"
    """Icon detector backend selector."""

    # ─── Controlled App profile ──────────────────────────────────────
    profile_bundle: str | None = None
    """bundle_id of the walkthrough target App. When set, the matching
    profile is loaded from profiles/; when unset, the walkthrough carries
    no App white-box knowledge (the framework itself is not bound to a
    specific App)."""

    crawl_policy: str = "generic"
    """CrawlPolicy backend selector for generic crawler/explorer drivers.
    App-specific regression harnesses may use bespoke crawlers instead."""

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

    springboard_icon_map_path: str | None = None
    """JSON path for the VLM-built SpringBoard icon map. When set it PERSISTS the
    icon→position map across runs (layout-keyed, drift-invalidated), so the VLM
    icon-naming cost is paid once per Home layout, not every cold start. When
    None the map is in-memory only (per run). env GLASSBOX_SPRINGBOARD_ICON_MAP_PATH."""

    # ─── Experimental flag retirement policy ───────────────────────────
    # Each default-off experimental flag in this section must carry its CUQ /
    # issue identifier, validation conditions, and promote-or-remove intent in
    # the field docstring. Once a flag is rig-validated as default-on, file the
    # follow-up to make the behavior unconditional and delete the branch.
    #
    # Keep owner boundaries explicit: Phone-owned flags may flow into
    # PhoneFeatureFlags; runtime dependency gates (for example enable_coldstart)
    # and ActionOrchestrator flags (for example recover_then_retry) must not.

    enable_coldstart: bool = False
    """Enable the cold-start VLM annotator: a brand-new UTG node triggers one
    VLM annotation, fused onto OCR boxes (slow + billed, off by default).
    Needs a VLM client — pairs with enable_kimi / a key in .env."""

    detect_icons_in_perceive: bool = False
    """CUQ-2.1: run the no-text icon detector inside perceive() and inject the
    surviving regions as tappable image elements, so icon-only controls (+,
    share, gear, back-chevron, trash) become tap candidates instead of being
    invisible to the OCR-text-only candidate set. Default off (adds CV cost per
    perceive and changes the candidate set); validate on-rig before enabling.
    Scene classification is unaffected (icons are injected after classifiers)."""

    ui_layout_segmentation_enabled: bool = True
    """CUQ-UI-LAYOUT: default ON. perceive() builds
    a geometric Tier-A element graph from OCR text plus icon regions: reading
    order is normalized, icon+label affordances are grouped into one tappable
    element, and icon-only controls are promoted to typed tap targets. No VLM
    captioning is invoked. This implicitly runs the no-text icon detector even
    when GLASSBOX_DETECT_ICONS_IN_PERCEIVE is off, because icon regions are the
    grouping input. Set GLASSBOX_UI_LAYOUT_SEGMENTATION_ENABLED=0 to disable."""

    ios_closed_set_canonicalization_enabled: bool = True
    """CUQ-OCR-POSTPROCESS: keep iOS/iPadOS closed-set Home/Settings
    canonicalization on the runtime perception + memory path. This is the
    current default intelligence: SpringBoard app labels and Settings root rows
    may write canonical intent_label values, and screen memory may use those
    labels for stable element keys. Set to 0 only for measurement arms such as
    raw_no_canonical that need to compare raw OCR against the current baseline;
    report/evaluator canonical scoring remains independent. Env
    GLASSBOX_IOS_CLOSED_SET_CANONICALIZATION_ENABLED."""

    strict_target_matching: bool = False
    """CUQ-1.5: make find_text ambiguity-aware — the substring tier prefers the
    closest-length containing row (not the first), and the fuzzy tier returns no
    match when the best candidate does not beat the runner-up by a margin, so an
    ambiguous read escalates (e.g. to VLM grounding) instead of guessing the
    wrong row. Default off (changes which element a tap resolves to); validate
    on-rig before enabling."""

    require_home_icon_grid: bool = False
    """CUQ-2.2: require icon-grid corroboration before is_ios_home_screen trusts
    a bare 'springboard' classification as Home, closing the false-positive where
    a Settings detail page mislabeled 'springboard' is treated as Home (and a
    settings row is tapped as an app icon). Default off (tightens a core
    recognizer); validate on-rig before enabling."""

    reverify_fresh_frame: bool = False
    """CUQ-1.3: before a VLM verification escalation, re-perceive a fresh frame
    (perceive(fresh=True)) and re-check the expected_state on it. The OCR verify
    and a subsequent describe() both read the same post-action frame, so for
    text-based expectations (visible_text / element_appears / element_gone) the
    VLM re-check is otherwise guaranteed identical — pure wasted budget+latency.
    A fresh re-read picks up text that only finished rendering after settle and,
    when it now matches, returns succeeded WITHOUT spending the VLM call. Default
    off (adds a capture+OCR on escalation); the fresh OCR short-circuits via the
    perceive cache when pixels are unchanged, so it only re-OCRs a genuinely
    changed screen. Validate on-rig before enabling."""

    recovery_target_page: str | None = None
    """CUQ-0.5: when set, install the generic UTG-pathed recovery hook
    (make_try_memory_path_hook) ahead of the home-anchor fallback. On a
    stuck/exhausted recovery it recognizes the current screen, asks screen
    memory for the shortest safe-enough learned path to this page_id, and
    replays that edge chain to re-navigate in place instead of resetting to
    Home. Env GLASSBOX_RECOVERY_TARGET_PAGE (e.g. an app root page id). Default
    None preserves today's home-only recovery. Needs a populated UTG graph
    (memory enabled); validate on-rig that the replayed path actually recovers."""

    recovery_allowed_actions: str = "home,back"
    """CUQ-0.5: comma-separated safety gate for the memory-path recovery — only
    these learned-edge ops are pathed and replayed (so recovery backs out via
    known navigation, never an improvised forward tap). Env
    GLASSBOX_RECOVERY_ALLOWED_ACTIONS."""

    recovery_min_success_rate: float = 0.5
    """CUQ-0.5: minimum historical edge success rate for the memory-path
    recovery to trust a learned edge. Env GLASSBOX_RECOVERY_MIN_SUCCESS_RATE."""

    coldstart_max_calls: int = 80
    """Per-run cap on cold-start VLM annotation calls."""

    ai_scroll_prefer_wheel: bool = False
    """CUQ-3.15: route the generic AI scroll verb (AIPhone.scroll / explore /
    candidate execution) to the precise scroll wheel when the backend supports
    it, instead of always using swipe-fling (which overshoots). Intended for the
    iPad rig, where wheel scrolling is validated/authoritative; iPhone wheel is
    intermittent so this stays off there. Env GLASSBOX_AI_SCROLL_PREFER_WHEEL.
    Default off → swipe-fling everywhere (byte-identical)."""

    calibration_probe_target: str = ""
    """CUQ-3.7: a known-safe anchor label to eagerly tap at session start when no
    actuation offset has been learned yet, so the offset is seeded before the
    first task tap (instead of only opportunistically mid-run). Env
    GLASSBOX_CALIBRATION_PROBE_TARGET. Empty (default) disables the probe
    (byte-identical). The target must be present + safe-to-tap on the session-start
    screen — operator-supplied, since no element is universally safe."""

    recover_then_retry: bool = False
    """CUQ-0.12: when stuck/loop recovery succeeds, re-attempt the failed action
    once from the recovered (clean) state, so recovery alters the CURRENT action's
    outcome instead of only priming the next one. Env GLASSBOX_RECOVER_THEN_RETRY.
    Default off (byte-identical: recovery stays post-action). Re-entrancy-guarded
    (a retry can't itself retry); validate on-rig that re-attempting from the
    recovered state helps rather than double-applies."""

    idempotent_retry_budget: int = 0
    """CUQ-0.11: semantic retry budget for ops declared idempotent (home /
    scroll_wheel / control_center / notification_center / recents — safe to
    re-do). 0 (default) leaves retry_budget at 0 so the `unknown → retry` policy
    is a no-op (byte-identical); >0 lets an `unknown` verdict on a safe op retry
    instead of giving up. Env GLASSBOX_IDEMPOTENT_RETRY_BUDGET. Non-idempotent
    ops (tap/back/...) always stay at 0. Validate on-rig (e.g. that a retried
    scroll does not over-scroll) before raising."""

    whitebox_hint_selection: bool = False
    """CUQ-2.10: when OCR cannot find a selection target, resolve it by an
    element's whitebox identity (accessibility_id / asset_match / deep_link /
    swift_class) — a Tier-1+ app-profile signal more reliable than fuzzy OCR.
    Env GLASSBOX_WHITEBOX_HINT_SELECTION. Default off; only effective when a
    whitebox profile populates hints and the caller's target names that identity."""

    vlm_reground_selection: bool = False
    """CUQ-0.4: when OCR cannot find a selection target (expect_text / tap_text),
    escalate ONCE to the VLM (describe → find-by-description / intent) before
    failing, instead of hard-failing. Default off so the default path is
    byte-identical — no billed describe() on an OCR miss — even when a VLM client
    is wired. Env GLASSBOX_VLM_REGROUND_SELECTION. Requires a VLM client; pairs
    with vlm_set_of_mark. Validate VLM cost/benefit on-rig before enabling."""

    strict_settings_detail: bool = False
    """CUQ-2.6: require a Settings-distinguishing signal (a system noun like
    Wi-Fi/Bluetooth/Face ID, or a Learn-More footnote) before the generic
    body-marker heuristic classifies a screen as `settings_detail`, closing the
    false-positive where a third-party app screen carrying only locale-generic
    words (允许 / 访问 / App / 通知 …) is mistaken for Settings. Env
    GLASSBOX_STRICT_SETTINGS_DETAIL. Default off (tightening a core recognizer
    risks scrolled-detail recall); validate on-rig before enabling."""

    settings_locale_fuzzy_resolution: bool = True
    """Settings root-label crediting under a non-zh locale: when on,
    `canonical_expected_root_label` (a) sources its alias vocabulary from the
    single-source-of-truth `SectionVocab` (locale-correct EN display + aliases)
    and (b) matches OCR text against those alias keys with an OCR-tolerant fuzzy
    tier (margin + short-key + prefix-truncation guards), so a 1-letter English
    OCR garble of a physically-reached required page (Screen → Screem, Accessibility
    → Accessibilityl) still resolves to its section instead of logging a spurious
    `search_no_result`. zh runs keep today's exact zh resolver (no change, and the
    en-only gate avoids the zh-vocab legacy recursion), so this only affects en/non-zh
    locales. Default ON: rig-validated on iPad mini 7 en/HK (2026-05-30 A/B,
    required_missing 2→1, zero regressions / zero over-crediting; the safety gate
    `is_safe_known_navigation_label` rides on this resolver and was unchanged for
    bare singulars). Set 0 to restore exact-only resolution.
    Env GLASSBOX_SETTINGS_LOCALE_FUZZY_RESOLUTION."""

    settings_search_reject_breadcrumb_result: bool = False
    """Fix 3: in the iPad Settings deep-search results, reject `Root → Child`
    breadcrumb rows (e.g. `Accessibility → Switch Control`) as root results.
    Their leading segment matches the requested root, so today they tie the real
    root row at rank 0 and a higher-on-screen breadcrumb can win — tapping it
    opens the CHILD page (Keyboards & Typing), never the root, → a spurious
    `search_no_result` on a required page. When on, a row is accepted as a root
    result only if its FULL text resolves to the root (the breadcrumb's primary-
    segment match is dropped when the text carries an arrow), so the genuine root
    row wins. Default off keeps the selection path byte-identical (changes which
    element a search-result tap targets); validate on-rig (iPad mini 7 en/HK)
    before flipping. Env GLASSBOX_SETTINGS_SEARCH_REJECT_BREADCRUMB_RESULT."""

    settings_search_root_fallback_sidebar: bool = False
    """Fix 3b: when Settings search cannot open a required root, recover via the
    sidebar instead of logging `search_no_result`. The iPad deep-search for some
    roots (Accessibility) surfaces ONLY deep-child results (every row is a
    `Root → Child` breadcrumb, some with the arrow dropped by OCR), so there is no
    tappable root result to select — search structurally cannot open the root.
    When on, after the search attempt fails the crawler returns to the root list,
    scrolls the sidebar to the root row, taps it, and verifies the opened title
    (one-shot, title-gated, reuses the existing wheel-scroll + landing-retry +
    title-check machinery). Default off (adds a recovery navigation); validate
    on-rig (iPad mini 7 en/HK) before flipping. Env
    GLASSBOX_SETTINGS_SEARCH_ROOT_FALLBACK_SIDEBAR."""

    settings_search_recovery_decouple_exempt: bool = True
    """Decouple the device-unavailable exemption from search-recovery robustness.
    The 4 iPad-absent roots (蜂窝网络/操作按钮/待机显示/紧急SOS) are exempted ONLY
    when search recovery searches them and logs `search_no_result`. But when
    return_to_settings_root flakes (intermittent back-nav) mid-loop, the recovery
    loop used to early-`return` and never search the roots after the flake — so
    they got no evidence and were falsely counted required-missing (false coverage
    failure, run-to-run flap). When on, a return-to-root failure skips ONLY the
    current root and the loop CONTINUES searching the rest (bounded by a small
    consecutive-failure cap), so every device-unavailable root still gets its real
    search attempt and genuine `search_no_result`. Strictly evidence-preserving:
    a reachable root that search CAN open is still entered (not exempted), and only
    the 4-label iPad set is ever exemptable — no blind/profile exempt. Default ON:
    rig-validated on iPad mini 7 en/HK (2026-05-30, 5-round sample, required_missing
    == [] in 5/5 incl. 2 rounds that still hit return_to_root_failed, vs 2/5 before).
    Set 0 to restore the early-return behavior. Env
    GLASSBOX_SETTINGS_SEARCH_RECOVERY_DECOUPLE_EXEMPT."""

    settings_return_root_via_memory: bool = False
    """Smart, app-agnostic return-to-root via the UTG screen-memory graph instead
    of the Settings-hardcoded back-nav state machine. When on, return_to_settings_root
    first tries the generic memory path: recognize() the current screen as a known
    node, ask the graph for the shortest learned safe path to the root page_id
    (memory.path_to_page, allowed_actions={back,home}), and replay those learned
    edges — verifying arrival by node identity (robust to the iPad split-view root
    detector oscillating). Falls back to today's hardcoded scene-kind state machine
    when the screen is unrecognized / no path exists / replay does not land on root.
    The mechanism is generic (the root page_id is a parameter), realizing
    "smartly return to the app root" rather than Settings-specific rules. Default
    off keeps the hardcoded path byte-identical; needs memory enabled (it is, per
    run); validate on-rig before flipping. Env GLASSBOX_SETTINGS_RETURN_ROOT_VIA_MEMORY."""

    settings_ipad_root_projection: bool = False
    """L1 iPad Settings state-machine model: when screen memory observes a
    split-view Settings frame, also write a sidebar-scoped virtual
    `settings/root` node and attribute sidebar-row taps from that root node.
    Default off because it changes UTG topology; validate on the iPad rig before
    enabling. Env GLASSBOX_SETTINGS_IPAD_ROOT_PROJECTION."""

    letterbox_refresh_consecutive: int = 2
    """CUQ-3.14: how many consecutive frames must agree on a NEW letterbox crop
    bbox before auto-refresh commits it (hysteresis). >1 stops a single
    transient-content frame (a fullscreen image/video/splash) from silently
    re-fitting the crop and drifting every subsequent coordinate. 1 restores the
    old commit-on-first-detection behavior. Env
    GLASSBOX_LETTERBOX_REFRESH_CONSECUTIVE. Only matters when the crop is
    auto-detected (no configured bbox), where auto-refresh is on."""

    memory_locate_priors: bool = False
    """CUQ-3.21: when OCR cannot find a selection target, use the UTG position
    memory as a tap-point prior (recognize the screen → a remembered element
    whose text matches → its last-known box), tried before the billed VLM
    reground. Volatile (list-row) positions are skipped and a stale prior that
    mis-taps is caught by post-action verification. Env
    GLASSBOX_MEMORY_LOCATE_PRIORS. Requires a populated UTG graph; default off."""

    vlm_set_of_mark: bool = False
    """CUQ-2.5: enable Set-of-Mark grounding on VLM `describe()` escalations —
    numbered red boxes are drawn on the frame so the VLM correlates each element
    to a mark it can see, instead of mentally aligning text coordinates (better
    grounding on dense/ambiguous scenes, at the cost of more tokens + sensitivity
    to box accuracy). Env GLASSBOX_VLM_SET_OF_MARK. Requires a VLM client;
    default off (measured at parity on the sparse eval set — opt in per app)."""

    coldstart_promote_controls: bool = False
    """CUQ-2.3: when a cold-start VLM annotation labels an element `toggle` or
    `slider`, promote it to the declared `switch`/`slider` element type and set
    its tap point to the row's right-margin control (instead of leaving it as
    `text`, where a tap hits the label and not the switch). Env
    GLASSBOX_COLDSTART_PROMOTE_CONTROLS. Requires cold-start (enable_coldstart);
    default off. Validate on-rig that the right-margin tap fraction toggles the
    control before flipping default-on."""

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

    semantic_plan_ops: str = "back,scroll,tap"
    """Comma-separated core ops routed through the first-class SemanticActionPlan
    strategy ladder instead of the legacy single-strategy path (CUQ-0.1/0.8), so a
    verified-failed strategy switches to the next reliable primitive (back:
    nav_back_tap -> keyboard_back -> edge_back_gesture; scroll: wheel -> swipe;
    tap: target_tap -> keyboard_focus_activate, with the CUQ-0.8 nested-
    orchestration suppression) instead of giving up.

    Default-on for `back,scroll,tap` since the 2026-05-29 on-rig A/B
    (`make ab-semantic-plan`, iPad mini 7 en/HK): vs the flags-off baseline the
    ladder lifted task_completion 0.0->0.5, action_success 0.50->0.75, scroll
    success 0.70->1.0 and cut unknown 0.50->0.25, with strategy_switches 0->4 and
    VLM never firing — compare rc 0, no regression. A full default-on iPad-en
    Settings drill-down corroborates (action_success 0.955, strategy_switches=5
    in production). Re-run with higher ROUNDS / on iPhone before widening the set.
    `launch_app` is
    intentionally excluded (`open_app` is a complex multi-page springboard search,
    no real ladder yet) and `home` already ladders bespoke, so listing those has
    no effect. Set GLASSBOX_SEMANTIC_PLAN_OPS to override (empty string restores
    the legacy single-strategy path; note routing also needs the orchestrator,
    i.e. computer_use_artifact_dir, so the bare runtime is unaffected)."""

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

    memory_autosave_every: int = 12
    """Persist the UTG every N observations (CUQ-3.22) so a mid-run crash/kill
    keeps the session's learned graph instead of losing everything since the
    last close-only save. 0 disables incremental saves (close-only)."""

    actuation_profile_dir: str | None = None
    """ActuationProfile store directory (defaults to <repo_root>/memory/actuation/)."""

    actuation_seed_path: str | None = None
    """Optional static actuation_seed JSON; contains only ActuationProfile-compatible facts."""

    recovery_seed_path: str | None = None
    """Optional static recovery_seed JSON; contains blocking overlay/recovery facts, not profile stats."""

    memory_bundle: str | None = None
    """Optional UTG bundle id override. Use this for system apps or glassbox
    walkthroughs without a profile, e.g. com.apple.Preferences."""

    # ─── Derived ─────────────────────────────────────────────────────
    @field_validator("effector_crop_bbox", "app_viewport_bbox", mode="before")
    @classmethod
    def _parse_bbox(cls, value):
        if value is None or isinstance(value, tuple):
            return value
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            if "," in text and not text.startswith("["):
                return tuple(int(part.strip()) for part in text.split(","))
        return value

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
