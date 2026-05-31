"""Text, keyboard, clipboard, and input-source helpers for Phone."""

from __future__ import annotations

import re
import time
from typing import Any

from loguru import logger

from glassbox.boundaries import AppLaunchTarget
from glassbox.effector import ActionResult

_MOD_META_LEFT = 0x08
_MOD_CTRL = 0x01
_KEY_A = 0x04
_KEY_SPACE = 0x2C
_KEY_DELETE = 0x2A
_KEY_ESC = 0x29
_HIDGLASSBOX_LABELS = ("GlassboxHelper",)
_IME_CANDIDATE_RE = re.compile(r"[1-9]\s*[一-鿿]")


def _is_ascii(text: str) -> bool:
    return all(ord(ch) < 128 for ch in text)


class TextInput:
    """Drive HID text input, clipboard fallback, and keyboard shortcuts."""

    def __init__(self, phone: Any) -> None:
        self._phone = phone

    def type(self, text: str, *, verify: bool | None = None, max_switches: int = 2) -> ActionResult:
        host = self._phone
        if not _is_ascii(text):
            return self.type_via_clipboard(text)
        if verify is None:
            verify = True
        result = host.execute_action("type", lambda: host.effector.type(text), text=text)
        if not verify:
            return result
        for attempt in range(1, max_switches + 1):
            if not host.ime_composing():
                return result
            logger.info(
                f"type({text!r}): CJK IME composing detected — "
                f"switching input source (attempt {attempt}/{max_switches})"
            )
            self.switch_input_source()
            time.sleep(0.4)
            self.clear_focused_field()
            result = host.execute_action(
                "type", lambda: host.effector.type(text),
                text=text, type_switch_attempt=attempt,
            )
        if host.ime_composing():
            logger.warning(
                f"type({text!r}) still composing after {max_switches} input-source switches"
            )
        return result

    def type_via_clipboard(self, text: str) -> ActionResult:
        host = self._phone
        if not host.supports("set_clipboard"):
            logger.warning(
                f"type({text!r}): non-ASCII text needs effector.set_clipboard "
                "(GlassboxHelper setClipboard) — unavailable on this effector"
            )
            return host.unsupported_action("type", text=text)
        dance = (
            host.app_labels is not None
            and host.icon_map is not None
            and host.kimi is not None
            and host.springboard_provider is not None
        )
        if dance:
            self.foreground_app(_HIDGLASSBOX_LABELS)
        host.execute_action(
            "set_clipboard", lambda: host.effector.set_clipboard(text), text=text)
        if dance:
            self.foreground_app(host.app_labels)
        return host.execute_action(
            "paste", lambda: host.effector.paste(), via="type_clipboard", text=text)

    def foreground_app(self, labels: tuple[str, ...]) -> None:
        host = self._phone
        if host.springboard_provider is None:
            return
        target = AppLaunchTarget(bundle_id="", labels=labels)
        host.springboard_provider.foreground_app(
            host,
            target,
            icon_map=host.icon_map,
            settle_s=host.cjk_foreground_settle_s,
        )

    def ime_composing(self) -> bool:
        time.sleep(0.4)
        try:
            scene = self._phone.perceive()
        except Exception:
            return False
        try:
            _, height = self._phone.viewport_size()
        except Exception:
            height = 956
        y_floor = height * 0.7
        hits = 0
        for element in scene.elements:
            if element.text and element.box.center[1] >= y_floor:
                hits += len(_IME_CANDIDATE_RE.findall(element.text))
        return hits >= 2

    def clear_focused_field(self) -> None:
        self.key(0, _KEY_ESC)
        self.key(_MOD_META_LEFT, _KEY_A)
        self.key(0, _KEY_DELETE)

    def key(self, modifier: int, keycode: int) -> ActionResult:
        host = self._phone
        return host.execute_action(
            "key",
            lambda: host.effector.key(modifier, keycode),
            modifier=modifier,
            keycode=keycode,
        )

    def switch_input_source(self) -> ActionResult:
        host = self._phone
        strategy = host.system_action_strategy("switch_input_source")
        if strategy == "unsupported":
            return host.unsupported_action("switch_input_source", strategy=strategy)
        return host.execute_action(
            "key",
            lambda: host.effector.key(_MOD_CTRL, _KEY_SPACE),
            modifier=_MOD_CTRL,
            keycode=_KEY_SPACE,
            via="switch_input_source",
            strategy=strategy,
        )

    def paste(self) -> ActionResult:
        host = self._phone
        strategy = host.system_action_strategy("paste")
        if strategy == "unsupported":
            return host.unsupported_action("paste", strategy=strategy)
        return host.execute_action("paste", lambda: host.effector.paste(), strategy=strategy)


__all__ = ["TextInput"]
