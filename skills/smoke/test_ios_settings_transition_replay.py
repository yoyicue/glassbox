"""Replay the committed iPhone Settings transition corpus against current code.

S1+S2+S3+S4 (+S5a category pins) of docs/design/iphone_settings_transition.md.
For every candidate tap
group in ``skills/golden/ios_settings_transitions`` this rebuilds the
expected_state with the **real production builder**
(``navigation._settings_row_expected_state`` →
``policy.page_id_route_label_candidates``, wired exactly as
``core._navigation_actions`` does) under the run's locale (en/CN), **re-mints
the after-scene page_id with the current classifier**
(``glassbox.ios.scene.classify_ios_scene`` over the committed after-scene
elements — since S3 the mint is what the replay validates, not the recorded
string), then runs the **real comparator**
(``glassbox.action.semantic_plan.verify_expected_state`` page_id membership).

Pin taxonomy (22 groups):

- ``PAGE_ID_GREEN`` — the after-scene's minted page_id is in the builder's
  ``any_of``: stays green. Includes ``Face ID与密码`` since S2: its minted
  ``settings/Face ID & Passcode`` was correct all along, only the alias was
  missing from the rack-shaped search-query tables (C1); the SectionVocab
  union supplies it.
- ``CORRECT_REJECTIONS`` — physically did not land on the target page
  (Apple-ID modal / stayed on root, No-SIM): stays rejected.
- ``REMINT_GREEN_S3`` — physically entered, but the run minted the page_id
  from a body row instead of the visible nav title (C2): ``settings/Silent
  Mode`` over 'Sounds & Haptics', ``settings/Paired Devices`` over
  'Developer'. The S3 nav-band mint fix re-mints these correctly from the
  committed after-scene, so they are green now (was ``xfail(strict=True)``
  before S3; verified_via stays ``None`` — they were rejected live).
- ``FALSE_REJECTIONS_WRONG_MINT`` — physically entered but **not** fixed by
  S3: Wallpaper's committed after-scene carries no usable settings_detail
  evidence at all (16 sparse OCR elements → the classifier abstains, page_id
  ``None``; the ``settings/CURRENT`` body mint happened on wrapper retry
  frames that live only in ``notes``). Stays ``xfail(strict=True)``: S4's
  comparator fold cannot normalize a ``None`` mint — S5 (attribution)
  territory.
- ``VLM_ONLY_LIVE`` — verified live **only** through billed VLM escalation;
  the offline page_id comparator cannot reproduce that from the committed
  after-scene (re-mint is ``None`` or a non-member mint), so the page_id-route
  replay is pinned rejected. (Spec nuance: "16/22 verified live" = the 10
  ``PAGE_ID_GREEN`` originals + these 6.)

S4 (the fold-normalized comparator fallback) earns **no** re-mint pin flip:
every remaining rejected group re-mints ``None`` (nothing to normalize) or a
genuinely different page name (``settings/Do Not Disturb`` for 专注模式, which
the whole-identity fold rightly keeps rejected). What S4 does fix is the
*recorded verifier tokens* — the VLM-minted page_ids the run's comparator
rejected against the builder's ``any_of`` — pinned per token in
``test_s4_fold_comparator_verdicts_on_recorded_ledger_tokens`` below.
"""

from __future__ import annotations

import json
import re
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from glassbox.action.semantic_plan import ExpectedState, verify_expected_state
from glassbox.cognition import Box, Scene, UIElement
from glassbox.config import get_config
from glassbox.ios.scene import classify_ios_scene
from skills.regression.ios_settings import core as walkthrough
from skills.regression.ios_settings import navigation as settings_navigation
from skills.regression.ios_settings.policy import IPadSettingsPolicy, SettingsPolicy

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = REPO_ROOT / "skills" / "golden" / "ios_settings_transitions"
GROUPS = {path.stem: json.loads(path.read_text()) for path in sorted(CORPUS_DIR.glob("grp_*.json"))}
IPAD_BASELINE = REPO_ROOT / "skills" / "regression" / "fixtures" / "reliability_baseline.json"
# The slimmed corpus scenes drop viewport_size, so the replay re-supplies the
# run's frame size. The source run's letterbox crop jitters a few px per frame
# (448-452 x 977-992); the classifier's band math is insensitive at this scale.
RUN_VIEWPORT = (448, 990)

PAGE_ID_GREEN = {
    "grp_000023",  # 无线局域网 → settings/WLAN
    "grp_000026",  # 蓝牙 → settings/Bluetooth
    "grp_000031",  # 电池 → settings/Battery
    "grp_000034",  # 通用 → settings/General
    "grp_000044",  # Siri → settings/Siri
    "grp_000047",  # 待机显示 → settings/StandBy
    "grp_000062",  # 屏幕使用时间 → settings/Screen Time
    "grp_000072",  # 紧急 SOS → settings/Emergency SOS
    "grp_000075",  # 隐私与安全性 → settings/Privacy & Security
    "grp_000078",  # Game Center → settings/Game Center
    # S2 flip: minted 'settings/Face ID & Passcode' was correct; only the alias
    # was missing (C1). Was strict-xfail before the SectionVocab union landed.
    "grp_000065",  # Face ID与密码 → settings/Face ID & Passcode
}
CORRECT_REJECTIONS = {
    "grp_000014",  # Review Apple Account phone number → Apple-ID modal (page_id None)
    "grp_000029",  # 蜂窝网络 → stayed on settings/root (device has no SIM)
}
REMINT_GREEN_S3 = {
    "grp_000056",  # 声音与触感 → run minted first row 'Silent Mode'; S3 re-mints
    #                'settings/Sounds & Haptics' from the nav-band title
    "grp_000084",  # Developer → run minted body section 'Paired Devices'; S3
    #                re-mints 'settings/Developer' from the nav-band title
}
FALSE_REJECTIONS_WRONG_MINT = {
    "grp_000050",  # Wallpaper → committed after-scene re-mints None (classifier
    #                abstains on its 16 sparse elements; the 'CURRENT' body mint
    #                lives only on wrapper retry frames recorded in notes)
}
VLM_ONLY_LIVE = {
    "grp_000038",  # Display & Brightness (after page_id None)
    "grp_000041",  # Home Screen & App Library (recorded VLM-written page_id
    #                'com.apple.settings.HomeScreenAppLibrary' IS an S4 fold
    #                match, but the current classifier re-mints None from the
    #                committed OCR elements → stays VLM-only on replay)
    "grp_000053",  # 通知 (after page_id None; wrapper VLM matched)
    "grp_000059",  # 专注模式 (minted 'settings/Do Not Disturb' — a genuinely
    #                different page name; the whole-identity fold keeps it
    #                rejected, by design)
    "grp_000081",  # Apps (after page_id None; wrapper VLM matched)
    "grp_000095",  # Home Screen& App Library re-visit (after page_id None)
}


@pytest.fixture()
def en_cn_locale(monkeypatch):
    """The repro run's locale; same env+cache pattern as the policy tests."""
    monkeypatch.setenv("GLASSBOX_LANGUAGE", "en")
    monkeypatch.setenv("GLASSBOX_REGION", "CN")
    get_config.cache_clear()
    yield
    get_config.cache_clear()


def _production_actions(**overrides):
    return replace(walkthrough._navigation_actions(), **overrides)


def _rebuild_expected_state(target: str) -> dict:
    expected = settings_navigation._settings_row_expected_state(target, _production_actions())
    assert expected is not None and expected["kind"] == "page_id"
    return expected


def _expected_any_of(expected: dict) -> set[str]:
    payload = expected["payload"]
    return set(payload.get("any_of") or [payload["page_id"]])


def _replay_param(group_id: str):
    marks = []
    if group_id in FALSE_REJECTIONS_WRONG_MINT:
        marks.append(
            pytest.mark.xfail(
                strict=True,
                reason="false rejection neither the minting fix (S3) nor the "
                "comparator fold (S4) earns: the committed after-scene carries "
                "no usable settings_detail evidence, so the re-mint is None "
                "and there is nothing to normalize. S5a (landed) now "
                "classifies this mint_none and backs out instead of "
                "re-tapping, but that changes runtime recovery, not the "
                "offline re-mint — flipping needs a rig run (the back-out "
                "retry capturing a mintable frame) or an S5b/core change",
            )
        )
    return pytest.param(group_id, id=f"{group_id}-{GROUPS[group_id]['target']}", marks=marks)


def _scene_from_corpus(after_scene: dict) -> Scene:
    elements = []
    for raw in after_scene["elements"]:
        box = raw["box"]
        elements.append(
            UIElement(
                type=raw.get("type") or "text",
                box=Box(x=box["x"], y=box["y"], w=box["w"], h=box["h"]),
                text=raw.get("text"),
                confidence=0.9,
            )
        )
    scene = Scene(frame_id=0, timestamp=0.0, elements=elements)
    scene.viewport_size = RUN_VIEWPORT
    return scene


def _remint_page_id(after_scene: dict) -> str | None:
    return classify_ios_scene(_scene_from_corpus(after_scene)).page_id


@pytest.mark.smoke
def test_replay_categories_partition_the_corpus():
    categories = (
        PAGE_ID_GREEN,
        CORRECT_REJECTIONS,
        REMINT_GREEN_S3,
        FALSE_REJECTIONS_WRONG_MINT,
        VLM_ONLY_LIVE,
    )
    assert sum(len(category) for category in categories) == len(GROUPS) == 22
    assert set().union(*categories) == set(GROUPS)
    # Corpus self-consistency: the pin taxonomy must agree with the recorded
    # live evidence (see module docstring for the 10+6 split of the 16).
    for group_id, group in GROUPS.items():
        if group_id in VLM_ONLY_LIVE:
            assert group["verified_via"] == "vlm_escalation"
        elif group_id == "grp_000065":
            # Face ID与密码 was rejected live (the S2 alias did not exist yet);
            # it is green on replay only because of the SectionVocab union.
            assert group["verified_via"] is None
        elif group_id in PAGE_ID_GREEN:
            assert group["verified_via"] == "page_id"
        else:
            # REMINT_GREEN_S3 / FALSE_REJECTIONS_WRONG_MINT / CORRECT_REJECTIONS
            # were all rejected live.
            assert group["verified_via"] is None


@pytest.mark.smoke
@pytest.mark.parametrize("group_id", [_replay_param(group_id) for group_id in sorted(GROUPS)])
def test_transition_replay_against_current_builder(group_id, en_cn_locale):
    group = GROUPS[group_id]
    rebuilt = _rebuild_expected_state(group["target"])
    # The current builder must never lose aliases the run already had.
    recorded = set(group["expected_state"]["payload"]["any_of"])
    assert _expected_any_of(rebuilt) >= recorded

    scene = SimpleNamespace(page_id=_remint_page_id(group["after_scene"]))
    outcome = verify_expected_state(ExpectedState.from_dict(rebuilt), scene)
    if group_id in PAGE_ID_GREEN or group_id in REMINT_GREEN_S3:
        assert outcome.status == "succeeded", outcome.reason
    elif group_id in FALSE_REJECTIONS_WRONG_MINT:
        assert outcome.status == "succeeded", outcome.reason  # xfail(strict) pin
    else:
        assert outcome.status == "failed", outcome.reason


# ── S4: comparator fold fallback on the recorded ledger tokens ───────────────
#
# The committed corpus preserves every page_id token the run's verifier
# actually REJECTED ("got '<token>'" inside recorded_reason and
# notes.wrapper_attempts reasons), plus grp_000041's VLM-written after-scene
# page_id. This table pins, token by token, what the S4 fold-normalized
# comparator must now decide against the CURRENT builder's any_of:
#
# - "fold"  — accepted only via the fold fallback (the run false-rejected it):
#   the ios_settings_* ↔ com.apple.settings.* namespace-equivalence family and
#   the VLM's own face-id slug spellings. All are pages the run physically
#   entered.
# - "exact" — accepted by the exact fast path already (earned by S2's
#   SectionVocab union, not S4; kept here to show the full token inventory).
# - "rejected" — must STAY rejected: the Apple-ID modal tokens and empty mint
#   (grp_000014), the stayed-on-root No-SIM tokens (grp_000029 — note
#   'ios_settings_root' maps into the bundle namespace only, never to
#   'settings/root'), pre-S3 body mints ('settings/Silent Mode',
#   'settings/Paired Devices'), a genuinely different page name
#   ('settings/Do Not Disturb'), and word-order-reversed free-form VLM tokens
#   ('wallpaper_settings', 'developer_settings') — fold equality is
#   whole-identity, not bag-of-words.
S4_TOKEN_VERDICTS: dict[tuple[str, str], str] = {
    ("grp_000014", ""): "rejected",
    ("grp_000014", "apple_account_trusted_number_verification"): "rejected",
    ("grp_000014", "apple_id_trusted_number_verification"): "rejected",
    ("grp_000029", "ios_settings_root"): "rejected",
    ("grp_000029", "settings/root"): "rejected",
    ("grp_000041", "com.apple.settings.HomeScreenAppLibrary"): "fold",
    ("grp_000050", "ios_settings_wallpaper"): "fold",
    ("grp_000050", "wallpaper_settings"): "rejected",
    ("grp_000053", "ios_settings_notifications"): "fold",
    ("grp_000056", "com.apple.settings.sounds-haptics"): "exact",
    ("grp_000056", "settings/Silent Mode"): "rejected",
    ("grp_000059", "ios_settings_focus"): "fold",
    ("grp_000059", "settings/Do Not Disturb"): "rejected",
    ("grp_000065", "com.apple.settings.faceid_passcode"): "fold",
    ("grp_000065", "com.apple.settings.faceid-passcode"): "fold",
    ("grp_000065", "settings/Face ID & Passcode"): "exact",
    ("grp_000081", "ios_settings_apps"): "fold",
    ("grp_000084", "ios_settings_developer"): "fold",
    ("grp_000084", "developer_settings"): "rejected",
    ("grp_000084", "settings/Paired Devices"): "rejected",
}


def _recorded_rejected_tokens() -> set[tuple[str, str]]:
    got = re.compile(r"got '([^']*)'")
    tokens: set[tuple[str, str]] = set()
    for group_id, group in GROUPS.items():
        reasons = [str(group.get("recorded_reason") or "")]
        for attempt in (group.get("notes") or {}).get("wrapper_attempts", []) or []:
            reasons.append(str(attempt.get("reason") or ""))
        for reason in reasons:
            for token in got.findall(reason):
                tokens.add((group_id, token))
    # grp_000041's drifted identity lives in the recorded after-scene page_id
    # (the VLM matched live before the OCR-route comparator ever saw it).
    tokens.add(("grp_000041", str(GROUPS["grp_000041"]["after_scene"]["page_id"])))
    return tokens


@pytest.mark.smoke
def test_s4_fold_comparator_verdicts_on_recorded_ledger_tokens(en_cn_locale):
    # The table must cover exactly the tokens the committed corpus records —
    # no hand-typed inventory drift.
    assert _recorded_rejected_tokens() == set(S4_TOKEN_VERDICTS)

    for (group_id, token), verdict in sorted(S4_TOKEN_VERDICTS.items()):
        rebuilt = _rebuild_expected_state(GROUPS[group_id]["target"])
        outcome = verify_expected_state(
            ExpectedState.from_dict(rebuilt), SimpleNamespace(page_id=token)
        )
        if verdict == "rejected":
            assert outcome.status == "failed", (group_id, token, outcome.reason)
        else:
            assert outcome.status == "succeeded", (group_id, token, outcome.reason)
            if verdict == "fold":
                assert "fold-normalized" in outcome.reason, (group_id, token)
            else:
                assert outcome.reason == f"page_id matched: {token}"


@pytest.mark.smoke
def test_s3_remint_prefers_nav_band_title_on_corpus_scenes():
    """S3 pin: the re-minted identities themselves (not just comparator status)
    — the nav-band title beats the body-row mint the run recorded."""
    assert _remint_page_id(GROUPS["grp_000056"]["after_scene"]) == "settings/Sounds & Haptics"
    assert _remint_page_id(GROUPS["grp_000084"]["after_scene"]) == "settings/Developer"
    # Not earned by S3: Wallpaper's committed after-scene has no usable
    # settings_detail evidence — the classifier abstains rather than minting.
    assert _remint_page_id(GROUPS["grp_000050"]["after_scene"]) is None


# ── S5a: entered_unverified taxonomy on the corpus's rejected groups ──────────
#
# S5a's runtime classifier (navigation.classify_unverified_transition) decides
# whether a verification-rejected tap may be retried in place (same_page) or
# must back out first (left-the-root categories). The corpus pins its category
# for every group the CURRENT replay rejects — the only groups whose category
# is derivable offline (for the green groups the classifier never runs):
#
# - grp_000029 stayed on the root (No-SIM) → same_page (retry-in-place safe).
# - grp_000059 re-mints 'settings/Do Not Disturb', a real but non-matching
#   identity → name_mismatch (back-out).
# - every other rejected group re-mints None → mint_none (back-out). This
#   includes the Apple-ID modal (grp_000014): the corpus carries no
#   affirmative strong-home-evidence frame, so `unknown_scene` has no corpus
#   exemplar — it is pinned by a constructed-scene unit test in
#   test_ios_settings_navigation.py instead.
S5A_REPLAY_CATEGORY_PINS = {
    "grp_000014": "mint_none",
    "grp_000029": "same_page",
    "grp_000038": "mint_none",
    "grp_000041": "mint_none",
    "grp_000050": "mint_none",
    "grp_000053": "mint_none",
    "grp_000059": "name_mismatch",
    "grp_000081": "mint_none",
    "grp_000095": "mint_none",
}


@pytest.mark.smoke
def test_s5a_classifier_categories_on_replay_rejected_groups(en_cn_locale):
    # The pin table covers exactly the groups the replay rejects today.
    assert set(S5A_REPLAY_CATEGORY_PINS) == (
        CORRECT_REJECTIONS | FALSE_REJECTIONS_WRONG_MINT | VLM_ONLY_LIVE
    )
    root_scene = _scene_from_corpus(
        json.loads((CORPUS_DIR / "root_scene.json").read_text())
    )
    actions = _production_actions()
    for group_id, expected_category in sorted(S5A_REPLAY_CATEGORY_PINS.items()):
        after = _scene_from_corpus(GROUPS[group_id]["after_scene"])
        category = settings_navigation.classify_unverified_transition(
            root_scene, after, actions
        )
        assert category == expected_category, (group_id, category)


# ── S2 guards ────────────────────────────────────────────────────────────────


@pytest.mark.smoke
def test_zh_label_candidates_byte_identical(monkeypatch):
    """S2 guard (a): the zh output is byte-identical to the pre-S2 builder.

    Exact tuples pinned from the builder at 8eb69f7 (before the SectionVocab
    union): the zh vocab's terms are the zh canonicals themselves, so the
    union must add nothing under zh-Hans.
    """
    monkeypatch.setenv("GLASSBOX_LANGUAGE", "zh-Hans")
    monkeypatch.delenv("GLASSBOX_REGION", raising=False)
    get_config.cache_clear()
    try:
        policy = SettingsPolicy()
        assert policy.page_id_route_label_candidates("无线局域网") == ("无线局域网", "Wi-Fi", "WLAN")
        assert policy.page_id_route_label_candidates("声音与触感") == ("声音与触感", "Sounds")
        assert policy.page_id_route_label_candidates("Face ID与密码") == (
            "Face ID与密码",
            "Touch ID & Passcode",
        )
    finally:
        get_config.cache_clear()


def _ipad_baseline_payloads() -> dict[str, set[str]]:
    """Every page_id expected-state payload in the iPad floor fixture, keyed by
    the row label that built it."""
    payloads: dict[str, set[str]] = {}

    def walk(node):
        if isinstance(node, dict):
            expected = node.get("expected_state")
            if isinstance(expected, dict) and expected.get("kind") == "page_id":
                label = node.get("target")
                if label:
                    payloads.setdefault(str(label), set()).update(
                        str(item) for item in expected["payload"]["any_of"]
                    )
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(json.loads(IPAD_BASELINE.read_text()))
    return payloads


@pytest.mark.smoke
def test_ipad_baseline_payloads_remain_subset_of_builder(monkeypatch):
    """S2 guard (b): under en/HK the new builder's any_of ⊇ every payload the
    gate-load-bearing iPad floor recorded — widening must never drop aliases."""
    monkeypatch.setenv("GLASSBOX_LANGUAGE", "en")
    monkeypatch.setenv("GLASSBOX_REGION", "HK")
    get_config.cache_clear()
    try:
        payloads = _ipad_baseline_payloads()
        assert len(payloads) == 18  # distinct labels in the committed fixture
        actions = _production_actions(
            page_id_route_label_candidates=IPadSettingsPolicy().page_id_route_label_candidates,
        )
        for label, recorded in sorted(payloads.items()):
            rebuilt = set(settings_navigation._settings_row_page_id_candidates(label, actions))
            assert rebuilt >= recorded, (label, sorted(recorded - rebuilt))
    finally:
        get_config.cache_clear()


@pytest.mark.smoke
def test_page_id_route_consumes_vocab_widened_candidates(en_cn_locale):
    """S2 guard (c): the learned-route path (page_id_route_enabled) iterates the
    widened candidate list, including the SectionVocab-supplied alias."""

    class RoutePhone:
        def __init__(self) -> None:
            self.page_ids: list[str] = []

        def navigate_to_page(self, page_id, **_kwargs):
            self.page_ids.append(page_id)
            return SimpleNamespace(
                attempted=True, reached=False, reason="no_path", edge_count=0, replayed_ops=()
            )

    phone = RoutePhone()
    actions = _production_actions(
        page_id_route_enabled=True,
        action_intent=lambda *_args, **_kwargs: nullcontext(),
    )

    routed = settings_navigation._try_settings_row_page_id_route(phone, "Face ID与密码", actions)

    assert routed is None  # no learned path anywhere → fall back to the live row tap
    assert phone.page_ids == list(
        settings_navigation._settings_row_page_id_candidates("Face ID与密码", actions)
    )
    assert "settings/Face ID & Passcode" in phone.page_ids
