"""glassbox/profile.py — App profile schema (Tier 1+ white-box knowledge base)

A profile = the agent's prior knowledge of a **specific walkthrough target
App**. It comes from packet capture, static app analysis, or manual
curation. On a perception hit, the glassbox uses it to skip OCR, make
precise VC decisions, provide deep links, and so on.

Data flow:
    profile.yaml (hand-written or tool-generated)
            │
            ▼ Profile.from_yaml()
       Profile (pydantic validation)
            │
            ▼ glassbox loads it into ProfileRegistry
    perception / planner / effector query it on demand
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import BaseModel, Field, PrivateAttr

from glassbox.cognition.text_match import compact_text, ocr_compact_text

if TYPE_CHECKING:
    from glassbox.cognition.base import Scene


# ─── App metadata ────────────────────────────────────────────────────
class AppMeta(BaseModel):
    name: str
    bundle_id: str
    version: str
    min_ios: str | None = None
    platforms: list[str] = Field(default_factory=lambda: ["ios"])
    notes: str | None = None


# ─── View layer (VC topology) ────────────────────────────────────────
class Transition(BaseModel):
    """An edge from one VC to the next."""

    to: str                                 # target VC name
    via: str | None = None                   # triggering element (button id / cell id)
    condition: str | None = None             # runtime condition ("geoip_in_free_countries")
    is_deep_link: bool = False               # whether it can be triggered by a deep link


class VCMatch(BaseModel):
    """Anchors that identify this VC from a perceived Scene.

    iOS is a black box — there is no runtime VC introspection — so a VC is
    recognised by what shows on screen. `all_text` / `any_text` are matched
    against OCR element texts (available at Layer 1+2, no VLM needed);
    `scene_type` is matched against the Kimi scene_type when Layer 3 has run.
    """

    all_text: list[str] = Field(default_factory=list)   # every one must appear on screen
    any_text: list[str] = Field(default_factory=list)   # at least one must appear
    scene_type: list[str] = Field(default_factory=list)  # acceptable Kimi scene_type values


class VCMatchDetail(BaseModel):
    """Detailed result for matching a perceived scene to a known VC."""

    vc_name: str | None = None
    score: int = 0
    evidence: list[str] = Field(default_factory=list)
    ambiguous: bool = False
    tied_vcs: list[str] = Field(default_factory=list)


class ProfileLoadError(BaseModel):
    path: str
    error: str


class KnownElement(BaseModel):
    """A UI element of a VC, known ahead of time from an app profile.

    The profile gives the element's *identity* — its role, NSLocalizedString
    key, and which asset-catalog icons render it — but not its runtime pixel
    position. Perception matches a detected on-screen element back to one of
    these by icon (see glassbox/cognition/asset_match.py), then writes the
    resulting whitebox_hint onto the UIElement.
    """

    id: str                                  # stable semantic id ("mode_cold")
    role: str                                # "mode" / "fan_speed" / "swing" / ...
    label_key: str | None = None             # NSLocalizedString key ("Cold")
    assets: list[str] = Field(default_factory=list)   # asset-catalog icon names
    intent: str | None = None                # semantic action ("切换制冷")


class KnownVC(BaseModel):
    name: str                                # "SplashViewController"
    is_entry: bool = False                   # launch entry point?
    is_real_main: bool = False               # the real main screen (not the launch entry)?
    notes: str | None = None
    match: VCMatch | None = None              # anchors used to recognise this VC on screen
    known_elements: list[KnownElement] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)


# ─── Monetization ────────────────────────────────────────────────────
class PaywallPlacement(BaseModel):
    id: str                                  # "general_placement"
    ab_name: str | None = None                # "general"
    sku: str | None = None                    # "com.ac.week399"
    price: str | None = None                  # "$3.99/wk"
    role: str | None = None                   # "fallback" / "onboarding_main" / "review_state"


# ─── Analytics ───────────────────────────────────────────────────────
class AnalyticsEvent(BaseModel):
    name: str
    sdk: str | None = None                   # "amplitude" / "firebase" / "appsflyer"
    triggered_by: str | None = None           # which VC / action triggers it
    properties: list[str] = Field(default_factory=list)


# ─── Backend ─────────────────────────────────────────────────────────
class Endpoint(BaseModel):
    name: str                                # "midea_cloud_proxy"
    url: str                                 # full URL or a templated path
    method: str = "GET"
    auth: str | None = None                   # auth description
    notes: str | None = None


# ─── Protocols (used by device transport-style capabilities) ───────────────
class Protocol(BaseModel):
    name: str                                # e.g. "Vendor A LAN" / "Vendor B LAN"
    transport: str                           # "UDP 7000" / "TCP 6444"
    crypto: str | None = None                 # "AES-128-ECB"
    community_impl: str | None = None         # GitHub URL


# ─── Full Profile ────────────────────────────────────────────────────
class Profile(BaseModel):
    """An App profile, persistable via yaml.safe_dump / from_yaml."""

    schema_version: str = "0.1"
    app: AppMeta

    # profile-source / packet-capture workspace path (relative to this yaml file)
    source: str | None = None
    source_notes: str | None = None

    # directory holding the app's exported asset-catalog PNGs (relative to this
    # yaml file). Used by perception to icon-match known_elements.
    asset_root: str | None = None

    # absolute directory of the loaded yaml — set by from_yaml, used to resolve
    # the relative `source` / `asset_root` paths.
    _yaml_dir: Path | None = PrivateAttr(default=None)

    # view topology
    known_vcs: list[KnownVC] = Field(default_factory=list)
    deep_links: dict[str, str] = Field(default_factory=dict)

    # monetization
    paywall_placements: list[PaywallPlacement] = Field(default_factory=list)

    # analytics
    analytics_events: list[AnalyticsEvent] = Field(default_factory=list)

    # backend
    endpoints: list[Endpoint] = Field(default_factory=list)

    # protocols (optional, usually for device transport / device-communication projects)
    protocols: list[Protocol] = Field(default_factory=list)

    # localization (hand-filled short term, can be auto-extracted from
    # .strings/.xcstrings long term)
    # structure: lang_code -> { string_key: localized_text }
    localization: dict[str, dict[str, str]] = Field(default_factory=dict)

    # ─── Load / save ───────────────────────────────────────────────
    @classmethod
    def from_yaml(cls, path: str | Path) -> Profile:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        prof = cls.model_validate(data)
        prof._yaml_dir = Path(path).resolve().parent
        return prof

    def to_yaml(self) -> str:
        return yaml.safe_dump(
            self.model_dump(exclude_none=True, mode="json"),
            allow_unicode=True,
            sort_keys=False,
        )

    # ─── Query convenience methods ─────────────────────────────────
    def vc(self, name: str) -> KnownVC | None:
        return next((v for v in self.known_vcs if v.name == name), None)

    def entry_vc(self) -> KnownVC | None:
        return next((v for v in self.known_vcs if v.is_entry), None)

    def real_main_vc(self) -> KnownVC | None:
        return next((v for v in self.known_vcs if v.is_real_main), None)

    def paywall(self, placement_id: str) -> PaywallPlacement | None:
        return next((p for p in self.paywall_placements if p.id == placement_id), None)

    def endpoint(self, name: str) -> Endpoint | None:
        return next((e for e in self.endpoints if e.name == name), None)

    def match_vc_detail(self, scene: Scene) -> VCMatchDetail:
        """Identify which KnownVC the perceived Scene is showing, with evidence.

        Scores every VC's `match` anchors against the scene: `all_text` /
        `any_text` are hard filters (matched against OCR element texts);
        `scene_type` is a soft bonus (the VLM's exact wording must never
        *disqualify* an otherwise strong text match). Exact ties are ambiguous
        rather than resolved by profile YAML order.
        """
        texts = [e.text.strip() for e in scene.elements if e.text and e.text.strip()]
        candidates: list[VCMatchDetail] = []
        for vc in self.known_vcs:
            m = vc.match
            if m is None:
                continue
            detail = _score_vc_match(
                vc.name,
                m,
                texts,
                scene.semantic_scene_type or scene.scene_type,
            )
            if detail is not None and detail.score > 0:
                candidates.append(detail)
        if not candidates:
            return VCMatchDetail()
        candidates.sort(key=lambda item: item.score, reverse=True)
        best = candidates[0]
        tied = [c.vc_name for c in candidates if c.score == best.score and c.vc_name is not None]
        if len(tied) > 1:
            return best.model_copy(update={"vc_name": None, "ambiguous": True, "tied_vcs": tied})
        return best

    def match_vc(self, scene: Scene) -> str | None:
        """Compatibility wrapper returning only an unambiguous VC name."""
        detail = self.match_vc_detail(scene)
        return None if detail.ambiguous else detail.vc_name


    # ─── asset resolution (for icon-based whitebox matching) ───────
    def asset_path(self, asset_name: str) -> Path | None:
        """Absolute path of an asset-catalog PNG. None when asset_root is not
        configured, the loaded-from directory is unknown, or the file is gone
        (the asset workspace is an external, optional dependency)."""
        if not self.asset_root or self._yaml_dir is None:
            return None
        p = (self._yaml_dir / self.asset_root / f"{asset_name}.png").resolve()
        return p if p.exists() else None

    def vc_asset_candidates(self, vc_name: str) -> list[tuple[str, Path]]:
        """(asset_name, png_path) for every resolvable asset of a VC's
        known_elements — the candidate set for icon-matching on that VC."""
        vc = self.vc(vc_name)
        if vc is None:
            return []
        out: list[tuple[str, Path]] = []
        seen: set[str] = set()
        for el in vc.known_elements:
            for a in el.assets:
                if a in seen:
                    continue
                seen.add(a)
                p = self.asset_path(a)
                if p is not None:
                    out.append((a, p))
        return out

    def element_for_asset(self, vc_name: str, asset_name: str) -> KnownElement | None:
        """Reverse lookup: which KnownElement an asset belongs to (used after a
        successful icon match to recover the element's role / intent)."""
        vc = self.vc(vc_name)
        if vc is None:
            return None
        return next((el for el in vc.known_elements if asset_name in el.assets), None)


def _anchored(anchor: str, texts: list[str]) -> bool:
    """True when `anchor` appears as a substring of any normalized element text."""
    a = anchor.strip()
    if not a:
        return False
    compact_anchor = compact_text(a)
    ocr_anchor = ocr_compact_text(a)
    for text in texts:
        if a in text:
            return True
        if compact_anchor and compact_anchor in compact_text(text):
            return True
        if ocr_anchor and ocr_anchor in ocr_compact_text(text):
            return True
    return False


def _score_vc_match(
    vc_name: str,
    match: VCMatch,
    texts: list[str],
    scene_type: str | None,
) -> VCMatchDetail | None:
    evidence: list[str] = []
    for anchor in match.all_text:
        if not _anchored(anchor, texts):
            return None
        evidence.append(f"all_text:{anchor}")

    score = len(match.all_text)
    if match.any_text:
        any_hits = [anchor for anchor in match.any_text if _anchored(anchor, texts)]
        if not any_hits:
            return None
        score += len(any_hits)
        evidence.extend(f"any_text:{anchor}" for anchor in any_hits)

    if match.scene_type and scene_type and scene_type in match.scene_type:
        score += 1
        evidence.append(f"scene_type:{scene_type}")

    if score <= 0:
        return None
    return VCMatchDetail(vc_name=vc_name, score=score, evidence=evidence)


# ─── Profile registry — loaded entirely at agent startup ────────────
class ProfileRegistry:
    """Indexes all profiles by bundle_id. The agent scans the `profiles/` directory at startup to load them."""

    def __init__(self):
        self._by_bundle: dict[str, Profile] = {}
        self.load_errors: list[ProfileLoadError] = []

    def load_dir(self, profiles_dir: str | Path, *, strict: bool = False) -> int:
        """Recursively scan profiles_dir for all profile.yaml files. Returns the number loaded."""
        self.load_errors.clear()
        new_by_bundle: dict[str, Profile] = {}
        seen_paths: dict[str, Path] = {}
        for p in sorted(Path(profiles_dir).rglob("profile.yaml")):
            try:
                prof = Profile.from_yaml(p)
                existing = seen_paths.get(prof.app.bundle_id)
                if existing is not None:
                    raise ValueError(
                        f"duplicate profile bundle_id={prof.app.bundle_id!r}; "
                        f"already loaded from {existing}"
                    )
                seen_paths[prof.app.bundle_id] = p
                new_by_bundle[prof.app.bundle_id] = prof
            except Exception as e:
                self.load_errors.append(ProfileLoadError(path=str(p), error=str(e)))
                # avoid a logger dependency for now, just print
                print(f"[ProfileRegistry] failed to load {p}: {e}")
                if strict:
                    raise
        self._by_bundle = new_by_bundle
        return len(new_by_bundle)

    def get(self, bundle_id: str) -> Profile | None:
        return self._by_bundle.get(bundle_id)

    def __contains__(self, bundle_id: str) -> bool:
        return bundle_id in self._by_bundle

    def __len__(self) -> int:
        return len(self._by_bundle)
