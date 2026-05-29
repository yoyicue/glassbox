"""glassbox/ios/gauntlet.py — cold-start interstitial gauntlet.

A new iOS app rarely opens straight onto its real UI. First it throws a gauntlet
of one-shot interstitials — system permission dialogs (TCC), onboarding /
what's-new screens, consent panels. A black-box agent must get past them before
it can perceive, annotate, or explore anything; this is the first blocker for
any "new app", more fundamental than what comes after.

`clear_cold_start_gauntlet` perceives, recognizes an interstitial by its text
markers plus a safe dismiss/advance button, taps the safest button, and repeats
until a stable app screen — or reports `blocked` (a login / paywall it must not
tap through) or `stuck`.

Safety: it only ever taps a deny / dismiss / advance button. It never grants a
permission, never logs in, never purchases — declining is the conservative,
side-effect-free choice for black-box exploration.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

# An interstitial is recognized by a context marker in the on-screen text AND a
# safe button. Requiring the marker keeps a real app screen that merely has a
# "继续"/"完成"/"Continue" button from being mistaken for the gauntlet.
#
# Both the zh-Hans and the en (English / region HK/US) marker sets live here so
# the same cold-start crawl clears a device in either UI language; English
# patterns are case-insensitive (re.I) since iOS title-cases dialog text.
_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # —— Chinese (zh-Hans) ——
    ("permission", re.compile(r"想(访问|使用|向你|查找|发送|连接)")),
    ("permission", re.compile(r"(访问|使用|读取)你的")),
    ("permission", re.compile(r"App\s*跟踪|跟踪你在|允许.{0,6}跟踪")),
    ("permission", re.compile(r"是否允许.{0,10}(通知|定位|位置|访问)")),
    ("permission", re.compile(r"(发送|接收).{0,4}通知")),
    ("onboarding", re.compile(r"欢迎使用|新功能|全新.{0,6}(体验|设计|功能|导览)")),
    ("consent", re.compile(r"服务条款|用户协议|隐私政策|继续即表示|隐私(声明|说明)")),
    # —— English (en) ——
    ("permission", re.compile(r"would like to (access|use|send|find|connect|add)", re.I)),
    ("permission", re.compile(r"\baccess your \w+", re.I)),
    ("permission", re.compile(r"track your activity|allow .{0,24}\bto track\b|tracking transparency", re.I)),
    ("permission", re.compile(r"(send|receive|enable|turn on)\b.{0,16}notifications?", re.I)),
    ("permission", re.compile(r"allow .{0,24}\bto (use|access)\b", re.I)),
    ("onboarding", re.compile(r"\bwelcome to\b|what'?s new|\bget started\b|new (features?|design|experience)", re.I)),
    ("consent", re.compile(r"terms (of service|of use|& conditions|and conditions)|privacy policy|privacy (notice|statement)|by (continuing|tapping)|user agreement", re.I)),
)

# Button-label taxonomy, scanned in this intent priority: a permission dialog is
# declined, a promo is dismissed, onboarding is advanced. Labels are matched by
# exact (stripped) equality, so each surface form must be listed; combined
# phrases ("Agree and Continue") precede their shorter forms ("Continue") so the
# most specific safe button wins. iOS renders the apostrophe as U+2019 (’) but
# OCR may emit a straight ', so both are listed for the en denials.
_DENY = (
    "不允许", "暂不允许", "不允许访问", "拒绝", "拒绝访问",
    "Don't Allow", "Don’t Allow", "Don't Allow Access", "Don’t Allow Access",
    "Ask App Not to Track", "Deny", "Block",
)
_DISMISS = (
    "以后再说", "暂不", "跳过", "取消", "关闭", "知道了", "我知道了", "稍后", "暂时不用",
    "Not Now", "Maybe Later", "No Thanks", "No, Thanks", "Skip", "Cancel",
    "Close", "Dismiss", "Later",
)
_ADVANCE = (
    "接受并继续", "同意并继续", "继续", "下一步", "开始使用", "同意", "完成", "好",
    "Agree and Continue", "Agree & Continue", "Accept and Continue", "Accept & Continue",
    "Continue", "Next", "Get Started", "Agree", "Accept", "Done", "Got It", "OK",
)
_INTENT_ORDER: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("deny", _DENY),
    ("dismiss", _DISMISS),
    ("advance", _ADVANCE),
)

# Buttons that must never be auto-tapped: they wall the app (login) or commit
# the user (purchase). An interstitial whose only buttons are these is `blocked`.
_BLOCKING = (
    "登录", "注册", "立即登录", "立即注册", "创建账户", "创建 Apple 账户",
    "使用 Apple 账户登录", "用 Apple 登录", "立即购买", "订阅", "升级", "续费",
    "Sign In", "Log In", "Login", "Sign Up", "Register", "Create Account",
    "Continue with Apple", "Sign in with Apple", "Subscribe", "Upgrade",
    "Buy Now", "Purchase", "Start Free Trial", "Restore Purchase",
)


@dataclass
class Interstitial:
    """A recognized cold-start interstitial and the safe button to act on."""

    kind: str            # "permission" | "onboarding" | "consent" | "blocked"
    action: str          # "deny" | "dismiss" | "advance" | "blocked"
    label: str
    button: Any | None   # UIElement to tap; None when blocked


@dataclass
class GauntletResult:
    """Outcome of clearing the cold-start gauntlet."""

    status: str                                  # "stable" | "blocked" | "stuck"
    handled: list[tuple[str, str]] = field(default_factory=list)  # (kind, label) per step
    blocked_kind: str = ""

    @property
    def steps(self) -> int:
        return len(self.handled)


def _texts(scene: Any) -> list[str]:
    return [(e.text or "").strip() for e in scene.elements if (e.text or "").strip()]


def _find_button(scene: Any, label: str):
    return next((e for e in scene.elements if (e.text or "").strip() == label), None)


def classify_interstitial(scene: Any) -> Interstitial | None:
    """Recognize a cold-start interstitial, or return None for a normal screen.

    Pure function (no device) — the detection is unit-testable.
    """
    blob = " ".join(_texts(scene))
    kind = next((k for k, pat in _MARKERS if pat.search(blob)), None)
    if kind is None:
        return None
    intent_order = _INTENT_ORDER
    if kind == "permission":
        # Permission prompts are conservative: deny or dismiss only. Buttons
        # such as "继续" / "接受并继续" may grant a capability or consent.
        intent_order = tuple(
            (action, labels)
            for action, labels in _INTENT_ORDER
            if action in {"deny", "dismiss"}
        )
    for action, labels in intent_order:
        for label in labels:
            button = _find_button(scene, label)
            if button is not None:
                return Interstitial(kind=kind, action=action, label=label, button=button)
    # marker present but no safe button — a login wall / paywall the agent
    # must not tap through.
    blocking = next((b for b in _BLOCKING if _find_button(scene, b) is not None), "")
    return Interstitial(kind="blocked", action="blocked", label=blocking, button=None)


def clear_cold_start_gauntlet(
    phone: Any, *, max_steps: int = 12, settle_s: float = 1.8
) -> GauntletResult:
    """Tap past every cold-start interstitial until a stable app screen.

    Returns a GauntletResult: `stable` (a normal screen reached), `blocked` (a
    login/paywall — cannot pass safely), or `stuck` (an interstitial would not
    clear within the step budget, or the same one keeps re-appearing).
    """
    handled: list[tuple[str, str]] = []
    repeats = 0
    for _ in range(max_steps):
        phone.invalidate_perceive_cache()
        scene = phone.perceive()
        intr = classify_interstitial(scene)
        if intr is None:
            return GauntletResult(status="stable", handled=handled)
        if intr.button is None:
            return GauntletResult(status="blocked", handled=handled, blocked_kind=intr.kind)
        if handled and handled[-1] == (intr.kind, intr.label):
            repeats += 1
            if repeats >= 2:  # tapped the same interstitial 3× — it will not clear
                return GauntletResult(status="stuck", handled=handled)
        else:
            repeats = 0
        phone.tap_xy(*intr.button.box.center)
        handled.append((intr.kind, intr.label))
        time.sleep(settle_s)
    return GauntletResult(status="stuck", handled=handled)
