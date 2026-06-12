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


# ── dismiss_modal_sheet_overlay: auto-presented card sheets ───────────────────
# Constructed from the recorded Apple Account safety-sheet shape
# (iphone_transition_n1, 2026-06-12) with synthetic values.


def _safety_sheet_scene(*, with_close_x: bool = True) -> Scene:
    elements = [
        _el("Is this still your phone number?", 36, 155, w=328, h=147),
        _el("Current trusted number:", 38, 308, w=248, h=22),
        _el("+1 (555) 010-4477", 38, 336, w=192, h=24),
        _el("It is important to make sure your", 36, 457, w=314, h=23),
        _el("trusted phone number is correct so", 36, 486, w=340, h=22),
        _el("number is used to verify your identity.", 38, 648, w=361, h=22),
        _el("Messaging and data rates may apply.", 38, 676, w=358, h=24),
        _el("Keep using +1 (555) 010-4477", 98, 838, w=252),
        _el("Change trusted number", 128, 902, w=194, h=18),
    ]
    if with_close_x:
        elements.insert(0, _el("X", 394, 102, w=20, h=18))
    return Scene(frame_id=0, timestamp=0.0, elements=elements)


class _TapPhone:
    def __init__(self):
        self.taps: list[tuple[int, int]] = []

    def tap_xy(self, x: int, y: int):
        self.taps.append((x, y))


@pytest.mark.smoke
def test_dismiss_modal_sheet_overlay_taps_only_the_close_x_region():
    from glassbox.ios.recovery import dismiss_modal_sheet_overlay

    trace: list[tuple[str, dict]] = []

    @contextmanager
    def action_context(name: str, **metadata):
        trace.append((name, metadata))
        yield

    phone = _TapPhone()
    scene = _safety_sheet_scene()

    assert dismiss_modal_sheet_overlay(
        phone, scene, viewport_size=(448, 973), action_context=action_context
    )
    assert phone.taps == [(404, 111)]
    # READ-ONLY pin: button rows ("Keep using …" / "Change trusted number")
    # are present, yet every tap stays in the top-right close band.
    for x, y in phone.taps:
        assert x >= 448 * 0.75
        assert y <= 973 * 0.20
    assert trace and trace[0][0] == "modal.dismiss_close_x"


@pytest.mark.smoke
def test_dismiss_modal_sheet_overlay_falls_back_to_canonical_close_region():
    from glassbox.ios.recovery import dismiss_modal_sheet_overlay

    phone = _TapPhone()
    scene = _safety_sheet_scene(with_close_x=False)

    assert dismiss_modal_sheet_overlay(phone, scene, viewport_size=(448, 973))
    assert phone.taps == [(403, 107)]


@pytest.mark.smoke
def test_dismiss_modal_sheet_overlay_abstains_without_modal_evidence():
    from glassbox.ios.recovery import dismiss_modal_sheet_overlay

    phone = _TapPhone()
    detail = Scene(
        frame_id=0,
        timestamp=0.0,
        elements=[
            _el("General", 198, 80, w=64),
            _el("About", 80, 300, w=50),
            _el("Software Update", 80, 360, w=130),
        ],
    )

    assert not dismiss_modal_sheet_overlay(phone, detail, viewport_size=(448, 973))
    assert not dismiss_modal_sheet_overlay(phone, None, viewport_size=(448, 973))
    assert phone.taps == []
