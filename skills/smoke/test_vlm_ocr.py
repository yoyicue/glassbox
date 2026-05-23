"""VLM 行级 OCR 兜底(F)—— vlm_ocr。"""
from __future__ import annotations

import numpy as np
import pytest

from glassbox.cognition import Box
from glassbox.cognition.vlm_ocr import (
    choose_label_from_region,
    crop_box,
    horizontal_band_box,
    read_row_text,
)


class _FakeReader:
    """假 VLM 客户端:数 read_text_region 调用次数,返回固定文本。"""

    def __init__(self, text: str = "待机显示"):
        self.text = text
        self.calls = 0

    def read_text_region(self, *, region_image: bytes) -> str:
        self.calls += 1
        return self.text


class _FakeChat:
    def __init__(self, text: str = "待机显示") -> None:
        self.text = text
        self.calls = 0
        self.images: list[bytes] = []
        self.prompts: list[str] = []

    def chat(self, **kwargs):
        self.calls += 1
        self.images.append(kwargs["image"])
        self.prompts.append(kwargs["user_text"])
        return type("_Response", (), {"raw_content": self.text})()


def _frame(h: int = 200, w: int = 400):
    return np.full((h, w, 3), 220, dtype=np.uint8)


@pytest.mark.smoke
def test_crop_box_extracts_padded_region():
    crop = crop_box(_frame(), Box(x=100, y=50, w=80, h=20), pad=6)
    assert crop is not None
    assert crop.shape[0] == 32 and crop.shape[1] == 92   # 20+12, 80+12


@pytest.mark.smoke
def test_crop_box_returns_none_when_fully_off_frame():
    assert crop_box(_frame(), Box(x=900, y=900, w=20, h=20)) is None


@pytest.mark.smoke
def test_horizontal_band_box_keeps_vlm_crop_local_near_bottom():
    frame = _frame(h=980, w=450)
    box = Box(x=36, y=885, w=114, h=18)

    band = horizontal_band_box(frame, box, pad_y=8, min_height=34)

    assert band.x == 0
    assert band.w == 450
    assert band.h == 34
    assert band.y <= box.y
    assert band.y + band.h < 915


@pytest.mark.smoke
def test_read_row_text_returns_vlm_reading():
    reader = _FakeReader("待机显示")
    text = read_row_text(reader, _frame(), Box(x=40, y=40, w=120, h=22))
    assert text == "待机显示"
    assert reader.calls == 1


@pytest.mark.smoke
def test_read_row_text_caches_by_crop_signature():
    """同一行跨帧重复读 → 命中缓存,不重复计费。"""
    reader = _FakeReader()
    cache: dict[str, str] = {}
    box = Box(x=40, y=40, w=120, h=22)
    frame = _frame()
    a = read_row_text(reader, frame, box, cache=cache)
    b = read_row_text(reader, frame, box, cache=cache)
    assert a == b
    assert reader.calls == 1   # 第二次走缓存


@pytest.mark.smoke
def test_read_row_text_swallows_vlm_errors():
    class _Boom:
        def read_text_region(self, *, region_image: bytes) -> str:
            raise RuntimeError("vlm down")

    assert read_row_text(_Boom(), _frame(), Box(x=40, y=40, w=80, h=20)) == ""


@pytest.mark.smoke
def test_read_row_text_does_not_cache_vlm_errors():
    class _Flaky:
        def __init__(self) -> None:
            self.calls = 0

        def read_text_region(self, *, region_image: bytes) -> str:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("vlm down")
            return "待机显示"

    reader = _Flaky()
    cache: dict[str, str] = {}
    frame = _frame()
    box = Box(x=40, y=40, w=80, h=20)

    assert read_row_text(reader, frame, box, cache=cache) == ""
    assert cache == {}
    assert read_row_text(reader, frame, box, cache=cache) == "待机显示"
    assert reader.calls == 2


@pytest.mark.smoke
def test_choose_label_from_region_uses_local_crop_and_closed_set():
    import cv2

    chat = _FakeChat("待机显示")
    labels = ("无线局域网", "待机显示", "通用")
    frame = _frame(h=900, w=500)
    box = horizontal_band_box(frame, Box(x=80, y=420, w=120, h=18))

    label = choose_label_from_region(chat, frame, box, labels, cache={})

    assert label == "待机显示"
    assert chat.calls == 1
    assert "待机显示" in chat.prompts[0]
    crop = cv2.imdecode(np.frombuffer(chat.images[0], dtype=np.uint8), cv2.IMREAD_COLOR)
    assert crop is not None
    assert crop.shape[0] < frame.shape[0]
    assert crop.shape[0] * crop.shape[1] < frame.shape[0] * frame.shape[1]


@pytest.mark.smoke
def test_choose_label_from_region_caches_none_response():
    chat = _FakeChat("not a candidate")
    cache: dict[str, str] = {}
    frame = _frame()
    box = Box(x=40, y=40, w=120, h=22)

    assert choose_label_from_region(chat, frame, box, ("待机显示",), cache=cache) is None
    assert choose_label_from_region(chat, frame, box, ("待机显示",), cache=cache) is None
    assert chat.calls == 1
