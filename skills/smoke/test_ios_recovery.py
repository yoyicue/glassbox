from __future__ import annotations

from contextlib import contextmanager

import pytest

from glassbox.boundaries import StepContext
from glassbox.cognition import Box, Scene, UIElement
from glassbox.ios.recovery import IOSRecoveryProvider, dismiss_system_search


def _el(text: str, x: int, y: int, w: int = 80, h: int = 20) -> UIElement:
    return UIElement(type="text", box=Box(x=x, y=y, w=w, h=h), text=text, confidence=0.9)


def _system_search_scene() -> Scene:
    return Scene(
        frame_id=0,
        timestamp=0.0,
        elements=[
            _el("建议", 18, 98, w=36),
            _el("App", 56, 152, w=34),
            _el("通用", 56, 212, w=36),
            _el("最近1", 18, 410, w=46),
            _el("Q", 48, 912, w=16),
            _el("搜索", 68, 910, w=42),
        ],
    )


@pytest.mark.smoke
def test_dismiss_system_search_uses_home_with_trace():
    class FakePhone:
        def __init__(self):
            self.actions: list[str] = []

        def home(self):
            self.actions.append("home")

    trace: list[tuple[str, dict]] = []

    @contextmanager
    def action_context(name: str, **metadata):
        trace.append((name, metadata))
        yield

    phone = FakePhone()

    assert dismiss_system_search(phone, _system_search_scene(), action_context=action_context)
    assert phone.actions == ["home"]
    assert trace[0][0] == "system_search.home_dismiss"


@pytest.mark.smoke
def test_dismiss_system_search_rejects_non_system_search_scene():
    class FakePhone:
        def home(self):
            raise AssertionError("home should not be called")

    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        elements=[
            _el("设置", 198, 72, w=48),
            _el("无线局域网", 80, 370, w=86),
            _el("蓝牙", 80, 424, w=40),
        ],
    )

    assert not dismiss_system_search(FakePhone(), scene)


@pytest.mark.smoke
def test_ios_recovery_provider_detects_and_recovers_system_search():
    class FakePhone:
        def __init__(self):
            self.actions: list[str] = []

        def home(self):
            self.actions.append("home")

    provider = IOSRecoveryProvider()
    phone = FakePhone()
    scene = _system_search_scene()

    signal = provider.detect(scene)
    recovered = provider.recover(StepContext(metadata={"phone": phone, "scene": scene}))

    assert signal is not None
    assert signal.kind == "system_search"
    assert recovered is True
    assert phone.actions == ["home"]


@pytest.mark.smoke
def test_ios_recovery_provider_rejects_missing_phone():
    provider = IOSRecoveryProvider()

    assert provider.recover(StepContext(metadata={"scene": _system_search_scene()})) is False
