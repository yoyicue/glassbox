"""Actuation reliability profile indexed by platform control buckets."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from glassbox.action.actuation import ActuationMethod

ControlActuability = Literal["unknown", "actuatable", "unactuatable"]


@dataclass
class CalibratedOffset:
    space: Literal["roi_normalized", "frame_px"]
    mean: tuple[float, float]
    variance: tuple[float, float]
    n: int
    confidence: float
    calibration_version: int
    last_updated: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "space": self.space,
            "mean": list(self.mean),
            "variance": list(self.variance),
            "n": self.n,
            "confidence": self.confidence,
            "calibration_version": self.calibration_version,
            "last_updated": self.last_updated,
        }


_NEGATIVE_LABELS = ("missed", "landed_noop")


def _identity_key(identity: Any) -> str | None:
    """Stable key for a target identity (CUQ-1.2 distinct-control tracking)."""
    if not isinstance(identity, dict):
        return None
    for field_name in ("intent", "text", "element_id", "role", "type"):
        value = identity.get(field_name)
        if value:
            return f"{field_name}:{value}"
    return None


@dataclass
class MethodStats:
    command_tries: int = 0
    landed_attempts: int = 0
    semantic_ok: int = 0
    by_label: dict[str, int] = field(default_factory=dict)
    offset: CalibratedOffset | None = None
    last_outcome: str = "unknown"
    updated_at: str = ""
    source: str = "learned"
    # CUQ-1.2: distinct target identities that produced a negative (missed /
    # landed_noop). The unactuatable verdict requires negatives from several
    # *different* controls so one stubborn target can't poison the whole coarse
    # (role, size, zone) bucket on a few transient perception misses.
    negative_identities: set[str] = field(default_factory=set)

    def record(
        self,
        *,
        landing_signal: str | None,
        label: str,
        target_identity: Any = None,
    ) -> None:
        self.command_tries += 1
        if landing_signal == "landed":
            self.landed_attempts += 1
        if label == "landed_ok":
            self.semantic_ok += 1
        if label in _NEGATIVE_LABELS:
            identity = _identity_key(target_identity)
            if identity is not None:
                self.negative_identities.add(identity)
        self.by_label[label] = self.by_label.get(label, 0) + 1
        self.last_outcome = label
        self.updated_at = datetime.now().astimezone().isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_tries": self.command_tries,
            "landed_attempts": self.landed_attempts,
            "semantic_ok": self.semantic_ok,
            "by_label": dict(sorted(self.by_label.items())),
            "offset": self.offset.to_dict() if self.offset else None,
            "last_outcome": self.last_outcome,
            "updated_at": self.updated_at,
            "source": self.source,
            "negative_identities": sorted(self.negative_identities),
        }


@dataclass
class ControlClassEntry:
    methods: dict[ActuationMethod, MethodStats] = field(default_factory=dict)
    actuability: ControlActuability = "unknown"
    calibration_version: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "methods": {method: stats.to_dict() for method, stats in sorted(self.methods.items())},
            "actuability": self.actuability,
            "calibration_version": self.calibration_version,
        }


class ActuationProfile:
    """In-memory profile with deterministic JSON export."""

    schema_version = 1

    def __init__(
        self,
        *,
        platform: str = "ios",
        os_version: str = "unknown",
        device_model: str = "unknown",
    ):
        self.platform = platform
        self.os_version = os_version
        self.device_model = device_model
        self.entries: dict[tuple[str, str, str, str, str, str], ControlClassEntry] = {}

    def record_attempt(
        self,
        *,
        control_bucket: dict[str, str] | None,
        method: str | None,
        landing_signal: str | None,
        label: str | None,
        target_identity: Any = None,
    ) -> None:
        if not control_bucket or method not in {"mouse_tap", "keyboard_focus_activate"} or not label:
            return
        key = self._key(control_bucket)
        entry = self.entries.setdefault(key, ControlClassEntry())
        stats = entry.methods.setdefault(method, MethodStats())  # type: ignore[arg-type]
        stats.record(landing_signal=landing_signal, label=label, target_identity=target_identity)
        self._refresh_actuability(entry, method=method)

    def record_correction_pair(
        self,
        *,
        control_bucket: dict[str, str] | None,
        method: str | None,
        missed_point: dict[str, Any] | None,
        landed_point: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not control_bucket or method != "mouse_tap":
            return None
        if not isinstance(missed_point, dict) or not isinstance(landed_point, dict):
            return None
        try:
            missed_x = float(missed_point["x"])
            missed_y = float(missed_point["y"])
            landed_x = float(landed_point["x"])
            landed_y = float(landed_point["y"])
        except (KeyError, TypeError, ValueError):
            return None
        space = str(landed_point.get("space") or missed_point.get("space") or "frame_px")
        if space not in {"frame_px", "roi_normalized"}:
            space = "frame_px"
        delta = (landed_x - missed_x, landed_y - missed_y)
        # CUQ-3.8: reject an implausibly large correction. The candidate-point
        # retry only nudges the tap a small amount, so a large missed->landed
        # delta means the "landed" tap was a different element (a mis-pairing),
        # not a calibration offset — and a single such pair would otherwise bias
        # the whole shared bucket.
        if _correction_is_outlier(delta, space):
            return None
        key = self._key(control_bucket)
        entry = self.entries.setdefault(key, ControlClassEntry())
        stats = entry.methods.setdefault("mouse_tap", MethodStats())
        stats.offset = _updated_offset(stats.offset, delta=delta, space=space)
        return {
            "control_bucket": control_bucket,
            "method": method,
            "missed_target_point": missed_point,
            "landed_target_point": landed_point,
            "delta": [delta[0], delta[1]],
            "space": space,
        }

    def entry_for_bucket(self, control_bucket: dict[str, str] | None) -> ControlClassEntry | None:
        if not control_bucket:
            return None
        return self.entries.get(self._key(control_bucket))

    def offset_for_bucket(
        self,
        control_bucket: dict[str, str] | None,
        *,
        method: str = "mouse_tap",
        min_samples: int = 1,
        min_confidence: float = 0.2,
    ) -> CalibratedOffset | None:
        entry = self.entry_for_bucket(control_bucket)
        if entry is None:
            return None
        stats = entry.methods.get(method)  # type: ignore[arg-type]
        if stats is None or stats.offset is None:
            return None
        offset = stats.offset
        if offset.n < min_samples or offset.confidence < min_confidence:
            return None
        return offset

    def should_skip_bucket(
        self,
        control_bucket: dict[str, str] | None,
        *,
        method: str = "mouse_tap",
    ) -> tuple[bool, str | None]:
        entry = self.entry_for_bucket(control_bucket)
        if entry is None:
            return False, None
        stats = entry.methods.get(method)  # type: ignore[arg-type]
        if stats is None:
            return False, None
        if _method_is_unactuatable(stats):
            return True, "unactuatable"
        return False, None

    def best_method_for_bucket(
        self,
        control_bucket: dict[str, str] | None,
        *,
        default: str = "mouse_tap",
    ) -> str:
        entry = self.entry_for_bucket(control_bucket)
        if entry is None:
            return default
        scored = [
            (method, _method_score(stats))
            for method, stats in entry.methods.items()
            if stats.command_tries > 0 and not _method_is_unactuatable(stats)
        ]
        if not scored:
            return default
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[0][0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "platform": self.platform,
            "os_version": self.os_version,
            "device_model": self.device_model,
            "entries": [
                {
                    "key": {
                        "platform": key[0],
                        "os_version": key[1],
                        "device_model": key[2],
                        "control_role": key[3],
                        "size_bucket": key[4],
                        "region_zone": key[5],
                    },
                    "value": entry.to_dict(),
                }
                for key, entry in sorted(self.entries.items())
            ],
        }

    def apply_seed(self, payload: dict[str, Any]) -> None:
        seeded = ActuationProfile.from_dict({
            **payload,
            "platform": payload.get("platform") or self.platform,
            "os_version": payload.get("os_version") or self.os_version,
            "device_model": payload.get("device_model") or self.device_model,
        })
        for key, entry in seeded.entries.items():
            target = self.entries.setdefault(key, ControlClassEntry())
            target.actuability = entry.actuability
            target.calibration_version = entry.calibration_version
            for method, stats in entry.methods.items():
                if method not in target.methods:
                    stats.source = "seed"
                    target.methods[method] = stats

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _key(self, control_bucket: dict[str, str]) -> tuple[str, str, str, str, str, str]:
        return (
            self.platform,
            self.os_version,
            self.device_model,
            str(control_bucket.get("control_role") or "unknown"),
            str(control_bucket.get("size_bucket") or "unknown"),
            str(control_bucket.get("region_zone") or "unknown"),
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ActuationProfile:
        profile = cls(
            platform=str(payload.get("platform") or "ios"),
            os_version=str(payload.get("os_version") or "unknown"),
            device_model=str(payload.get("device_model") or "unknown"),
        )
        for item in payload.get("entries", []) or []:
            if not isinstance(item, dict):
                continue
            key_payload = item.get("key") or {}
            value_payload = item.get("value") or {}
            if not isinstance(key_payload, dict) or not isinstance(value_payload, dict):
                continue
            key = (
                str(key_payload.get("platform") or profile.platform),
                str(key_payload.get("os_version") or profile.os_version),
                str(key_payload.get("device_model") or profile.device_model),
                str(key_payload.get("control_role") or "unknown"),
                str(key_payload.get("size_bucket") or "unknown"),
                str(key_payload.get("region_zone") or "unknown"),
            )
            entry = ControlClassEntry(
                actuability=str(value_payload.get("actuability") or "unknown"),  # type: ignore[arg-type]
                calibration_version=int(value_payload.get("calibration_version", 0) or 0),
            )
            for method, stats_payload in (value_payload.get("methods") or {}).items():
                if method not in {"mouse_tap", "keyboard_focus_activate"} or not isinstance(stats_payload, dict):
                    continue
                offset_payload = stats_payload.get("offset")
                offset = _offset_from_dict(offset_payload) if isinstance(offset_payload, dict) else None
                stats = MethodStats(  # type: ignore[literal-required]
                    command_tries=int(stats_payload.get("command_tries", 0) or 0),
                    landed_attempts=int(stats_payload.get("landed_attempts", 0) or 0),
                    semantic_ok=int(stats_payload.get("semantic_ok", 0) or 0),
                    by_label={str(k): int(v) for k, v in (stats_payload.get("by_label") or {}).items()},
                    offset=offset,
                    last_outcome=str(stats_payload.get("last_outcome") or "unknown"),
                    updated_at=str(stats_payload.get("updated_at") or ""),
                    source=str(stats_payload.get("source") or "learned"),
                    negative_identities={
                        str(item) for item in (stats_payload.get("negative_identities") or [])
                    },
                )
                # CUQ-3.6: persist the learned calibration offset across sessions,
                # but do NOT carry a stale "unactuatable" verdict — a transient
                # rig hiccup that disabled a control class last run must not
                # silently disable it again on load. Reset only the
                # unactuatable-driving evidence for would-be-unactuatable buckets;
                # actuatable buckets keep their full stats.
                if _method_is_unactuatable(stats):
                    stats.command_tries = 0
                    stats.landed_attempts = 0
                    stats.by_label = {}
                    stats.negative_identities = set()
                    stats.last_outcome = "unknown"
                    if entry.actuability == "unactuatable":
                        entry.actuability = "unknown"  # type: ignore[assignment]
                entry.methods[method] = stats
            # Audit fix: keep the persisted actuability label consistent with the
            # current (possibly stricter, post-CUQ-1.2) gate. A bucket persisted
            # "unactuatable" under the OLD gate whose loaded stats no longer
            # qualify must not keep the stale label — should_skip_bucket recomputes
            # from stats, so a disagreeing label would only mislead exports/audit.
            if entry.actuability == "unactuatable" and not any(
                _method_is_unactuatable(s) for s in entry.methods.values()
            ):
                entry.actuability = "unknown"  # type: ignore[assignment]
            profile.entries[key] = entry
        return profile

    @staticmethod
    def _refresh_actuability(entry: ControlClassEntry, *, method: str) -> None:
        stats = entry.methods.get(method)  # type: ignore[arg-type]
        if stats is None:
            return
        if any(method_stats.semantic_ok > 0 for method_stats in entry.methods.values()):
            entry.actuability = "actuatable"
            return
        if entry.methods and all(_method_is_unactuatable(method_stats) for method_stats in entry.methods.values()):
            entry.actuability = "unactuatable"


def actuation_profile_path(
    *,
    platform: str,
    device_model: str,
    os_version: str = "unknown",
    profile_dir: str | Path | None = None,
) -> Path:
    base = Path(profile_dir) if profile_dir else Path(__file__).resolve().parents[2] / "memory" / "actuation"
    safe = "_".join(_safe_part(part) for part in (platform, os_version, device_model))
    return base / f"{safe}.json"


def load_actuation_profile(
    *,
    platform: str = "ios",
    device_model: str = "unknown",
    os_version: str = "unknown",
    profile_dir: str | Path | None = None,
) -> ActuationProfile:
    path = actuation_profile_path(
        platform=platform,
        os_version=os_version,
        device_model=device_model,
        profile_dir=profile_dir,
    )
    if not path.exists():
        return ActuationProfile(platform=platform, os_version=os_version, device_model=device_model)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        profile = ActuationProfile.from_dict(payload)
    except Exception as exc:
        print(f"[actuation] failed to load {path}: {exc} — cold start")
        return ActuationProfile(platform=platform, os_version=os_version, device_model=device_model)
    if (
        profile.platform != platform
        or profile.os_version != os_version
        or profile.device_model != device_model
    ):
        return ActuationProfile(platform=platform, os_version=os_version, device_model=device_model)
    return profile


def save_actuation_profile(profile: ActuationProfile, *, profile_dir: str | Path | None = None) -> Path:
    path = actuation_profile_path(
        platform=profile.platform,
        os_version=profile.os_version,
        device_model=profile.device_model,
        profile_dir=profile_dir,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    profile.save(path)
    return path


def _updated_offset(
    current: CalibratedOffset | None,
    *,
    delta: tuple[float, float],
    space: str,
) -> CalibratedOffset:
    now = datetime.now().astimezone().isoformat()
    if current is None or current.space != space:
        return CalibratedOffset(
            space=space,  # type: ignore[arg-type]
            mean=delta,
            variance=(0.0, 0.0),
            n=1,
            confidence=0.5,
            calibration_version=0,
            last_updated=now,
        )
    old_n = current.n
    new_n = old_n + 1
    mean_x = current.mean[0] + (delta[0] - current.mean[0]) / new_n
    mean_y = current.mean[1] + (delta[1] - current.mean[1]) / new_n
    var_x = ((old_n - 1) * current.variance[0] + (delta[0] - current.mean[0]) * (delta[0] - mean_x)) / max(1, old_n)
    var_y = ((old_n - 1) * current.variance[1] + (delta[1] - current.mean[1]) * (delta[1] - mean_y)) / max(1, old_n)
    variance = (max(0.0, var_x), max(0.0, var_y))
    confidence = min(0.95, 0.3 + 0.15 * new_n)
    return CalibratedOffset(
        space=current.space,
        mean=(mean_x, mean_y),
        variance=variance,
        n=new_n,
        confidence=confidence,
        calibration_version=current.calibration_version,
        last_updated=now,
    )


# CUQ-1.2: a coarse (role, size, zone) bucket is shared across many unrelated
# controls, and a "missed" is a low-threshold ROI pixel diff on a possibly-stale
# frame. Require more evidence before disabling a whole control class: at least
# this many all-negative tries, AND (when identity is known) negatives from at
# least this many DISTINCT controls, so transient perception misses on one
# stubborn target cannot silently poison the class.
_MIN_UNACTUATABLE_TRIES = 5
_MIN_DISTINCT_NEGATIVES = 2
# Escape hatch (audit fix): the >=2-distinct-identities rule prevents one stubborn
# target from poisoning a class, but a control that fails EVERY try past this hard
# cap is genuinely dead even under a single identity — disable it so it is not
# re-probed forever.
_HARD_UNACTUATABLE_TRIES = 10


# CUQ-3.8: a legitimate tap-landing correction is small (candidate-point nudge);
# a correction beyond these bounds is a mis-pairing, not calibration signal.
_MAX_CORRECTION_FRAME_PX = 150.0
_MAX_CORRECTION_ROI_NORM = 0.5


def _correction_is_outlier(delta: tuple[float, float], space: str) -> bool:
    magnitude = (delta[0] ** 2 + delta[1] ** 2) ** 0.5
    limit = _MAX_CORRECTION_ROI_NORM if space == "roi_normalized" else _MAX_CORRECTION_FRAME_PX
    return magnitude > limit


def _method_is_unactuatable(stats: MethodStats) -> bool:
    if stats.command_tries < _MIN_UNACTUATABLE_TRIES or stats.semantic_ok > 0:
        return False
    negative = stats.by_label.get("missed", 0) + stats.by_label.get("landed_noop", 0)
    if negative < stats.command_tries:
        return False
    # When identity info is available, require negatives from multiple distinct
    # controls; fall back to the count-only gate when identities were not
    # recorded (older artifacts / paths that omit target_identity).
    if stats.negative_identities:
        if len(stats.negative_identities) >= _MIN_DISTINCT_NEGATIVES:
            return True
        # Single repeating identity: still disable once it fails past the hard
        # cap, so a genuinely-dead control is not re-probed every session forever.
        return stats.command_tries >= _HARD_UNACTUATABLE_TRIES
    return True


def _method_score(stats: MethodStats) -> tuple[float, float, int]:
    command_tries = max(1, stats.command_tries)
    semantic_rate = stats.semantic_ok / command_tries
    landing_rate = stats.landed_attempts / command_tries
    return semantic_rate, landing_rate, stats.command_tries


def _offset_from_dict(payload: dict[str, Any]) -> CalibratedOffset:
    mean = payload.get("mean") or [0.0, 0.0]
    variance = payload.get("variance") or [0.0, 0.0]
    return CalibratedOffset(
        space=str(payload.get("space") or "frame_px"),  # type: ignore[arg-type]
        mean=(float(mean[0]), float(mean[1])),
        variance=(float(variance[0]), float(variance[1])),
        n=int(payload.get("n", 0) or 0),
        confidence=float(payload.get("confidence", 0.0) or 0.0),
        calibration_version=int(payload.get("calibration_version", 0) or 0),
        last_updated=str(payload.get("last_updated") or ""),
    )


def _safe_part(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value) or "unknown"
