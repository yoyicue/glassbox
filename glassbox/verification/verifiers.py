"""Semantic verifiers for computer-use actions."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Protocol

from glassbox.cognition.base import Scene

SemanticStatus = str


@dataclass(frozen=True)
class SemanticOutcome:
    status: SemanticStatus
    verifier: str
    reason: str
    confidence: float = 0.0
    verifier_version: str = "2026-05-19.1"
    verifier_hash: str | None = None
    matched_evidence: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    matched_frame_id: str | None = None
    matched_scene_id: str | None = None
    deterministic: bool = False
    retry_allowed: bool = True
    disqualifying_state: str | None = None
    verification_skipped: bool = False
    observation_match: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "verifier": self.verifier,
            "reason": self.reason,
            "confidence": self.confidence,
            "verifier_version": self.verifier_version,
            "verifier_hash": self.verifier_hash,
            "matched_evidence": list(self.matched_evidence),
            "missing_evidence": list(self.missing_evidence),
            "matched_frame_id": self.matched_frame_id,
            "matched_scene_id": self.matched_scene_id,
            "deterministic": self.deterministic,
            "retry_allowed": self.retry_allowed,
            "disqualifying_state": self.disqualifying_state,
            "verification_skipped": self.verification_skipped,
            "observation_match": self.observation_match,
        }


@dataclass(frozen=True)
class VerifierInput:
    attempt_id: str
    attempt_group_id: str
    action: dict[str, Any]
    before_requested: Scene | None
    before_command: Scene | None
    after_scenes: list[Scene]
    after_mode: str
    frame_diff: dict[str, Any] | None
    scene_diff: dict[str, Any] | None
    command_result: dict[str, Any]
    risk: dict[str, Any]
    platform: str = "ios"
    matched_by_observation: dict[str, Any] | None = None
    after_frame_ids: list[str] = field(default_factory=list)
    after_scene_ids: list[str] = field(default_factory=list)


class Verifier(Protocol):
    name: str
    version: str

    def verify(self, input: VerifierInput) -> SemanticOutcome: ...


POWER_OFF_MARKERS = ("滑动来关机", "关机", "SOS", "紧急呼叫")
LOCK_MARKERS = ("输入密码", "Face ID", "Touch ID", "解锁")
PERMISSION_MARKERS = (
    "想要访问",
    "允许访问",
    "需要权限",
    "请求权限",
    "权限请求",
    "不允许",
    "Would Like to",
    "Would Like To",
    "Don’t Allow",
    "Don't Allow",
    "Allow Once",
    "Allow While Using",
)
APP_CRASH_MARKERS = (
    "意外退出",
    "已崩溃",
    "重新打开",
    "应用程序错误",
    "unexpectedly quit",
    "crashed",
    "reopen",
)
HOME_SCREEN_MARKERS = (
    "App Store",
    "照片",
    "相机",
    "日历",
    "天气",
    "钱包",
    "时钟",
    "FaceTime",
    "游戏",
    "设置",
)
SETTINGS_APP_LABELS = {"settings", "设置", "com.apple.preferences"}
NAV_BACK_TEXTS = ("<", "‹", "〈", "返回", "Back")
TRANSIENT_CAROUSEL_MARKERS = (
    "评价",
    "评论",
    "用户",
    "评分",
    "星",
    "review",
    "rating",
    "carousel",
    "testimonial",
    "广告",
    "ad",
)


@dataclass(frozen=True)
class DisqualifyingState:
    state: str
    markers: tuple[str, ...]
    status: SemanticStatus
    confidence: float
    deterministic: bool
    retry_allowed: bool = False


# CUQ-3.19: device-safety disqualifying states (power-off, locked, app crashed)
# map to the terminal `blocked` bucket, not `failed`. The execution state
# machine terminates on either (via the disqualifying_state flag), but `blocked`
# is the documented safety bucket — it records these as a deliberate safety stop
# to surface, not as a task-action failure, and keeps "send no more input on a
# safety state" explicit at the status level too (invariant #4 exception).
DISQUALIFYING_STATES = (
    DisqualifyingState(
        state="ios_power_off_screen",
        markers=POWER_OFF_MARKERS,
        status="blocked",
        confidence=0.95,
        deterministic=True,
    ),
    DisqualifyingState(
        state="ios_lock_screen",
        markers=LOCK_MARKERS,
        status="blocked",
        confidence=0.9,
        deterministic=False,
    ),
    DisqualifyingState(
        state="ios_system_permission_dialog",
        markers=PERMISSION_MARKERS,
        status="approval_required",
        confidence=0.85,
        deterministic=False,
    ),
    DisqualifyingState(
        state="app_crashed_or_terminated",
        markers=APP_CRASH_MARKERS,
        status="blocked",
        confidence=0.9,
        deterministic=False,
    ),
)
HOME_UNEXPECTED_STATE = DisqualifyingState(
    state="ios_home_unexpected",
    markers=HOME_SCREEN_MARKERS,
    status="failed",
    confidence=0.8,
    deterministic=False,
)


def _texts(scene: Scene | None) -> list[str]:
    if scene is None:
        return []
    return [str(e.text).strip() for e in scene.elements if e.text and str(e.text).strip()]


def _all_texts(scenes: list[Scene]) -> list[str]:
    values: list[str] = []
    for scene in scenes:
        values.extend(_texts(scene))
    return values


def _looks_like_transient_carousel_change(input: VerifierInput) -> bool:
    scene_diff = input.scene_diff or {}
    if not scene_diff.get("changed"):
        return False
    if scene_diff.get("page_id_before") != scene_diff.get("page_id_after"):
        return False
    if scene_diff.get("scene_type_before") != scene_diff.get("scene_type_after"):
        return False
    added = [str(text) for text in scene_diff.get("texts_added") or []]
    removed = [str(text) for text in scene_diff.get("texts_removed") or []]
    if not added and not removed:
        return False
    if len(added) + len(removed) > 6:
        return False
    if abs(int(scene_diff.get("element_count_delta") or 0)) > 2:
        return False
    combined = " ".join([*_texts(input.before_command), *_all_texts(input.after_scenes), *added, *removed]).casefold()
    return any(marker.casefold() in combined for marker in TRANSIENT_CAROUSEL_MARKERS)


def _navigation_identity_texts(scene: Scene | None) -> list[str]:
    if scene is None:
        return []
    values: list[str] = []
    for el in sorted(scene.elements, key=lambda item: (item.box.y, item.box.x)):
        text = str(el.text).strip() if el.text else ""
        if not text or el.type == "status_bar" or el.type == "nav_back" or text in NAV_BACK_TEXTS:
            continue
        values.append(text)
    return values


def _navigation_title(scene: Scene | None) -> str | None:
    if scene is None:
        return None
    viewport_w = scene.viewport_size[0] if scene.viewport_size else 400
    viewport_h = scene.viewport_size[1] if scene.viewport_size else 800
    top_limit = max(120, int(viewport_h * 0.13))
    candidates: list[tuple[int, int, str]] = []
    for el in scene.elements:
        text = str(el.text).strip() if el.text else ""
        if (
            not text
            or el.type == "status_bar"
            or el.type == "nav_back"
            or text in NAV_BACK_TEXTS
            or el.box.center[1] > top_limit
        ):
            continue
        center_distance = abs(el.box.center[0] - viewport_w // 2)
        candidates.append((center_distance, el.box.y, text))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][2]


def _navigation_body_texts(scene: Scene | None) -> list[str]:
    if scene is None:
        return []
    viewport_h = scene.viewport_size[1] if scene.viewport_size else 800
    top_limit = max(120, int(viewport_h * 0.13))
    values: list[str] = []
    for el in sorted(scene.elements, key=lambda item: (item.box.y, item.box.x)):
        text = str(el.text).strip() if el.text else ""
        if (
            not text
            or el.type == "status_bar"
            or el.type == "nav_back"
            or text in NAV_BACK_TEXTS
            or el.box.center[1] <= top_limit
        ):
            continue
        values.append(text)
    return values


def _navigation_page_signature(scene: Scene | None) -> str | None:
    if scene is None:
        return None
    if scene.page_id:
        return f"page:{scene.page_id}"

    significant = _navigation_identity_texts(scene)
    if not significant:
        return None
    return "texts:" + "\x1f".join(significant[:10])


def _navigation_text_overlap(before: Scene | None, after: Scene | None) -> float:
    before_texts = set(_navigation_identity_texts(before))
    after_texts = set(_navigation_identity_texts(after))
    if not before_texts or not after_texts:
        return 0.0
    return len(before_texts & after_texts) / max(len(before_texts), len(after_texts))


def _after_frame_id(input: VerifierInput, index: int = -1) -> str | None:
    if input.after_frame_ids:
        return input.after_frame_ids[index]
    if input.after_scenes:
        return str(input.after_scenes[index].frame_id)
    return None


def _after_scene_id(input: VerifierInput, index: int = -1) -> str | None:
    if input.after_scene_ids:
        return input.after_scene_ids[index]
    return None


def _observation_frame_id(input: VerifierInput) -> str | None:
    match = input.matched_by_observation or {}
    frame_id = match.get("frame_id")
    return str(frame_id) if frame_id else _after_frame_id(input)


def _observation_scene_id(input: VerifierInput) -> str | None:
    match = input.matched_by_observation or {}
    scene_id = match.get("scene_id")
    return str(scene_id) if scene_id else _after_scene_id(input)


def _observation_match(
    verifier_name: str,
    input: VerifierInput,
    *,
    kind: str,
    matched_evidence: list[str],
    state: str | None = None,
) -> dict[str, Any]:
    match = dict(input.matched_by_observation or {})
    match.setdefault("kind", kind)
    match.setdefault("verifier", verifier_name)
    match["matched_evidence"] = list(matched_evidence)
    frame_id = _observation_frame_id(input)
    scene_id = _observation_scene_id(input)
    if frame_id is not None:
        match["frame_id"] = frame_id
    if scene_id is not None:
        match["scene_id"] = scene_id
    if state is not None:
        match["state"] = state
    return match


def _contains_any(texts: list[str], markers: tuple[str, ...] | list[str]) -> list[str]:
    hits: list[str] = []
    for marker in markers:
        if any(marker in text for text in texts):
            hits.append(marker)
    return hits


def _looks_like_home_texts(texts: list[str]) -> bool:
    return len(set(_contains_any(texts, HOME_SCREEN_MARKERS))) >= 3


def _targets_settings_app(candidates: list[str]) -> bool:
    return any(candidate.strip().casefold() in SETTINGS_APP_LABELS for candidate in candidates)


def _settings_foreground_evidence(scene: Scene | None) -> str | None:
    if scene is None:
        return None
    page_id = str(scene.page_id or "").strip()
    if page_id == "settings" or page_id.startswith("settings/"):
        return f"page_id={page_id}"
    for field_name in ("scene_type", "semantic_scene_type", "platform_scene_kind"):
        value = str(getattr(scene, field_name, "") or "").strip()
        if "settings" in value.casefold():
            return f"{field_name}={value}"
    return None


def _action_text_values(action: dict[str, Any], *keys: str) -> list[str]:
    values: list[str] = []
    sources = (action.get("kwargs", {}), action.get("metadata", {}))
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            raw = source.get(key)
            if isinstance(raw, str) and raw.strip():
                values.append(raw.strip())
        aliases = source.get("aliases")
        if isinstance(aliases, list | tuple):
            values.extend(str(alias).strip() for alias in aliases if str(alias).strip())
    return list(dict.fromkeys(values))


def detect_disqualifying_state(
    texts: list[str],
    *,
    include_home_unexpected: bool = False,
) -> tuple[DisqualifyingState, list[str]] | None:
    for spec in DISQUALIFYING_STATES:
        hits = (
            _power_off_hits(texts, spec.markers)
            if spec.state == "ios_power_off_screen"
            else _lock_screen_hits(texts, spec.markers)
            if spec.state == "ios_lock_screen"
            else _contains_any(texts, spec.markers)
        )
        if hits:
            return spec, hits
    if include_home_unexpected:
        hits = _contains_any(texts, HOME_UNEXPECTED_STATE.markers)
        if len(set(hits)) >= 3:
            return HOME_UNEXPECTED_STATE, hits
    return None


def _power_off_hits(texts: list[str], markers: tuple[str, ...]) -> list[str]:
    hits = _contains_any(texts, markers)
    if not hits:
        return []
    hit_set = set(hits)
    if "滑动来关机" in hit_set:
        return hits
    if "关机" in hit_set and ({"SOS", "紧急呼叫"} & hit_set):
        return hits
    return []


def _lock_screen_hits(texts: list[str], markers: tuple[str, ...]) -> list[str]:
    hits = _contains_any(texts, markers)
    if not hits:
        return []
    hit_set = set(hits)
    if "输入密码" in hit_set:
        return hits
    biometric_hits = {"Face ID", "Touch ID"} & hit_set
    if biometric_hits and ({"解锁", "输入密码"} & hit_set):
        return hits
    if any("iPhone密码" in text or "设备密码" in text for text in texts):
        return hits
    return []


def _source_hash(cls: type) -> str:
    payload = f"{cls.__module__}.{cls.__qualname__}".encode()
    return hashlib.sha1(payload).hexdigest()[:12]


class BaseTextVerifier:
    name = "base_text"
    version = "2026-05-19.1"
    success_markers: tuple[str, ...] = ()
    minimum_hits = 1
    home_unexpected_disqualifies = False

    def _disqualify(self, input: VerifierInput, texts: list[str]) -> SemanticOutcome | None:
        detected = detect_disqualifying_state(
            texts,
            include_home_unexpected=self.home_unexpected_disqualifies,
        )
        if detected is not None:
            spec, hits = detected
            observation_match = _observation_match(
                self.name,
                input,
                kind="disqualifying_state",
                state=spec.state,
                matched_evidence=hits,
            )
            return SemanticOutcome(
                status=spec.status,
                verifier=self.name,
                reason=f"disqualifying state detected: {spec.state}",
                confidence=spec.confidence,
                verifier_version=self.version,
                verifier_hash=_source_hash(self.__class__),
                matched_evidence=hits,
                matched_frame_id=_observation_frame_id(input),
                matched_scene_id=_observation_scene_id(input),
                deterministic=spec.deterministic,
                retry_allowed=spec.retry_allowed,
                disqualifying_state=spec.state,
                observation_match=observation_match,
            )
        return None

    def verify(self, input: VerifierInput) -> SemanticOutcome:
        if input.after_mode == "none":
            return SemanticOutcome(
                status="unknown",
                verifier=self.name,
                reason="after observation was not captured",
                verifier_version=self.version,
                verifier_hash=_source_hash(self.__class__),
                verification_skipped=True,
                observation_match=input.matched_by_observation,
            )
        texts = _all_texts(input.after_scenes)
        if disqualified := self._disqualify(input, texts):
            return disqualified
        for index, scene in enumerate(input.after_scenes):
            hits = _contains_any(_texts(scene), self.success_markers)
            if len(hits) < self.minimum_hits:
                continue
            return SemanticOutcome(
                status="succeeded",
                verifier=self.name,
                reason=f"matched semantic markers: {hits}",
                confidence=min(0.99, 0.55 + 0.2 * len(hits)),
                verifier_version=self.version,
                verifier_hash=_source_hash(self.__class__),
                matched_evidence=hits,
                matched_frame_id=_after_frame_id(input, index),
                matched_scene_id=_after_scene_id(input, index),
                deterministic=False,
                observation_match=input.matched_by_observation,
            )
        texts = _all_texts(input.after_scenes)
        return SemanticOutcome(
            status="failed",
            verifier=self.name,
            reason="required semantic markers were absent",
            confidence=0.75,
            verifier_version=self.version,
            verifier_hash=_source_hash(self.__class__),
            missing_evidence=list(self.success_markers),
            deterministic=False,
            observation_match=input.matched_by_observation,
        )


class IOSControlCenterOpenedVerifier(BaseTextVerifier):
    name = "ios_control_center_opened"
    success_markers = (
        "勿扰模式",
        "专注模式",
        "未在播放",
        "正在播放",
        "屏幕镜像",
        "亮度",
        "音量",
        "飞行模式",
        "控制中心",
        "Focus",
        "Not Playing",
        "Screen Mirroring",
    )


class IOSNotificationCenterOpenedVerifier(BaseTextVerifier):
    name = "ios_notification_center_opened"
    success_markers = (
        "通知中心",
        "没有较早的通知",
        "无通知",
        "通知",
        "Notification Center",
        "No Older Notifications",
    )


class IOSAppSwitcherOpenedVerifier(BaseTextVerifier):
    name = "ios_app_switcher_opened"
    home_unexpected_disqualifies = True
    success_markers = (
        "App 切换器",
        "App切换器",
        "App Switcher",
    )

    def verify(self, input: VerifierInput) -> SemanticOutcome:
        texts = _all_texts(input.after_scenes)
        if disqualified := self._disqualify(input, texts):
            return disqualified
        for index, scene in enumerate(input.after_scenes):
            kind = scene.platform_scene_kind or scene.scene_type or scene.semantic_scene_type or ""
            if "switcher" in kind.lower() or scene.page_id == "ios_app_switcher":
                return SemanticOutcome(
                    status="succeeded",
                    verifier=self.name,
                    reason="after scene classified as app switcher",
                    confidence=0.9,
                    verifier_version=self.version,
                    verifier_hash=_source_hash(self.__class__),
                    matched_evidence=[kind or "ios_app_switcher"],
                    matched_frame_id=_after_frame_id(input, index),
                    matched_scene_id=_after_scene_id(input, index),
                    deterministic=False,
                    observation_match=input.matched_by_observation,
                )
        return super().verify(input)


class IOSHomeScreenVisibleVerifier(BaseTextVerifier):
    name = "ios_home_screen_visible"
    success_markers = HOME_SCREEN_MARKERS
    min_marker_count = 3

    def verify(self, input: VerifierInput) -> SemanticOutcome:
        texts = _all_texts(input.after_scenes)
        if disqualified := self._disqualify(input, texts):
            return disqualified
        for index, scene in enumerate(input.after_scenes):
            kind = scene.platform_scene_kind or scene.scene_type or scene.semantic_scene_type or ""
            if kind == "springboard" or scene.page_id == "ios/springboard":
                return SemanticOutcome(
                    status="succeeded",
                    verifier=self.name,
                    reason="after scene classified as SpringBoard",
                    confidence=0.9,
                    verifier_version=self.version,
                    verifier_hash=_source_hash(self.__class__),
                    matched_evidence=[kind or "ios/springboard"],
                    matched_frame_id=_after_frame_id(input, index),
                    matched_scene_id=_after_scene_id(input, index),
                    deterministic=False,
                    observation_match=input.matched_by_observation,
                )
        for index, scene in enumerate(input.after_scenes):
            hits = _contains_any(_texts(scene), self.success_markers)
            if len(set(hits)) < self.min_marker_count:
                continue
            return SemanticOutcome(
                status="succeeded",
                verifier=self.name,
                reason=f"matched home screen markers: {hits}",
                confidence=min(0.95, 0.55 + 0.1 * len(set(hits))),
                verifier_version=self.version,
                verifier_hash=_source_hash(self.__class__),
                matched_evidence=hits,
                matched_frame_id=_after_frame_id(input, index),
                matched_scene_id=_after_scene_id(input, index),
                deterministic=False,
                observation_match=input.matched_by_observation,
            )
        hits = _contains_any(texts, self.success_markers)
        return SemanticOutcome(
            status="failed",
            verifier=self.name,
            reason=f"home screen requires at least {self.min_marker_count} app/widget markers",
            confidence=0.75,
            verifier_version=self.version,
            verifier_hash=_source_hash(self.__class__),
            matched_evidence=hits,
            missing_evidence=list(self.success_markers),
            deterministic=False,
            observation_match=input.matched_by_observation,
        )


class TextInsertedVerifier(BaseTextVerifier):
    name = "text_inserted"

    def verify(self, input: VerifierInput) -> SemanticOutcome:
        expected = str(input.action.get("kwargs", {}).get("text") or input.action.get("metadata", {}).get("text") or "")
        texts = _all_texts(input.after_scenes)
        if disqualified := self._disqualify(input, texts):
            return disqualified
        if expected:
            for index, scene in enumerate(input.after_scenes):
                if not any(expected in text for text in _texts(scene)):
                    continue
                return SemanticOutcome(
                    status="succeeded",
                    verifier=self.name,
                    reason="expected text is visible after type action",
                    confidence=0.9,
                    verifier_version=self.version,
                    verifier_hash=_source_hash(self.__class__),
                    matched_evidence=[expected],
                    matched_frame_id=_after_frame_id(input, index),
                    matched_scene_id=_after_scene_id(input, index),
                    deterministic=False,
                    observation_match=input.matched_by_observation,
                )
        return SemanticOutcome(
            status="unknown",
            verifier=self.name,
            reason="typed text is not visible; target may be hidden or OCR-inaccessible",
            confidence=0.4,
            verifier_version=self.version,
            verifier_hash=_source_hash(self.__class__),
            missing_evidence=[expected] if expected else [],
            deterministic=False,
            observation_match=input.matched_by_observation,
        )


class SceneProgressedVerifier(BaseTextVerifier):
    name = "scene_progressed"

    def verify(self, input: VerifierInput) -> SemanticOutcome:
        texts = _all_texts(input.after_scenes)
        if disqualified := self._disqualify(input, texts):
            return disqualified
        scene_diff = input.scene_diff or {}
        scene_changed = bool(scene_diff.get("changed"))
        frame_changed = bool((input.frame_diff or {}).get("changed"))
        page_before = scene_diff.get("page_id_before")
        page_after = scene_diff.get("page_id_after")
        if scene_changed:
            if _looks_like_transient_carousel_change(input):
                return SemanticOutcome(
                    status="unknown",
                    verifier=self.name,
                    reason="scene text changed only in a likely transient carousel/review region",
                    confidence=0.35,
                    verifier_version=self.version,
                    verifier_hash=_source_hash(self.__class__),
                    matched_frame_id=_after_frame_id(input),
                    matched_scene_id=_after_scene_id(input),
                    deterministic=False,
                    observation_match=input.matched_by_observation,
                )
            if page_before and page_after and page_before == page_after:
                # Same page identity before and after: the text changed only
                # because the page scrolled / reflowed, not because the action
                # navigated. For a tap meant to open a new page this is NOT
                # progress — a stale or mis-registered tap that merely scrolled
                # the list would otherwise be scored a false success.
                return SemanticOutcome(
                    status="unknown",
                    verifier=self.name,
                    reason="scene text changed but page identity is unchanged (same-page scroll/reflow)",
                    confidence=0.35,
                    verifier_version=self.version,
                    verifier_hash=_source_hash(self.__class__),
                    matched_frame_id=_after_frame_id(input),
                    matched_scene_id=_after_scene_id(input),
                    deterministic=False,
                    observation_match=input.matched_by_observation,
                )
            return SemanticOutcome(
                status="succeeded",
                verifier=self.name,
                reason="scene changed after action",
                confidence=0.7,
                verifier_version=self.version,
                verifier_hash=_source_hash(self.__class__),
                matched_frame_id=_after_frame_id(input),
                matched_scene_id=_after_scene_id(input),
                deterministic=False,
                observation_match=input.matched_by_observation,
            )
        if frame_changed:
            return SemanticOutcome(
                status="unknown",
                verifier=self.name,
                reason="frame changed but OCR/page identity did not; semantic target not proven",
                confidence=0.35,
                verifier_version=self.version,
                verifier_hash=_source_hash(self.__class__),
                matched_frame_id=_after_frame_id(input),
                matched_scene_id=_after_scene_id(input),
                deterministic=False,
                observation_match=input.matched_by_observation,
            )
        return SemanticOutcome(
            status="unknown",
            verifier=self.name,
            reason="no scene or frame progress detected",
            confidence=0.5,
            verifier_version=self.version,
            verifier_hash=_source_hash(self.__class__),
            deterministic=False,
            observation_match=input.matched_by_observation,
        )


class ForegroundAppMatchesVerifier(SceneProgressedVerifier):
    name = "foreground_app_matches"

    def verify(self, input: VerifierInput) -> SemanticOutcome:
        texts = _all_texts(input.after_scenes)
        if disqualified := self._disqualify(input, texts):
            return disqualified
        candidates = _action_text_values(input.action, "app", "label", "target")
        if candidates:
            if _targets_settings_app(candidates):
                for index, scene in enumerate(input.after_scenes):
                    evidence = _settings_foreground_evidence(scene)
                    if evidence is None:
                        continue
                    return SemanticOutcome(
                        status="succeeded",
                        verifier=self.name,
                        reason=f"matched Settings foreground identity: {evidence}",
                        confidence=0.9,
                        verifier_version=self.version,
                        verifier_hash=_source_hash(self.__class__),
                        matched_evidence=[evidence],
                        matched_frame_id=_after_frame_id(input, index),
                        matched_scene_id=_after_scene_id(input, index),
                        deterministic=False,
                        observation_match=input.matched_by_observation,
                    )
            for index, scene in enumerate(input.after_scenes):
                hits = _contains_any(_texts(scene), candidates)
                if not hits:
                    continue
                return SemanticOutcome(
                    status="succeeded",
                    verifier=self.name,
                    reason=f"matched foreground app markers: {hits}",
                    confidence=0.9,
                    verifier_version=self.version,
                    verifier_hash=_source_hash(self.__class__),
                    matched_evidence=hits,
                    matched_frame_id=_after_frame_id(input, index),
                    matched_scene_id=_after_scene_id(input, index),
                    deterministic=False,
                    observation_match=input.matched_by_observation,
                )
            return SemanticOutcome(
                status="unknown",
                verifier=self.name,
                reason="foreground changed, but expected app markers were absent",
                confidence=0.45,
                verifier_version=self.version,
                verifier_hash=_source_hash(self.__class__),
                missing_evidence=candidates,
                deterministic=False,
                observation_match=input.matched_by_observation,
            )
        return super().verify(input)


class NavigationBackVerifier(SceneProgressedVerifier):
    name = "navigation_back"

    def verify(self, input: VerifierInput) -> SemanticOutcome:
        texts = _all_texts(input.after_scenes)
        if disqualified := self._disqualify(input, texts):
            return disqualified

        before_signature = _navigation_page_signature(input.before_command) or _navigation_page_signature(
            input.before_requested
        )
        comparable_after: list[tuple[int, str]] = []
        if before_signature:
            for index, scene in enumerate(input.after_scenes):
                after_signature = _navigation_page_signature(scene)
                if after_signature is None:
                    continue
                comparable_after.append((index, after_signature))
                if after_signature != before_signature:
                    after_title = _navigation_title(scene)
                    before_scene = input.before_command or input.before_requested
                    before_title = _navigation_title(before_scene)
                    if (
                        after_title
                        and after_title != before_title
                        and after_title in set(_navigation_body_texts(before_scene))
                    ):
                        return SemanticOutcome(
                            status="unknown",
                            verifier=self.name,
                            reason="navigation moved to a child page instead of going back",
                            confidence=0.65,
                            verifier_version=self.version,
                            verifier_hash=_source_hash(self.__class__),
                            matched_evidence=[after_title],
                            matched_frame_id=_after_frame_id(input, index),
                            matched_scene_id=_after_scene_id(input, index),
                            deterministic=False,
                            observation_match=input.matched_by_observation,
                        )
                    return SemanticOutcome(
                        status="succeeded",
                        verifier=self.name,
                        reason="navigation page identity changed after back action",
                        confidence=0.85,
                        verifier_version=self.version,
                        verifier_hash=_source_hash(self.__class__),
                        matched_evidence=[after_signature],
                        matched_frame_id=_after_frame_id(input, index),
                        matched_scene_id=_after_scene_id(input, index),
                        deterministic=False,
                        observation_match=input.matched_by_observation,
                    )
            if comparable_after and all(signature == before_signature for _index, signature in comparable_after):
                return SemanticOutcome(
                    status="unknown",
                    verifier=self.name,
                    reason="navigation page identity did not change after back action",
                    confidence=0.65,
                    verifier_version=self.version,
                    verifier_hash=_source_hash(self.__class__),
                    matched_evidence=[before_signature],
                    deterministic=False,
                    observation_match=input.matched_by_observation,
                )

        before_scene = input.before_command or input.before_requested
        for scene in input.after_scenes:
            overlap = _navigation_text_overlap(before_scene, scene)
            if overlap >= 0.75:
                return SemanticOutcome(
                    status="unknown",
                    verifier=self.name,
                    reason="navigation page text identity did not change after back action",
                    confidence=0.65,
                    verifier_version=self.version,
                    verifier_hash=_source_hash(self.__class__),
                    matched_evidence=_navigation_identity_texts(scene)[:10],
                    deterministic=False,
                    observation_match=input.matched_by_observation,
                )

        return SemanticOutcome(
            status="unknown",
            verifier=self.name,
            reason="missing comparable navigation page identity for back action",
            confidence=0.5,
            verifier_version=self.version,
            verifier_hash=_source_hash(self.__class__),
            deterministic=False,
            observation_match=input.matched_by_observation,
        )


class TapTargetEffectVerifier(SceneProgressedVerifier):
    name = "tap_target_effect"

    def verify(self, input: VerifierInput) -> SemanticOutcome:
        texts = _all_texts(input.after_scenes)
        if disqualified := self._disqualify(input, texts):
            return disqualified

        targets = _action_text_values(input.action, "target", "label", "text", "app")
        before_texts = _texts(input.before_command) or _texts(input.before_requested)
        before_signature = _navigation_page_signature(input.before_command) or _navigation_page_signature(
            input.before_requested
        )
        if targets and _looks_like_home_texts(before_texts) and before_signature:
            for scene in input.after_scenes:
                after_signature = _navigation_page_signature(scene)
                if after_signature != before_signature:
                    continue
                still_visible = _contains_any(_texts(scene), targets)
                if still_visible:
                    return SemanticOutcome(
                        status="unknown",
                        verifier=self.name,
                        reason="target label still visible on the same SpringBoard page after tap",
                        confidence=0.65,
                        verifier_version=self.version,
                        verifier_hash=_source_hash(self.__class__),
                        matched_evidence=still_visible,
                        deterministic=False,
                        observation_match=input.matched_by_observation,
                    )

        return super().verify(input)
