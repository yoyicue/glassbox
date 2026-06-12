from __future__ import annotations

import pytest

from glassbox.ios.progress import (
    same_visible_page,
    scroll_outcome,
    scroll_overshot,
    stable_visible_texts,
    trace_payload_no_progress,
)


@pytest.mark.smoke
def test_stable_visible_texts_filters_volatile_ocr_noise():
    texts = ["19:37", "设置", "最近1", "取近2", "无线局域网", "Q", "蓝牙"]

    assert stable_visible_texts(texts) == {"设置", "无线局域网", "蓝牙"}


@pytest.mark.smoke
def test_same_visible_page_ignores_time_and_recent_noise():
    before = ["19:37", "设置", "最近1", "无线局域网", "蓝牙", "通用", "通知", "搜索"]
    after = ["19:38", "设置", "蕺近2", "无线局域网", "蓝牙", "通用", "通知", "搜索"]

    assert same_visible_page(before, after)


@pytest.mark.smoke
def test_trace_payload_no_progress_requires_same_scene_type():
    before = {"scene_type": "system_search", "texts": ["建议", "App", "通用", "最近1"]}
    after = {"scene_type": "settings_root", "texts": ["设置", "无线局域网", "蓝牙", "通用"]}

    assert not trace_payload_no_progress(before, after)


@pytest.mark.smoke
def test_scroll_overshot_flags_zero_overlap_jump():
    """一次滚动从列表顶跳到底、无重叠文本 → overshoot。"""
    top = ["设置", "飞行模式", "无线局域网", "蓝牙", "蜂窝网络", "电池"]
    bottom = ["通知", "声效与触感", "专注模式", "屏幕时间", "隐私与安全性", "钱包"]

    assert scroll_overshot(top, bottom)


@pytest.mark.smoke
def test_scroll_overshot_false_on_incremental_scroll_with_overlap():
    """正常增量滚动,相邻帧有重叠行 → 非 overshoot。"""
    before = ["无线局域网", "蓝牙", "蜂窝网络", "电池", "通用", "辅助功能"]
    after = ["电池", "通用", "辅助功能", "操作按钮", "待机显示", "声效与触感"]

    assert not scroll_overshot(before, after)


@pytest.mark.smoke
def test_scroll_overshot_false_on_no_movement():
    """完全没动是 no-progress,不是 overshoot。"""
    same = ["设置", "无线局域网", "蓝牙", "通用", "辅助功能"]

    assert not scroll_overshot(same, list(same))


@pytest.mark.smoke
def test_scroll_outcome_progress_on_partial_scroll():
    """有重叠 + 有新行 → progress。"""
    before = ["无线局域网", "蓝牙", "蜂窝网络", "电池", "通用", "辅助功能"]
    after = ["电池", "通用", "辅助功能", "操作按钮", "待机显示", "声效与触感"]
    assert scroll_outcome(before, after) == "progress"


@pytest.mark.smoke
def test_scroll_outcome_overshoot_on_zero_overlap():
    """零重叠 → 跳过 >1 屏 → overshoot。"""
    top = ["设置", "飞行模式", "无线局域网", "蓝牙", "蜂窝网络", "电池"]
    bottom = ["通知", "声效与触感", "专注模式", "屏幕时间", "隐私与安全性", "钱包"]
    assert scroll_outcome(top, bottom) == "overshoot"


@pytest.mark.smoke
def test_scroll_outcome_stuck_at_bottom():
    """到底:after 无新行(⊆ before)→ stuck。"""
    before = ["通用", "辅助功能", "操作按钮", "待机显示", "通知", "搜索"]
    after = ["辅助功能", "操作按钮", "待机显示", "通知", "搜索"]   # 无新行,只是顶部少了一条
    assert scroll_outcome(before, after) == "stuck"
    assert scroll_outcome(before, list(before)) == "stuck"   # 完全没动也 stuck


@pytest.mark.smoke
def test_scroll_outcome_overshoot_despite_shared_chrome():
    """整列表从顶跳到底,只有持久标题「设置」重叠 → 重叠率低 → 仍判 overshoot。"""
    top = ["设置", "飞行模式", "无线局域网", "蓝牙", "蜂窝网络", "电池", "VPN"]
    bottom = ["设置", "通知", "声效与触感", "专注模式", "屏幕时间", "隐私与安全性", "钱包"]
    assert scroll_outcome(top, bottom) == "overshoot"


@pytest.mark.smoke
def test_stable_visible_texts_drops_symbol_fragments():
    """纯符号/标点碎片(（②、-）)是 OCR 噪声,不算稳定行;行做空白+大小写归一。"""
    stable = stable_visible_texts(["设置", "通知", "（②", "-）", "VPN", "Jo Doe"])
    assert stable == {"设置", "通知", "vpn", "jodoe"}


@pytest.mark.smoke
def test_stable_visible_texts_normalizes_whitespace_and_case():
    """OCR 对行内空白/大小写不稳定 —— Game Center / GameCenter 归一为同一行。"""
    spaced = stable_visible_texts(["Game Center", "iCloud", "钱包与 Apple Pay"])
    tight = stable_visible_texts(["GameCenter", "iClOud", "钱包与ApplePay"])
    assert spaced == tight


@pytest.mark.smoke
def test_scroll_outcome_stuck_when_only_symbol_noise_differs():
    """列表没动、after 只多了一闪一灭的 OCR 垃圾行 → 仍判 stuck,不被骗成 progress。"""
    before = ["设置", "通知", "声效与触感反馈", "专注模式", "屏幕时间"]
    after = ["设置", "（②", "通知", "声效与触感反馈", "专注模式", "屏幕时间"]
    assert scroll_outcome(before, after) == "stuck"


@pytest.mark.smoke
def test_scroll_outcome_stuck_when_rows_differ_only_by_whitespace_and_case():
    """两条 perceive 路径对同一静止列表给出不同空白/大小写 → 必须判 stuck。

    这是 wheel-v13 实测 bug:列表卡住不动,before 用紧凑形、after 用带空格形,
    旧的精确字符串比对把它误判成 progress,滚动循环 14 次都不 break。
    """
    before = ["13:3O", "GameCenter", "iClOud", "钱包与ApplePay", "Q搜索",
              "•GlassboxHelper", "专注模式", "声效与触感反馈", "设置", "通知"]
    after = ["13:31", "Game Center", "iCloud", "钱包与 Apple Pay", "Q 搜索",
             "• GlassboxHelper", "专注模式", "声效与触感反馈", "设置", "通知"]
    assert scroll_outcome(before, after) == "stuck"
