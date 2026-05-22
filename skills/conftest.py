"""skills/conftest.py — pytest fixtures for walkthroughs

Provides phone (integrates perception + cognition + effector) and profile
(white-box hints).

Current (M2b):
    - source can be HDMI frame grabbing or static images (env GLASSBOX_FRAME_DIR points at an image set)
    - cognition: VisionOCR (direct PyObjC call + unsharp mask); GLASSBOX_OCR=ocrmac falls back
    - effector: NoOpEffector for now (M3+ wires up PicoKVM)

Walkthrough script example:
    def test_login(phone, profile):
        phone.expect_text("登录", timeout=5)
        # phone.tap_text("登录")  # available once the effector is connected
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

import pytest

from glassbox.cognition import (
    HeuristicTyper,
    UIElement,
)
from glassbox.config import get_config
from glassbox.perception import Frame
from glassbox.phone import Phone
from glassbox.profile import Profile, ProfileRegistry
from glassbox.runtime import (
    RuntimeUnavailable,
    build_phone,
)
from glassbox.runtime import (
    detect_crop as runtime_detect_crop,
)
from glassbox.runtime import (
    make_effector as runtime_make_effector,
)
from glassbox.runtime import (
    make_source as runtime_make_source,
)
from glassbox.runtime import (
    save_memory_utg as runtime_save_memory_utg,
)

# project root (derived from the conftest location)
GLASSBOX_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True, scope="session")
def _isolate_glassbox_env():
    """Run the suite against true config defaults.

    ``import glassbox`` auto-loads the repo-root ``.env`` (for local device runs
    and API keys), which would otherwise leak ``GLASSBOX_*`` overrides into tests
    that assert default configuration. Strip them for the session and restore
    afterwards so a contributor's local ``.env`` cannot break the suite.
    """
    saved = {key: os.environ.pop(key) for key in list(os.environ) if key.startswith("GLASSBOX_")}
    get_config.cache_clear()
    try:
        yield
    finally:
        os.environ.update(saved)
        get_config.cache_clear()


# ─── FrameSource selection ───────────────────────────────────────────
def _make_source():
    """Pytest adapter around glassbox.runtime.make_source()."""
    try:
        return runtime_make_source(cfg=get_config())
    except RuntimeUnavailable as e:
        pytest.skip(str(e))


# NoOpEffector / PicoKVMEffector / MockEffector live behind glassbox.runtime; this only assembles them.


def _make_effector(source, *, frame_resolution: tuple[int, int] | None = None):
    """Compatibility wrapper for tests that exercise effector selection."""
    return runtime_make_effector(
        source,
        cfg=get_config(),
        frame_resolution=frame_resolution,
    )


def _save_memory_utg(memory, *, memory_dir: str | None) -> None:
    runtime_save_memory_utg(memory, memory_dir=memory_dir)


def _detect_crop(source):
    """Pytest adapter around glassbox.runtime.detect_crop()."""
    try:
        return runtime_detect_crop(source, cfg=get_config())
    except RuntimeUnavailable as e:
        pytest.skip(str(e))


# The Phone class implementation moved to glassbox/phone.py — so probe scripts /
# external scripts can import it directly, without relying on pytest conftest's
# dynamic discovery mechanism. Here the fixture only assembles a Phone instance.


# ─── Fixtures ────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def profile_registry() -> ProfileRegistry:
    """Load every yaml under profile/. Session-scoped, so the full test suite loads it only once."""
    reg = ProfileRegistry()
    reg.load_dir(GLASSBOX_ROOT / "profiles", strict=False)
    return reg


@pytest.fixture(scope="session")
def profile(profile_registry: ProfileRegistry) -> Profile | None:
    """The walkthrough target App profile.

    bundle_id is determined by config.profile_bundle (env
    GLASSBOX_PROFILE_BUNDLE) — the framework itself is not bound to a specific
    App. Unset → None (the walkthrough carries no white-box knowledge).
    Set but not loaded from profiles/ → skip.
    A walkthrough for a specific App sets GLASSBOX_PROFILE_BUNDLE in that App's
    private conftest.
    """
    bundle = get_config().profile_bundle
    if not bundle:
        return None
    prof = profile_registry.get(bundle)
    if prof is None:
        if profile_registry.load_errors:
            details = "; ".join(
                f"{e.path}: {e.error}" for e in profile_registry.load_errors[:3]
            )
            pytest.fail(f"profile {bundle} was requested but profile loading failed: {details}")
        pytest.skip(f"profile {bundle} not loaded (not found under profiles/)")
    return prof


@pytest.fixture(scope="session")
def _frame_source():
    """Session-scoped frame source.

    On the macOS AVFoundation backend, cv2.VideoCapture gets into a stuck
    state after repeated open/close — isOpened=True but read() always
    False. Opening only once per session, with all tests sharing the same
    cap handle, works around this.
    """
    src = _make_source()
    yield src
    with contextlib.suppress(Exception):
        src.close()


@pytest.fixture
def phone(profile: Profile | None, _frame_source) -> Phone:
    """The main walkthrough object. The frame source is reused session-scoped; effector / scene state is function-scoped."""
    source = _frame_source
    cfg = get_config()
    try:
        runtime = build_phone(source=source, profile=profile, cfg=cfg)
    except RuntimeUnavailable as e:
        pytest.skip(str(e))
    yield runtime.phone
    # cleanup: _frame_source owns the session-scoped capture handle. Closing it
    # here makes the next test reuse a closed AVFoundation source.
    runtime.close(close_source=False)


# ─── Marker availability ─────────────────────────────────────────────
def _ocrmac_available() -> bool:
    try:
        import ocrmac  # noqa: F401
        return True
    except ImportError:
        return False


# pytest skip marker (attach this when a walkthrough needs OCR)
needs_ocrmac = pytest.mark.skipif(
    not _ocrmac_available(),
    reason="ocrmac not installed. `pip install ocrmac` (works on macOS only)",
)


# ─── Fixture for unit tests (no hardware / OCR, pure logic verification) ──
@pytest.fixture
def mock_phone(profile: Profile | None) -> Phone:
    """For unit-testing walkthrough script logic. The effector is a MockEffector that records every action.

    Usage:
        def test_login_calls_tap(mock_phone, monkeypatch):
            # have OCR return specific elements, verify tap_text calls effector.tap
            ...
            assert mock_phone.effector.last().op == "tap"
    """
    from glassbox.effector import MockEffector
    from glassbox.ios.safe_area import IOSSafeAreaProvider
    from glassbox.ios.springboard import IOSSpringboardProvider

    phone_size = get_config().phone_size()

    class FakeSource:
        """Hardware-free frame source. snapshot() returns a 1px black image."""

        def snapshot(self):
            import numpy as np
            return Frame(img=np.zeros((1, 1, 3), dtype=np.uint8), ts=0.0)

        def close(self): pass
        resolution = phone_size

    class FakeOCR:
        """OCR mock with configurable elements."""
        def __init__(self):
            self.elements: list[UIElement] = []

        def recognize(self, image) -> list[UIElement]:
            return list(self.elements)

    eff = MockEffector()
    typer = HeuristicTyper(frame_size=phone_size)
    p = Phone(
        source=FakeSource(), ocr=FakeOCR(), effector=eff,
        profile=profile, typer=typer, action_fail_fast=False,
        safe_area_provider=IOSSafeAreaProvider(),
        springboard_provider=IOSSpringboardProvider(),
    )
    yield p
    eff.reset()
