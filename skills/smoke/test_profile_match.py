"""skills/smoke/test_profile_match.py

Unit tests for Tier 1+ white-box VC recognition — Profile.match_vc and its
wiring into Phone._apply_profile. Fully offline (no OCR / no VLM / no device).

Coverage:
  - the real demoapp profile recognises its device-list / control / settings
    screens from element texts alone
  - a non-app screen (iOS springboard) matches nothing
  - scene_type is a soft bonus: a strong text match still wins on a mismatch
  - a VC without `match` anchors never matches; an empty scene → None
  - Phone._apply_profile writes scene.current_vc (and is a no-op without a profile)
"""

from __future__ import annotations

import pathlib

import pytest
from pydantic import ValidationError

from glassbox.cognition.base import Box, Scene, UIElement
from glassbox.profile import AppMeta, KnownVC, Profile, VCMatch

_DEMOAPP = pathlib.Path(__file__).resolve().parents[2] / "profiles" / "demoapp" / "profile.yaml"


def _scene(texts: list[str], scene_type: str | None = None) -> Scene:
    els = [
        UIElement(type="text", box=Box(x=0, y=0, w=10, h=10),
                  text=t, confidence=0.9, element_id=i)
        for i, t in enumerate(texts)
    ]
    return Scene(frame_id=0, timestamp=0.0, elements=els, scene_type=scene_type)


@pytest.fixture(scope="module")
def demoapp() -> Profile:
    if not _DEMOAPP.exists():
        pytest.skip("demoapp profile absent (App-specific content, gitignored)")
    return Profile.from_yaml(_DEMOAPP)


# ─── real profile recognises real screens ────────────────────────────
@pytest.mark.smoke
def test_match_devicelist_from_ocr_text_only(demoapp):
    """OCR-stage match (no scene_type yet) still resolves the VC."""
    scene = _scene(["设备列表", "usg-pro-4", "重新扫描", "未找到设备?"])
    assert demoapp.match_vc(scene) == "ListViewController"


@pytest.mark.smoke
def test_match_control_screen(demoapp):
    scene = _scene(["AC Remote Control", "当前温度", "模式", "解锁"], scene_type="main")
    assert demoapp.match_vc(scene) == "MainViewController"


@pytest.mark.smoke
def test_match_control_screen_with_compacted_ocr_text(demoapp):
    scene = _scene(["ACRemoteControl", "当前 温度", "模式"], scene_type="main")
    assert demoapp.match_vc(scene) == "MainViewController"


@pytest.mark.smoke
def test_match_settings_screen(demoapp):
    scene = _scene(["设置", "华氏温度", "隐私政策", "恢复购买"], scene_type="settings")
    assert demoapp.match_vc(scene) == "SettingsViewController"


@pytest.mark.smoke
def test_match_paywall_by_scene_type(demoapp):
    """MainCoordinator has only a scene_type anchor — it still resolves."""
    scene = _scene(["获取折扣", "立即解锁"], scene_type="paywall")
    assert demoapp.match_vc(scene) == "MainCoordinator"


@pytest.mark.smoke
def test_non_app_screen_matches_nothing(demoapp):
    """The iOS springboard is not a VC of this app."""
    scene = _scene(["查找", "家庭", "通讯录", "Safari"], scene_type="main")
    assert demoapp.match_vc(scene) is None


@pytest.mark.smoke
def test_empty_scene_matches_nothing(demoapp):
    assert demoapp.match_vc(_scene([])) is None


# ─── matcher semantics on a synthetic profile ────────────────────────
def _synthetic() -> Profile:
    return Profile(
        app=AppMeta(name="X", bundle_id="com.x", version="1"),
        known_vcs=[
            KnownVC(name="HasAnchors",
                    match=VCMatch(all_text=["唯一标题"], scene_type=["settings"])),
            KnownVC(name="NoAnchors"),                      # match is None
            KnownVC(name="EmptyMatch", match=VCMatch()),     # all lists empty
        ],
    )


@pytest.mark.smoke
def test_scene_type_is_soft_bonus_not_a_filter():
    """A satisfied all_text anchor must still win when scene_type disagrees —
    the VLM's exact wording must never disqualify a strong text match."""
    prof = _synthetic()
    assert prof.match_vc(_scene(["唯一标题"], scene_type="login_form")) == "HasAnchors"
    assert prof.match_vc(_scene(["唯一标题"], scene_type="settings")) == "HasAnchors"


@pytest.mark.smoke
def test_text_anchors_use_ocr_normalization():
    prof = _synthetic()
    assert prof.match_vc(_scene(["唯一 标题"])) == "HasAnchors"


@pytest.mark.smoke
def test_match_vc_detail_returns_score_and_evidence():
    prof = _synthetic()

    detail = prof.match_vc_detail(_scene(["唯一标题"], scene_type="settings"))

    assert detail.vc_name == "HasAnchors"
    assert detail.score == 2
    assert detail.evidence == ["all_text:唯一标题", "scene_type:settings"]
    assert detail.ambiguous is False


@pytest.mark.smoke
def test_tied_vc_match_is_ambiguous():
    prof = Profile(
        app=AppMeta(name="X", bundle_id="com.x", version="1"),
        known_vcs=[
            KnownVC(name="First", match=VCMatch(all_text=["共享标题"])),
            KnownVC(name="Second", match=VCMatch(all_text=["共享标题"])),
        ],
    )

    detail = prof.match_vc_detail(_scene(["共享标题"]))

    assert detail.ambiguous is True
    assert detail.vc_name is None
    assert detail.tied_vcs == ["First", "Second"]
    assert prof.match_vc(_scene(["共享标题"])) is None


@pytest.mark.smoke
def test_vc_without_anchors_never_matches():
    prof = _synthetic()
    # nothing supplies the "唯一标题" anchor → no VC matches
    assert prof.match_vc(_scene(["别的文字"])) is None


@pytest.mark.smoke
def test_profile_registry_records_load_errors_and_strict_fails(tmp_path):
    from glassbox.profile import ProfileRegistry

    bad_dir = tmp_path / "bad"
    bad_dir.mkdir()
    (bad_dir / "profile.yaml").write_text("app: {name: Broken}\n", encoding="utf-8")

    reg = ProfileRegistry()
    assert reg.load_dir(tmp_path) == 0
    assert len(reg.load_errors) == 1

    reg = ProfileRegistry()
    with pytest.raises(ValidationError):
        reg.load_dir(tmp_path, strict=True)


@pytest.mark.smoke
def test_profile_registry_duplicate_bundle_is_deterministic_error(tmp_path):
    from glassbox.profile import ProfileRegistry

    for name in ("a", "b"):
        d = tmp_path / name
        d.mkdir()
        (d / "profile.yaml").write_text(
            """
app:
  name: X
  bundle_id: com.dup
  version: "1"
""",
            encoding="utf-8",
        )

    reg = ProfileRegistry()
    loaded = reg.load_dir(tmp_path)

    assert loaded == 1
    assert len(reg.load_errors) == 1
    assert "duplicate profile bundle_id" in reg.load_errors[0].error


@pytest.mark.smoke
def test_profile_registry_reload_replaces_stale_profiles(tmp_path):
    from glassbox.profile import ProfileRegistry

    active = tmp_path / "active"
    active.mkdir()
    (active / "profile.yaml").write_text(
        """
app:
  name: Active
  bundle_id: com.active
  version: "1"
""",
        encoding="utf-8",
    )
    stale = tmp_path / "stale"
    stale.mkdir()
    stale_profile = stale / "profile.yaml"
    stale_profile.write_text(
        """
app:
  name: Stale
  bundle_id: com.stale
  version: "1"
""",
        encoding="utf-8",
    )

    reg = ProfileRegistry()
    assert reg.load_dir(tmp_path) == 2
    stale_profile.unlink()

    assert reg.load_dir(tmp_path) == 1
    assert "com.active" in reg
    assert "com.stale" not in reg


# ─── Phone wiring ────────────────────────────────────────────────────
@pytest.mark.smoke
def test_apply_profile_sets_current_vc(demoapp):
    from glassbox.phone import Phone
    phone = Phone(source=None, ocr=None, effector=None, profile=demoapp)
    scene = _scene(["设备列表", "重新扫描"])
    phone._apply_profile(scene)
    assert scene.current_vc == "ListViewController"


@pytest.mark.smoke
def test_apply_profile_noop_without_profile():
    from glassbox.phone import Phone
    phone = Phone(source=None, ocr=None, effector=None, profile=None)
    scene = _scene(["设备列表"])
    phone._apply_profile(scene)
    assert scene.current_vc is None


@pytest.mark.smoke
def test_apply_profile_does_not_set_current_vc_for_ambiguous_match():
    from glassbox.phone import Phone

    prof = Profile(
        app=AppMeta(name="X", bundle_id="com.x", version="1"),
        known_vcs=[
            KnownVC(name="First", match=VCMatch(all_text=["共享标题"])),
            KnownVC(name="Second", match=VCMatch(all_text=["共享标题"])),
        ],
    )
    phone = Phone(source=None, ocr=None, effector=None, profile=prof)
    scene = _scene(["共享标题"])

    phone._apply_profile(scene)

    assert scene.current_vc is None
