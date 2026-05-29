"""Smoke tests for the cold-start interstitial gauntlet (glassbox/ios/gauntlet.py)."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from glassbox.ios.gauntlet import (
    classify_interstitial,
    clear_cold_start_gauntlet,
)


@dataclass
class _Box:
    x: int
    y: int
    w: int = 80
    h: int = 30

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)


@dataclass
class _El:
    text: str
    box: _Box


@dataclass
class _Scene:
    elements: list


def _scene(*rows: tuple[str, int]) -> _Scene:
    return _Scene([_El(t, _Box(x=120, y=y)) for t, y in rows])


@pytest.mark.smoke
def test_classify_permission_dialog_picks_deny():
    scene = _scene(
        ("“照片”想访问你的通讯录。", 400),
        ("“照片”会使用“通讯录”来识别照片、相簿中的人物。", 440),
        ("不允许", 560),
        ("继续", 560),
    )
    intr = classify_interstitial(scene)
    assert intr is not None
    assert intr.kind == "permission"
    assert intr.action == "deny"            # 权限弹窗 → 拒绝,不点「继续」
    assert intr.label == "不允许"


@pytest.mark.smoke
def test_classify_onboarding_picks_advance():
    scene = _scene(
        ("欢迎使用“时钟”", 280),
        ("你可以轻点进一步了解,或者继续以开始使用。", 340),
        ("接受并继续", 840),
    )
    intr = classify_interstitial(scene)
    assert intr is not None
    assert intr.kind == "onboarding"
    assert intr.action == "advance"
    assert intr.label == "接受并继续"


@pytest.mark.smoke
def test_classify_normal_screen_returns_none():
    """普通 app 屏:有「继续」按钮但没有 interstitial 标记 → 不当成关卡。"""
    scene = _scene(("世界时钟", 140), ("北京", 220), ("继续", 600))
    assert classify_interstitial(scene) is None


@pytest.mark.smoke
def test_classify_login_wall_is_blocked():
    """有 interstitial 标记但只有登录/注册按钮 → blocked,不可安全穿越。"""
    scene = _scene(
        ("欢迎使用,请先登录以继续", 300),
        ("登录", 500),
        ("注册", 560),
    )
    intr = classify_interstitial(scene)
    assert intr is not None
    assert intr.kind == "blocked"
    assert intr.button is None


@pytest.mark.smoke
def test_classify_permission_dialog_does_not_advance_when_deny_is_missing():
    scene = _scene(
        ("是否允许“地图”访问你的位置?", 360),
        ("接受并继续", 520),
    )
    intr = classify_interstitial(scene)
    assert intr is not None
    assert intr.kind == "blocked"
    assert intr.button is None


@pytest.mark.smoke
def test_classify_promo_modal_is_dismissed():
    scene = _scene(
        ("App 跟踪:允许“X”跟踪你在其他公司App的活动?", 360),
        ("以后再说", 520),
        ("允许", 520),
    )
    intr = classify_interstitial(scene)
    assert intr is not None
    assert intr.action == "dismiss"          # 「以后再说」优先于「允许」
    assert intr.label == "以后再说"


# —— English (en) gauntlet — same conservative semantics in the other UI language ——
@pytest.mark.smoke
def test_classify_english_permission_picks_deny():
    scene = _scene(
        ("“Maps” Would Like to Use Your Location", 400),
        ("Your location is used to show nearby places.", 440),
        ("Don't Allow", 560),
        ("Allow Once", 560),
        ("Allow While Using App", 600),
    )
    intr = classify_interstitial(scene)
    assert intr is not None
    assert intr.kind == "permission"
    assert intr.action == "deny"             # permission → deny, never an "Allow*" button
    assert intr.label == "Don't Allow"


@pytest.mark.smoke
def test_classify_english_tracking_prompt_asks_not_to_track():
    scene = _scene(
        ("Allow “Acme” to track your activity across other companies' apps?", 360),
        ("Ask App Not to Track", 520),
        ("Allow", 520),
    )
    intr = classify_interstitial(scene)
    assert intr is not None
    assert intr.kind == "permission"
    assert intr.action == "deny"
    assert intr.label == "Ask App Not to Track"


@pytest.mark.smoke
def test_classify_english_onboarding_picks_advance():
    scene = _scene(
        ("Welcome to Clock", 280),
        ("Tap to learn more, or continue to get started.", 340),
        ("Continue", 840),
    )
    intr = classify_interstitial(scene)
    assert intr is not None
    assert intr.kind == "onboarding"
    assert intr.action == "advance"
    assert intr.label == "Continue"


@pytest.mark.smoke
def test_classify_english_normal_screen_returns_none():
    """A normal app screen with a "Continue" button but no marker → not a gauntlet."""
    scene = _scene(("World Clock", 140), ("Cupertino", 220), ("Continue", 600))
    assert classify_interstitial(scene) is None


@pytest.mark.smoke
def test_classify_english_login_wall_is_blocked():
    """English marker present but only sign-in buttons → blocked, cannot pass safely."""
    scene = _scene(
        ("Welcome to Acme", 300),
        ("Sign in to continue", 340),
        ("Sign In", 500),
        ("Sign Up", 560),
    )
    intr = classify_interstitial(scene)
    assert intr is not None
    assert intr.kind == "blocked"
    assert intr.button is None
    assert intr.label == "Sign In"


@pytest.mark.smoke
def test_classify_english_notification_prompt_dismissed_when_no_deny():
    """A "Send Notifications" promo with only Not Now / Allow → dismiss, not Allow."""
    scene = _scene(
        ("“Acme” Would Like to Send You Notifications", 360),
        ("Not Now", 520),
        ("Allow", 520),
    )
    intr = classify_interstitial(scene)
    assert intr is not None
    assert intr.kind == "permission"
    assert intr.action == "dismiss"          # Not Now beats Allow; permission never advances
    assert intr.label == "Not Now"


# —— loop tests with a scripted fake phone ——
class _FakePhone:
    """Returns a scripted sequence of scenes; records taps."""

    def __init__(self, scenes: list[_Scene]):
        self._scenes = scenes
        self._i = -1
        self.taps: list[tuple[int, int]] = []

    def invalidate_perceive_cache(self) -> None:
        pass

    def perceive(self) -> _Scene:
        self._i = min(self._i + 1, len(self._scenes) - 1)
        return self._scenes[self._i]

    def tap_xy(self, x: int, y: int) -> None:
        self.taps.append((x, y))


@pytest.mark.smoke
def test_clear_gauntlet_walks_to_stable_screen():
    """两道关卡(权限 → onboarding)→ 第三屏稳定。"""
    phone = _FakePhone([
        _scene(("“X”想访问你的位置。", 400), ("不允许", 560)),
        _scene(("欢迎使用“X”", 280), ("开始使用", 840)),
        _scene(("主页", 140), ("我的", 900)),          # stable
    ])
    result = clear_cold_start_gauntlet(phone, settle_s=0.0)
    assert result.status == "stable"
    assert result.handled == [("permission", "不允许"), ("onboarding", "开始使用")]
    assert len(phone.taps) == 2


@pytest.mark.smoke
def test_clear_gauntlet_reports_blocked_on_login_wall():
    phone = _FakePhone([
        _scene(("欢迎使用,登录后继续", 300), ("登录", 500)),
    ])
    result = clear_cold_start_gauntlet(phone, settle_s=0.0)
    assert result.status == "blocked"
    assert result.blocked_kind in ("onboarding", "consent", "permission", "blocked")


@pytest.mark.smoke
def test_clear_gauntlet_reports_stuck_when_interstitial_will_not_clear():
    """同一道权限弹窗反复出现、点不掉 → stuck,不无限循环。"""
    stuck = _scene(("“X”想访问你的通讯录。", 400), ("不允许", 560))
    phone = _FakePhone([stuck] * 10)
    result = clear_cold_start_gauntlet(phone, settle_s=0.0)
    assert result.status == "stuck"
    assert len(phone.taps) <= 3        # 连点 3 次同一关卡就判定卡死


@pytest.mark.smoke
def test_clear_english_gauntlet_walks_to_stable_screen():
    """An English permission → onboarding chain clears to a stable screen."""
    phone = _FakePhone([
        _scene(("“X” Would Like to Access Your Photos", 400), ("Don't Allow", 560)),
        _scene(("Welcome to X", 280), ("Get Started", 840)),
        _scene(("Home", 140), ("Me", 900)),          # stable
    ])
    result = clear_cold_start_gauntlet(phone, settle_s=0.0)
    assert result.status == "stable"
    assert result.handled == [("permission", "Don't Allow"), ("onboarding", "Get Started")]
    assert len(phone.taps) == 2
