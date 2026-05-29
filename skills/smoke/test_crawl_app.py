"""Smoke tests for the generic cold-start crawl (skills/crawl/crawl_app.py)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from glassbox.effector import ActionResult
from skills.crawl.crawl_app import crawl_app


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
    type: str = "button"
    box: _Box = None  # type: ignore[assignment]


@dataclass
class _Scene:
    elements: list


@dataclass
class _Frame:
    img: object


def _box_for(i: int) -> _Box:
    return _Box(40, 100 + 60 * i)


class _FakeApp:
    """Tiny stateful fake iOS app for crawl tests.

    `screens` maps a screen name to a list of (label, target | None) — a None
    target is a non-navigating control (a tap there is a noop). Navigation
    pushes a back stack so `back_gesture` unwinds it.
    """

    def __init__(self, screens: dict[str, list[tuple[str, str | None]]], start: str = "home"):
        self._screens = screens
        self._start = start
        self._cur = start
        self._stack: list[str] = []
        self.taps: list[tuple[int, int]] = []

    # —— phone interface used by crawl_app ——
    def invalidate_perceive_cache(self) -> None:
        pass

    def perceive(self) -> _Scene:
        rows = self._screens[self._cur]
        return _Scene([_El(label, "button", _box_for(i)) for i, (label, _) in enumerate(rows)])

    def snapshot(self) -> _Frame:
        return _Frame(img=np.zeros((956, 440, 3), dtype=np.uint8))

    def tap_xy(self, x: int, y: int) -> None:
        self.taps.append((x, y))
        for i, (_label, target) in enumerate(self._screens[self._cur]):
            if _box_for(i).center == (x, y):
                if target is not None:
                    self._stack.append(self._cur)
                    self._cur = target
                return

    def key(self, modifier: int, keycode: int) -> None:
        if (modifier, keycode) == (0x08, 0x2F) and self._stack:   # Cmd+[ = back
            self._cur = self._stack.pop()

    def foreground(self) -> None:
        self._cur = self._start
        self._stack = []


@dataclass
class _AnnEl:
    label: str
    role: str
    navigable: bool
    center: tuple[int, int]
    anchored: bool = True


@dataclass
class _Annotation:
    elements: list


class _SceneAnnotator:
    """Fake ColdStartAnnotator: marks every scene button navigable."""

    def annotate(self, _sid, scene, _img, **_kw) -> _Annotation:
        return _Annotation([
            _AnnEl(e.text, "button", True, e.box.center) for e in scene.elements
        ])


@pytest.mark.smoke
def test_crawl_app_depth1_explores_start_children():
    app = _FakeApp({
        "home": [("我的", "mine"), ("设置", "settings")],
        "mine": [], "settings": [],
    })
    report = crawl_app(app, foreground=app.foreground, annotator=_SceneAnnotator(),
                       max_depth=1, tap_settle_s=0.0)
    assert report.status == "ok"
    assert report.navigations == 2
    assert all(e.depth == 0 for e in report.entries)        # depth-1: no recursion


@pytest.mark.smoke
def test_crawl_app_depth2_recurses_into_children():
    app = _FakeApp({
        "home": [("进入", "child")],
        "child": [("深处", "grand")],
        "grand": [],
    })
    report = crawl_app(app, foreground=app.foreground, annotator=_SceneAnnotator(),
                       max_depth=2, tap_settle_s=0.0)
    assert report.status == "ok"
    assert any(e.depth == 0 and e.label == "进入" for e in report.entries)
    assert any(e.depth == 1 and e.label == "深处" for e in report.entries)   # recursed


@pytest.mark.smoke
def test_crawl_app_counts_noop_for_non_navigating_control():
    app = _FakeApp({"home": [("我的", "mine"), ("关于", None)], "mine": []})
    report = crawl_app(app, foreground=app.foreground, annotator=_SceneAnnotator(),
                       max_depth=1, tap_settle_s=0.0)
    assert report.navigations == 1
    assert report.metrics.no_progress_actions == 1          # 关于 → noop


@pytest.mark.smoke
def test_crawl_app_ocr_fallback_without_annotator():
    app = _FakeApp({"home": [("我的", "mine")], "mine": []})
    report = crawl_app(app, foreground=app.foreground, annotator=None,
                       max_depth=1, tap_settle_s=0.0)
    assert report.strategy == "policy"
    assert report.status == "ok"


@pytest.mark.smoke
def test_crawl_app_uses_injected_crawl_policy_for_candidates():
    class OnlySecondPolicy:
        def classify(self, _scene):
            return "unit"

        def candidates(self, _scene):
            return [
                {
                    "action": "tap",
                    "label": "忽略",
                    "center": list(_box_for(0).center),
                    "source": "unit_policy",
                    "safe": False,
                },
                {
                    "action": "tap",
                    "label": "设置",
                    "box": [
                        _box_for(1).x,
                        _box_for(1).y,
                        _box_for(1).x + _box_for(1).w,
                        _box_for(1).y + _box_for(1).h,
                    ],
                    "source": "unit_policy",
                    "safe": True,
                },
            ]

        def is_safe(self, action, _scene):
            return action.get("safe") is True

        def should_stop(self, _scene, _history):
            return False

    app = _FakeApp({"home": [("忽略", "ignored"), ("设置", "settings")], "settings": []})

    report = crawl_app(
        app,
        foreground=app.foreground,
        annotator=None,
        crawl_policy=OnlySecondPolicy(),
        max_depth=1,
        tap_settle_s=0.0,
    )

    assert report.strategy == "policy"
    assert [(entry.label, entry.source, entry.outcome) for entry in report.entries] == [
        ("设置", "unit_policy", "navigated")
    ]


@pytest.mark.smoke
def test_crawl_app_honors_crawl_policy_should_stop():
    class StopImmediatelyPolicy:
        def __init__(self):
            self.history_lengths = []

        def classify(self, _scene):
            return "unit"

        def candidates(self, _scene):
            raise AssertionError("candidates should not be called after should_stop")

        def is_safe(self, _action, _scene):
            return True

        def should_stop(self, _scene, history):
            self.history_lengths.append(len(history))
            return True

    app = _FakeApp({"home": [("设置", "settings")], "settings": []})
    policy = StopImmediatelyPolicy()

    report = crawl_app(
        app,
        foreground=app.foreground,
        annotator=None,
        crawl_policy=policy,
        max_depth=1,
        tap_settle_s=0.0,
    )

    assert report.status == "ok"
    assert report.entries == []
    assert app.taps == []
    assert policy.history_lengths == [0]


class _LoginWallPhone:
    """Start screen is a login wall — gauntlet must report blocked."""

    def invalidate_perceive_cache(self) -> None:
        pass

    def perceive(self) -> _Scene:
        return _Scene([
            _El("欢迎使用,请先登录后继续", "text", _box_for(0)),
            _El("登录", "button", _box_for(1)),
        ])

    def snapshot(self) -> _Frame:
        return _Frame(img=np.zeros((956, 440, 3), dtype=np.uint8))


@pytest.mark.smoke
def test_crawl_app_reports_gauntlet_block_on_login_wall():
    report = crawl_app(_LoginWallPhone(), foreground=lambda: None,
                       annotator=None, tap_settle_s=0.0)
    assert report.status == "gauntlet_blocked"
    assert report.entries == []


@pytest.mark.smoke
def test_crawl_app_clears_english_gauntlet_then_explores():
    """End-to-end breadth proof: an English-language app whose cold start throws
    a permission interstitial is cleared (deny), then the real home is crawled —
    the same chain that until now only worked on a zh-Hans device."""
    app = _FakeApp(
        {
            "permission": [
                ("“Acme” Would Like to Send You Notifications", None),
                ("Don't Allow", "home"),
                ("Allow", None),
            ],
            "home": [("Profile", "profile"), ("Settings", "settings")],
            "profile": [],
            "settings": [],
        },
        start="permission",
    )
    report = crawl_app(app, foreground=app.foreground, annotator=_SceneAnnotator(),
                       max_depth=1, tap_settle_s=0.0)
    assert report.status == "ok"
    assert report.gauntlet_steps == [("permission", "Don't Allow")]
    assert {e.label for e in report.entries} >= {"Profile", "Settings"}
    assert report.navigations == 2          # explored both real-home rows after the gauntlet


@pytest.mark.smoke
def test_crawl_app_rejects_semantic_failed_tap_without_trusting_screen_change():
    class SemanticRejectingApp(_FakeApp):
        def tap_xy(self, x: int, y: int):
            super().tap_xy(x, y)
            return ActionResult(
                ok=True,
                backend="fake",
                connected=True,
                semantic_status="failed",
                semantic_reason="verifier rejected tap",
            )

    app = SemanticRejectingApp({"home": [("进入", "child")], "child": []})

    report = crawl_app(app, foreground=app.foreground, annotator=_SceneAnnotator(),
                       max_depth=1, tap_settle_s=0.0)

    assert report.entries[0].outcome == "rejected"
    assert report.navigations == 0
    assert report.metrics.no_progress_actions == 1
