"""Replay the committed iPhone Settings transition corpus against current code.

S1+S2 of docs/design/iphone_settings_transition.md. For every candidate tap
group in ``skills/golden/ios_settings_transitions`` this rebuilds the
expected_state with the **real production builder**
(``navigation._settings_row_expected_state`` →
``policy.page_id_route_label_candidates``, wired exactly as
``core._navigation_actions`` does) under the run's locale (en/CN), then runs
the **real comparator** (``glassbox.action.semantic_plan.verify_expected_state``
page_id membership) against the recorded after-scene ``page_id``.

Pin taxonomy (22 groups):

- ``PAGE_ID_GREEN`` — the after-scene's minted page_id is in the builder's
  ``any_of``: stays green. Includes ``Face ID与密码`` since S2: its minted
  ``settings/Face ID & Passcode`` was correct all along, only the alias was
  missing from the rack-shaped search-query tables (C1); the SectionVocab
  union supplies it.
- ``CORRECT_REJECTIONS`` — physically did not land on the target page
  (Apple-ID modal / stayed on root, No-SIM): stays rejected.
- ``FALSE_REJECTIONS_WRONG_MINT`` — physically entered, but the after-scene
  page_id was minted from a body row instead of the nav title (C2) — e.g.
  first-row titles or ``None``. The label-alias fix (S2) cannot and should not
  make these pass; they stay ``xfail(strict=True)`` until the minting fix (S3)
  / comparator normalization (S4) land in later PRs.
- ``VLM_ONLY_LIVE`` — verified live **only** through billed VLM escalation;
  the offline page_id comparator cannot reproduce that from the recorded
  after-scene (page_id ``None`` or a non-member mint), so the page_id-route
  replay is pinned rejected. (Spec nuance: "16/22 verified live" = the 10
  ``PAGE_ID_GREEN`` originals + these 6.)
"""

from __future__ import annotations

import json
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from glassbox.action.semantic_plan import ExpectedState, verify_expected_state
from glassbox.config import get_config
from skills.regression.ios_settings import core as walkthrough
from skills.regression.ios_settings import navigation as settings_navigation
from skills.regression.ios_settings.policy import IPadSettingsPolicy, SettingsPolicy

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = REPO_ROOT / "skills" / "golden" / "ios_settings_transitions"
GROUPS = {path.stem: json.loads(path.read_text()) for path in sorted(CORPUS_DIR.glob("grp_*.json"))}
IPAD_BASELINE = REPO_ROOT / "skills" / "regression" / "fixtures" / "reliability_baseline.json"

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
FALSE_REJECTIONS_WRONG_MINT = {
    "grp_000050",  # Wallpaper → minted None here (the retry frame minted 'CURRENT')
    "grp_000056",  # 声音与触感 → minted from first row 'Silent Mode'
    "grp_000084",  # Developer → minted from body section 'Paired Devices'
}
VLM_ONLY_LIVE = {
    "grp_000038",  # Display & Brightness (after page_id None)
    "grp_000041",  # Home Screen & App Library (mint differs only by slug casing — S4 territory)
    "grp_000053",  # 通知 (after page_id None; wrapper VLM matched)
    "grp_000059",  # 专注模式 (minted 'settings/Do Not Disturb')
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
                reason="false rejection: page_id minted from body text, not the nav "
                "title (C2) — flips with the minting fix (S3) / comparator "
                "normalization (S4), not with label aliases",
            )
        )
    return pytest.param(group_id, id=f"{group_id}-{GROUPS[group_id]['target']}", marks=marks)


@pytest.mark.smoke
def test_replay_categories_partition_the_corpus():
    categories = (PAGE_ID_GREEN, CORRECT_REJECTIONS, FALSE_REJECTIONS_WRONG_MINT, VLM_ONLY_LIVE)
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
            assert group["verified_via"] is None


@pytest.mark.smoke
@pytest.mark.parametrize("group_id", [_replay_param(group_id) for group_id in sorted(GROUPS)])
def test_transition_replay_against_current_builder(group_id, en_cn_locale):
    group = GROUPS[group_id]
    rebuilt = _rebuild_expected_state(group["target"])
    # The current builder must never lose aliases the run already had.
    recorded = set(group["expected_state"]["payload"]["any_of"])
    assert _expected_any_of(rebuilt) >= recorded

    scene = SimpleNamespace(page_id=group["after_scene"]["page_id"])
    outcome = verify_expected_state(ExpectedState.from_dict(rebuilt), scene)
    if group_id in PAGE_ID_GREEN or group_id in FALSE_REJECTIONS_WRONG_MINT:
        assert outcome.status == "succeeded", outcome.reason
    else:
        assert outcome.status == "failed", outcome.reason


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
