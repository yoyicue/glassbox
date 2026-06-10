from __future__ import annotations

import numpy as np
import pytest

from glassbox.cognition import Box, Scene, UIElement
from glassbox.verification.diff import compute_frame_diff
from glassbox.verification.golden import iter_golden_cases
from glassbox.verification.registry import VerifierRegistry
from glassbox.verification.verifiers import VerifierInput

GOLDEN_ROOT = "skills/golden/computer_use"


@pytest.mark.smoke
def test_compute_frame_diff_shape_mismatch_is_indeterminate_not_full_change():
    """CUQ-1.7: a garbled/partial decode (shape mismatch) must be scored as
    indeterminate, not as a confident 'everything changed' (ratio 1.0) that
    would fake a landed/progress signal."""
    a = np.zeros((40, 30, 3), dtype=np.uint8)
    b = np.zeros((42, 31, 3), dtype=np.uint8)  # different shape == garbled decode

    diff = compute_frame_diff(a, b)

    assert diff is not None
    assert diff.diff_ratio is None  # not 1.0
    assert diff.changed is None  # falsey for progress/landing checks, not True
    # a same-shape real change is still scored normally
    c = np.zeros((40, 30, 3), dtype=np.uint8)
    c[:, :] = 255
    real = compute_frame_diff(a, c)
    assert real is not None and real.changed is True and real.diff_ratio == pytest.approx(1.0)


def _scene(
    *texts: str,
    page_id: str | None = None,
    kind: str | None = None,
    scene_type: str | None = None,
) -> Scene:
    scene = Scene(
        frame_id=1,
        timestamp=1.0,
        scene_type=scene_type,
        page_id=page_id,
        platform_scene_kind=kind,
        elements=[
            UIElement(
                type="text",
                box=Box(x=0, y=i * 10, w=100, h=8),
                text=text,
                confidence=0.95,
                element_id=i,
            )
            for i, text in enumerate(texts)
        ],
    )
    return scene


def _nav_scene(*items: tuple[str, str, int, int]) -> Scene:
    return Scene(
        frame_id=1,
        timestamp=1.0,
        viewport_size=(448, 982),
        elements=[
            UIElement(
                type=ty,
                box=Box(x=x, y=y, w=80, h=24),
                text=text,
                confidence=0.95,
                element_id=i,
            )
            for i, (ty, text, x, y) in enumerate(items)
        ],
    )


def _input(
    action: str,
    after: Scene,
    *,
    metadata: dict | None = None,
    matched_by_observation: dict | None = None,
) -> VerifierInput:
    return VerifierInput(
        attempt_id="act_1",
        attempt_group_id="grp_1",
        action={"op": action, "args": [], "kwargs": {}, "metadata": metadata or {}},
        before_requested=_scene("主屏幕"),
        before_command=_scene("主屏幕"),
        after_scenes=[after],
        after_mode="single_frame",
        frame_diff={"changed": True},
        scene_diff={"changed": True},
        command_result={"transport_ok": True},
        risk={"level": "medium"},
        matched_by_observation=matched_by_observation,
        after_frame_ids=["frm_after"],
        after_scene_ids=["scn_after"],
    )


@pytest.mark.smoke
def test_control_center_verifier_golden_positive_and_negative():
    registry = VerifierRegistry()
    verifier = registry.resolve("control_center")

    positive = verifier.verify(_input("control_center", _scene("勿扰模式", "未在播放")))
    negative = verifier.verify(_input("control_center", _scene("主屏幕", "设置")))

    assert positive.status == "succeeded"
    assert positive.verifier_hash
    assert positive.matched_scene_id == "scn_after"
    assert positive.matched_frame_id == "frm_after"
    assert negative.status == "failed"
    assert "勿扰模式" in negative.missing_evidence


@pytest.mark.smoke
def test_failed_verifier_preserves_observation_match_evidence():
    registry = VerifierRegistry()
    verifier = registry.resolve("control_center")
    match = {"kind": "success_marker", "scene_id": "scn_window_2", "frame_id": "frm_window_2"}

    outcome = verifier.verify(
        _input(
            "control_center",
            _scene("主屏幕", "设置"),
            matched_by_observation=match,
        )
    )

    assert outcome.status == "failed"
    assert outcome.observation_match == match


@pytest.mark.smoke
def test_control_center_verifier_golden_disqualifying_state():
    registry = VerifierRegistry()
    verifier = registry.resolve("control_center")

    outcome = verifier.verify(_input("control_center", _scene("滑动来关机", "SOS")))

    assert outcome.status == "blocked"  # CUQ-3.19: safety stop, not a task failure
    assert outcome.disqualifying_state == "ios_power_off_screen"
    assert outcome.retry_allowed is False
    assert outcome.observation_match == {
        "kind": "disqualifying_state",
        "verifier": "ios_control_center_opened",
        "matched_evidence": ["滑动来关机", "关机", "SOS"],
        "frame_id": "frm_after",
        "scene_id": "scn_after",
        "state": "ios_power_off_screen",
    }


@pytest.mark.smoke
def test_home_verifier_requires_multiple_home_screen_markers():
    registry = VerifierRegistry()
    verifier = registry.resolve("home")

    positive = verifier.verify(_input("home", _scene("天气", "日历", "照片", "App Store")))
    negative = verifier.verify(_input("home", _scene("设置", "命令", "向上轻扫", "停止服务")))

    assert positive.status == "succeeded"
    assert negative.status == "failed"
    assert "at least 3" in negative.reason


@pytest.mark.smoke
def test_home_verifier_accepts_platform_springboard_classification():
    registry = VerifierRegistry()
    verifier = registry.resolve("home")

    outcome = verifier.verify(_input("home", _scene("低置信标签", kind="springboard")))

    assert outcome.status == "succeeded"
    assert outcome.reason == "after scene classified as SpringBoard"


@pytest.mark.smoke
def test_home_verifier_rejects_photos_onboarding_layout():
    registry = VerifierRegistry()
    verifier = registry.resolve("home")

    outcome = verifier.verify(
        _input(
            "home",
            _scene(
                "“照片”新功能",
                "导览焕然一新",
                "自由切换图库和精选集视图",
                "触手可及。",
                "继续",
            ),
        )
    )

    assert outcome.status == "failed"
    assert outcome.verifier == "ios_home_screen_visible"


@pytest.mark.smoke
def test_registry_uses_policy_action_for_back_gesture_key_command():
    registry = VerifierRegistry()

    verifier = registry.resolve("key", {"policy_action": "back"})

    assert verifier.name == "navigation_back"


@pytest.mark.smoke
def test_navigation_back_rejects_same_page_focus_delta():
    registry = VerifierRegistry()
    verifier = registry.resolve("back")
    before = _scene("健康数据", "医疗详细信息", "健康详细信息")
    after = _scene("健康数据", "医疗详细信息", "健康详细信息")
    input_ = VerifierInput(
        attempt_id="act_1",
        attempt_group_id="grp_1",
        action={"op": "back", "args": [], "kwargs": {}, "metadata": {}},
        before_requested=before,
        before_command=before,
        after_scenes=[after],
        after_mode="single_frame",
        frame_diff={"changed": True, "diff_ratio": 0.009},
        scene_diff={"changed": False},
        command_result={"transport_ok": True},
        risk={"level": "medium"},
    )

    outcome = verifier.verify(input_)

    assert outcome.status == "unknown"
    assert "identity did not change" in outcome.reason


@pytest.mark.smoke
def test_navigation_back_rejects_same_about_page_after_focus_delta():
    registry = VerifierRegistry()
    verifier = registry.resolve("back")
    before = _nav_scene(
        ("nav_back", "<", 24, 78),
        ("button", "关于本机", 184, 78),
        ("text", "名称", 40, 155),
        ("button", "iOS版本", 40, 209),
        ("text", "型号名称", 40, 263),
        ("text", "序列号", 40, 371),
    )
    after = _nav_scene(
        ("button", "关于本机", 184, 78),
        ("nav_back", "<", 24, 78),
        ("text", "名称", 40, 155),
        ("button", "iOS版本", 40, 209),
        ("text", "型号名称", 40, 263),
        ("text", "序列号", 40, 371),
    )
    input_ = VerifierInput(
        attempt_id="act_1",
        attempt_group_id="grp_1",
        action={"op": "back", "args": [], "kwargs": {}, "metadata": {}},
        before_requested=before,
        before_command=before,
        after_scenes=[after],
        after_mode="single_frame",
        frame_diff={"changed": True, "diff_ratio": 0.012},
        scene_diff={"changed": True},
        command_result={"transport_ok": True},
        risk={"level": "medium"},
    )

    outcome = verifier.verify(input_)

    assert outcome.status == "unknown"
    assert "identity did not change" in outcome.reason


@pytest.mark.smoke
def test_navigation_back_accepts_about_to_general_text_identity_change():
    registry = VerifierRegistry()
    verifier = registry.resolve("back")
    before = _nav_scene(
        ("nav_back", "<", 24, 78),
        ("button", "关于本机", 184, 78),
        ("text", "名称", 40, 155),
        ("button", "iOS版本", 40, 209),
        ("text", "型号名称", 40, 263),
    )
    after = _nav_scene(
        ("nav_back", "<", 24, 78),
        ("button", "通用", 204, 78),
        ("button", "关于本机", 40, 155),
        ("button", "软件更新", 40, 209),
        ("button", "AppleCare 与保修", 40, 263),
    )
    input_ = VerifierInput(
        attempt_id="act_1",
        attempt_group_id="grp_1",
        action={"op": "back", "args": [], "kwargs": {}, "metadata": {}},
        before_requested=before,
        before_command=before,
        after_scenes=[after],
        after_mode="single_frame",
        frame_diff={"changed": True, "diff_ratio": 0.08},
        scene_diff={"changed": True},
        command_result={"transport_ok": True},
        risk={"level": "medium"},
    )

    outcome = verifier.verify(input_)

    assert outcome.status == "succeeded"
    assert "identity changed" in outcome.reason


@pytest.mark.smoke
def test_navigation_back_rejects_forward_navigation_to_child_row():
    registry = VerifierRegistry()
    verifier = registry.resolve("back")
    before = _nav_scene(
        ("nav_back", "<", 24, 78),
        ("button", "关于本机", 184, 78),
        ("text", "名称", 40, 155),
        ("button", "iOS版本", 40, 209),
        ("text", "型号名称", 40, 263),
    )
    after = _nav_scene(
        ("nav_back", "<", 24, 78),
        ("button", "名称", 204, 78),
        ("text", "iPhone", 40, 155),
    )
    input_ = VerifierInput(
        attempt_id="act_1",
        attempt_group_id="grp_1",
        action={"op": "back", "args": [], "kwargs": {}, "metadata": {}},
        before_requested=before,
        before_command=before,
        after_scenes=[after],
        after_mode="single_frame",
        frame_diff={"changed": True, "diff_ratio": 0.04},
        scene_diff={"changed": True},
        command_result={"transport_ok": True},
        risk={"level": "medium"},
    )

    outcome = verifier.verify(input_)

    assert outcome.status == "unknown"
    assert "child page" in outcome.reason


@pytest.mark.smoke
def test_navigation_back_rejects_same_page_when_title_is_also_body_text():
    registry = VerifierRegistry()
    verifier = registry.resolve("back")
    before = _nav_scene(
        ("nav_back", "<", 24, 78),
        ("button", "通用", 204, 78),
        ("button", "通用", 40, 232),
        ("button", "关于本机", 40, 371),
        ("button", "软件更新", 40, 425),
    )
    after = _nav_scene(
        ("button", "通用", 204, 78),
        ("nav_back", "<", 24, 78),
        ("button", "通用", 40, 232),
        ("button", "关于本机", 40, 371),
        ("button", "软件更新", 40, 425),
    )
    input_ = VerifierInput(
        attempt_id="act_1",
        attempt_group_id="grp_1",
        action={"op": "back", "args": [], "kwargs": {}, "metadata": {}},
        before_requested=before,
        before_command=before,
        after_scenes=[after],
        after_mode="single_frame",
        frame_diff={"changed": True, "diff_ratio": 0.02},
        scene_diff={"changed": True},
        command_result={"transport_ok": True},
        risk={"level": "medium"},
    )

    outcome = verifier.verify(input_)

    assert outcome.status == "unknown"
    assert "identity did not change" in outcome.reason


@pytest.mark.smoke
def test_tap_target_effect_rejects_springboard_same_page_label_delta():
    registry = VerifierRegistry()
    verifier = registry.resolve("tap")
    home = _scene("天气", "日历", "照片", "App Store")
    input_ = VerifierInput(
        attempt_id="act_1",
        attempt_group_id="grp_1",
        action={"op": "tap", "args": [], "kwargs": {}, "metadata": {"target": "照片"}},
        before_requested=home,
        before_command=home,
        after_scenes=[_scene("天气", "日历", "照片", "App Store")],
        after_mode="single_frame",
        frame_diff={"changed": True, "diff_ratio": 0.25},
        scene_diff={"changed": True},
        command_result={"transport_ok": True},
        risk={"level": "medium"},
    )

    outcome = verifier.verify(input_)

    assert outcome.status == "unknown"
    assert "same SpringBoard page" in outcome.reason


@pytest.mark.smoke
def test_type_verifier_unknown_when_expected_text_is_not_visible():
    registry = VerifierRegistry()
    verifier = registry.resolve("type")
    input_ = VerifierInput(
        attempt_id="act_1",
        attempt_group_id="grp_1",
        action={"op": "type", "args": [], "kwargs": {"text": "abc"}, "metadata": {}},
        before_requested=_scene("输入框"),
        before_command=_scene("输入框"),
        after_scenes=[_scene("输入框")],
        after_mode="single_frame",
        frame_diff={"changed": True},
        scene_diff={"changed": False},
        command_result={"transport_ok": True},
        risk={"level": "medium"},
    )

    outcome = verifier.verify(input_)

    assert outcome.status == "unknown"
    assert "not visible" in outcome.reason


@pytest.mark.smoke
def test_scene_progressed_verifier_disqualifying_state_overrides_change():
    registry = VerifierRegistry()
    verifier = registry.resolve("tap")

    outcome = verifier.verify(_input("tap", _scene("滑动来关机", "SOS")))

    assert outcome.status == "blocked"  # CUQ-3.19: safety stop, not a task failure
    assert outcome.disqualifying_state == "ios_power_off_screen"
    assert outcome.retry_allowed is False


@pytest.mark.smoke
def test_scene_progressed_verifier_does_not_treat_onboarding_unlock_copy_as_lock_screen():
    registry = VerifierRegistry()
    verifier = registry.resolve("tap")

    outcome = verifier.verify(_input("tap", _scene("“照片”新功能", "触手可及", "立即解锁更多功能", "继续")))

    assert outcome.disqualifying_state is None
    assert outcome.status == "succeeded"


@pytest.mark.smoke
def test_scene_progressed_verifier_reports_frame_only_change_as_unknown():
    registry = VerifierRegistry()
    verifier = registry.resolve("scroll")
    before = _scene("套餐", "继续")
    after = _scene("套餐", "继续")
    input_ = VerifierInput(
        attempt_id="act_1",
        attempt_group_id="grp_1",
        action={"op": "scroll", "args": [], "kwargs": {}, "metadata": {}},
        before_requested=before,
        before_command=before,
        after_scenes=[after],
        after_mode="single_frame",
        frame_diff={"changed": True, "diff_ratio": 0.02},
        scene_diff={"changed": False},
        command_result={"transport_ok": True},
        risk={"level": "medium"},
    )

    outcome = verifier.verify(input_)

    assert outcome.status == "unknown"
    assert "semantic target not proven" in outcome.reason


@pytest.mark.smoke
def test_scene_progressed_verifier_reports_carousel_text_churn_as_unknown():
    registry = VerifierRegistry()
    verifier = registry.resolve("tap")
    before = _scene("以受限功能继续", "用户评价", "非常好用", page_id="paywall")
    after = _scene("以受限功能继续", "用户评价", "五星推荐", page_id="paywall")
    input_ = VerifierInput(
        attempt_id="act_1",
        attempt_group_id="grp_1",
        action={"op": "tap", "args": [], "kwargs": {}, "metadata": {}},
        before_requested=before,
        before_command=before,
        after_scenes=[after],
        after_mode="single_frame",
        frame_diff={"changed": True, "diff_ratio": 0.02},
        scene_diff={
            "changed": True,
            "texts_added": ["五星推荐"],
            "texts_removed": ["非常好用"],
            "texts_common": ["以受限功能继续", "用户评价"],
            "page_id_before": "paywall",
            "page_id_after": "paywall",
            "scene_type_before": None,
            "scene_type_after": None,
            "element_count_delta": 0,
        },
        command_result={"transport_ok": True},
        risk={"level": "medium"},
    )

    outcome = verifier.verify(input_)

    assert outcome.status == "unknown"
    assert "transient carousel" in outcome.reason


@pytest.mark.smoke
def test_settings_emergency_sos_row_is_not_power_off_screen():
    registry = VerifierRegistry()
    verifier = registry.resolve("tap")

    outcome = verifier.verify(_input("tap", _scene("设置", "SOS", "SOS紧急联络", "隐私与安全性")))

    assert outcome.disqualifying_state is None
    assert outcome.status != "failed"


@pytest.mark.smoke
def test_permission_dialog_disqualifying_state_requires_approval():
    registry = VerifierRegistry()
    verifier = registry.resolve("tap")

    outcome = verifier.verify(_input("tap", _scene("想要访问您的照片", "不允许", "允许访问")))

    assert outcome.status == "approval_required"
    assert outcome.disqualifying_state == "ios_system_permission_dialog"
    assert outcome.retry_allowed is False


@pytest.mark.smoke
def test_app_crash_disqualifying_state_forbids_retry():
    registry = VerifierRegistry()
    verifier = registry.resolve("open_app", {"app": "Settings", "aliases": ["设置"]})

    outcome = verifier.verify(_input("open_app", _scene("应用程序意外退出", "重新打开")))

    assert outcome.status == "blocked"  # CUQ-3.19: safety stop, not a task failure
    assert outcome.disqualifying_state == "app_crashed_or_terminated"
    assert outcome.retry_allowed is False


@pytest.mark.smoke
@pytest.mark.parametrize(
    ("scene", "evidence"),
    [
        (_scene("Touch ID & Passcode", page_id="settings/Touch ID & Passcode"), "page_id="),
        (_scene("Touch ID & Passcode", scene_type="settings_detail"), "scene_type="),
        (_scene("Touch ID & Passcode", kind="settings_detail"), "platform_scene_kind="),
    ],
)
def test_open_app_settings_matches_settings_scene_identity(scene, evidence):
    registry = VerifierRegistry()
    verifier = registry.resolve("open_app", {"app": "设置", "aliases": ["Settings"]})

    outcome = verifier.verify(_input("open_app", scene, metadata={"app": "设置"}))

    assert outcome.status == "succeeded"
    assert outcome.matched_evidence
    assert outcome.matched_evidence[0].startswith(evidence)


@pytest.mark.smoke
def test_app_switcher_home_unexpected_disqualifying_state_forbids_retry():
    registry = VerifierRegistry()
    verifier = registry.resolve("recents")

    outcome = verifier.verify(_input("recents", _scene("天气", "日历", "照片", "App Store")))

    assert outcome.status == "failed"
    assert outcome.disqualifying_state == "ios_home_unexpected"
    assert outcome.retry_allowed is False


@pytest.mark.smoke
@pytest.mark.parametrize("case", iter_golden_cases(GOLDEN_ROOT), ids=lambda case: case.case_id)
def test_computer_use_verifier_golden_cases(case):
    registry = VerifierRegistry()
    verifier = registry.resolve(case.action, case.metadata)

    outcome = verifier.verify(case.verifier_input())

    assert outcome.status == case.expected_status
    assert registry.resolve(case.action, case.metadata).name == verifier.name
    if case.action == "scroll":
        scene_diff = case.verifier_input().scene_diff or {}
        assert "texts_added" in scene_diff
        assert "texts_removed" in scene_diff
        assert case.verifier_input().frame_diff is None
    if case.expected_disqualifying_state:
        assert outcome.disqualifying_state == case.expected_disqualifying_state


@pytest.mark.smoke
def test_scene_progressed_verifier_treats_same_page_scroll_as_unknown():
    # A tap that merely scrolled the same page (page_id unchanged) is NOT
    # navigation progress; it must not be scored a false success.
    registry = VerifierRegistry()
    verifier = registry.resolve("tap")
    before = _scene("蓝牙", "蜂窝网络", "个人热点", page_id="settings/root")
    after = _scene("设置", "无线局域网", "蓝牙", page_id="settings/root")
    input_ = VerifierInput(
        attempt_id="act_1",
        attempt_group_id="grp_1",
        action={"op": "tap", "args": [], "kwargs": {}, "metadata": {}},
        before_requested=before,
        before_command=before,
        after_scenes=[after],
        after_mode="single_frame",
        frame_diff={"changed": True, "diff_ratio": 0.05},
        scene_diff={
            "changed": True,
            "texts_added": ["设置", "无线局域网"],
            "texts_removed": ["蜂窝网络", "个人热点"],
            "texts_common": ["蓝牙"],
            "page_id_before": "settings/root",
            "page_id_after": "settings/root",
            "scene_type_before": None,
            "scene_type_after": None,
        },
        command_result={"transport_ok": True},
        risk={"level": "medium"},
        after_frame_ids=["frm_after"],
        after_scene_ids=["scn_after"],
    )
    outcome = verifier.verify(input_)
    assert outcome.status == "unknown"
    assert "page identity is unchanged" in (outcome.reason or "")


@pytest.mark.smoke
def test_scene_progressed_verifier_still_succeeds_on_real_navigation():
    registry = VerifierRegistry()
    verifier = registry.resolve("tap")
    before = _scene("蓝牙", "蜂窝网络", page_id="settings/root")
    after = _scene("蜂窝网络", "无SIM卡", page_id="settings/cellular")
    input_ = VerifierInput(
        attempt_id="act_2",
        attempt_group_id="grp_2",
        action={"op": "tap", "args": [], "kwargs": {}, "metadata": {}},
        before_requested=before,
        before_command=before,
        after_scenes=[after],
        after_mode="single_frame",
        frame_diff={"changed": True, "diff_ratio": 0.2},
        scene_diff={
            "changed": True,
            "texts_added": ["无SIM卡"],
            "texts_removed": ["蓝牙"],
            "texts_common": ["蜂窝网络"],
            "page_id_before": "settings/root",
            "page_id_after": "settings/cellular",
            "scene_type_before": None,
            "scene_type_after": None,
        },
        command_result={"transport_ok": True},
        risk={"level": "medium"},
        after_frame_ids=["frm_after"],
        after_scene_ids=["scn_after"],
    )
    outcome = verifier.verify(input_)
    assert outcome.status == "succeeded"
