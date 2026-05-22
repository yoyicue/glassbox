"""USB HID keymap helpers for PicoKVM keyboardReport."""

from __future__ import annotations

_MOD_SHIFT = 0x02

_LOWER = {chr(ord("a") + i): 0x04 + i for i in range(26)}
_DIGITS = {
    "1": 0x1E,
    "2": 0x1F,
    "3": 0x20,
    "4": 0x21,
    "5": 0x22,
    "6": 0x23,
    "7": 0x24,
    "8": 0x25,
    "9": 0x26,
    "0": 0x27,
}
_PLAIN = {
    **_LOWER,
    **_DIGITS,
    "\n": 0x28,
    "\r": 0x28,
    "\t": 0x2B,
    " ": 0x2C,
    "-": 0x2D,
    "=": 0x2E,
    "[": 0x2F,
    "]": 0x30,
    "\\": 0x31,
    ";": 0x33,
    "'": 0x34,
    "`": 0x35,
    ",": 0x36,
    ".": 0x37,
    "/": 0x38,
}
_SHIFTED = {
    **{k.upper(): v for k, v in _LOWER.items()},
    "!": 0x1E,
    "@": 0x1F,
    "#": 0x20,
    "$": 0x21,
    "%": 0x22,
    "^": 0x23,
    "&": 0x24,
    "*": 0x25,
    "(": 0x26,
    ")": 0x27,
    "_": 0x2D,
    "+": 0x2E,
    "{": 0x2F,
    "}": 0x30,
    "|": 0x31,
    ":": 0x33,
    '"': 0x34,
    "~": 0x35,
    "<": 0x36,
    ">": 0x37,
    "?": 0x38,
}


def char_to_key(ch: str) -> tuple[int, int]:
    if ch in _PLAIN:
        return 0, _PLAIN[ch]
    if ch in _SHIFTED:
        return _MOD_SHIFT, _SHIFTED[ch]
    raise ValueError(f"unsupported PicoKVM keyboard character: {ch!r}")
