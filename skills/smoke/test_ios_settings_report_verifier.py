from __future__ import annotations

import json

import pytest

from glassbox.config import get_config
from skills.regression.ios_settings.config import SettingsRunConfig
from skills.regression.ios_settings.policy import (
    EXPECTED_ROOT_NAV_TEXT_ZH,
    detect_device_unavailable_root_labels,
)
from skills.regression.ios_settings.report_writer import build_report_payload
from skills.regression.ios_settings.reporting import (
    NavigationFailure,
    PageVisit,
    RejectedCandidate,
    classify_root_coverage,
    refresh_report_summaries,
)
from skills.regression.ios_settings.sections import root_section_ids_for_canonical_labels
from skills.regression.ios_settings.verify_report import EXPECTED_MIN_VISITS, main, validate_report


@pytest.mark.smoke
def test_classify_root_coverage_splits_entered_visible_only_blocked():
    expected = ["无线局域网", "蓝牙", "Face ID与密码", "通用"]
    visits = [
        # entered: detail page captured (more than the bare row label)
        PageVisit(("Settings", "无线局域网"), "无线局域网", ("无线局域网", "接入无线局域网…", "homenet")),
        # visible_only: bare root-row visibility record (single text == label)
        PageVisit(("Settings", "蓝牙"), "蓝牙", ("蓝牙",)),
    ]
    rejected = [RejectedCandidate(("Settings",), "设置", "面容ID与密码", "unsafe_text")]
    base = {"expected": expected, "visited": ["无线局域网", "蓝牙"], "missing": ["Face ID与密码", "通用"]}

    result = classify_root_coverage(base, visits, rejected)

    assert result["entered"] == ["无线局域网"]
    assert result["visible_only"] == ["蓝牙"]
    assert result["blocked"] == ["Face ID与密码"]
    assert result["missing"] == ["Face ID与密码", "通用"]  # base keys preserved
    assert result["visited"] == ["无线局域网", "蓝牙"]      # backward-compat ("seen")


@pytest.mark.smoke
def test_classify_root_coverage_tracks_exempt_and_search_absent_roots():
    expected = ["蜂窝网络", "操作按钮", "待机显示", "钱包与 Apple Pay"]
    visits = [PageVisit(("Settings",), "Settings", ("Settings",))]
    failures = [
        NavigationFailure(("Settings",), "Settings", "蜂窝网络", "search_no_result"),
        NavigationFailure(("Settings",), "Settings", "操作按钮", "search_no_result"),
        NavigationFailure(("Settings",), "Settings", "待机显示", "tap_no_navigation"),
    ]
    base = {"expected": expected, "visited": [], "missing": expected}

    result = classify_root_coverage(base, visits, [], failures)

    assert result["entry_exempt"] == ["钱包与 Apple Pay"]
    assert result["search_absent"] == ["蜂窝网络", "操作按钮"]
    assert result["required_missing"] == ["蜂窝网络", "操作按钮", "待机显示"]
    assert result["entry_exempt_ids"] == ["WALLET"]
    assert result["search_absent_ids"] == ["CELLULAR", "ACTION_BUTTON"]


@pytest.mark.smoke
def test_classify_root_coverage_treats_detected_no_sim_as_entry_exempt():
    expected = ["蜂窝网络", "钱包与 Apple Pay"]
    visits = [PageVisit(("Settings",), "Settings", ("Settings", "No SIM"))]
    base = {"expected": expected, "visited": [], "missing": expected}

    result = classify_root_coverage(base, visits, [], [])

    assert result["device_unavailable"] == ["蜂窝网络"]
    assert result["entry_exempt"] == ["蜂窝网络", "钱包与 Apple Pay"]
    assert result["required_missing"] == []


@pytest.mark.smoke
def test_classify_root_coverage_marks_ipad_profile_roots_unavailable():
    expected = ["操作按钮", "待机显示", "蓝牙", "钱包与 Apple Pay"]
    visits = [PageVisit(("Settings",), "Settings", ("Settings",))]
    failures = [
        NavigationFailure(("Settings",), "Settings", "Action Button", "search_no_result"),
        NavigationFailure(("Settings",), "Settings", "Bluetooth", "search_no_result"),
    ]
    base = {"expected": expected, "visited": [], "missing": expected}

    result = classify_root_coverage(
        base,
        visits,
        [],
        failures,
        platform="ipados",
        phone_model="ipad_mini_7",
    )

    assert result["device_unavailable"] == ["操作按钮", "待机显示"]
    assert result["entry_exempt"] == ["操作按钮", "待机显示", "钱包与 Apple Pay"]
    assert result["search_absent"] == ["操作按钮", "蓝牙"]
    assert result["required_missing"] == ["蓝牙"]


@pytest.mark.smoke
def test_classify_root_coverage_does_not_exempt_sidebar_absence():
    expected = ["通知", "蓝牙"]
    visits = [PageVisit(("Settings",), "Settings", ("Settings",))]
    base = {"expected": expected, "visited": ["蓝牙"], "missing": ["通知"]}

    non_exhaustive = classify_root_coverage(
        {**base, "sidebar_absent": ["通知"]},
        visits,
        [],
    )
    exhaustive = classify_root_coverage(
        {**base, "sidebar_absent": ["通知"], "sidebar_exhaustive": ["true"]},
        visits,
        [],
    )

    assert non_exhaustive["device_unavailable"] == []
    assert non_exhaustive["required_missing"] == ["通知"]
    assert exhaustive["device_unavailable"] == []
    assert exhaustive["entry_exempt"] == []
    assert exhaustive["required_missing"] == ["通知"]


@pytest.mark.smoke
def test_report_payload_threads_search_failures_into_root_coverage(monkeypatch):
    monkeypatch.setattr(
        "skills.regression.ios_settings.report_writer._active_device_report_config",
        lambda: {"phone_model": "iphone_17_pro_max", "platform": "ios"},
    )
    run_config = SettingsRunConfig.for_child_audit(
        max_depth=1,
        max_pages=4,
        max_child_scrolls_per_page=1,
        max_candidates_per_page=0,
        strict_child_candidate_audit=False,
    )
    expected = ["操作按钮", "钱包与 Apple Pay"]

    payload = build_report_payload(
        run_config=run_config,
        visits=[PageVisit(("Settings",), "Settings", ("Settings",))],
        limits_hit=set(),
        blocked_pages=[],
        rejected_candidates=[],
        navigation_failures=[
            NavigationFailure(("Settings",), "Settings", "操作按钮", "search_no_result"),
        ],
        root_coverage={"expected": expected, "visited": [], "missing": expected},
        trace_payload=None,
    )

    root_coverage = payload["root_coverage"]
    assert root_coverage["entry_exempt"] == ["钱包与 Apple Pay"]
    assert root_coverage["search_absent"] == ["操作按钮"]
    assert payload["metrics"]["root_required_expected_count"] == 1
    assert payload["metrics"]["root_entry_exempt_count"] == 1
    assert payload["metrics"]["root_search_absent_count"] == 1


@pytest.mark.smoke
def test_report_payload_filters_resolved_navigation_failures(monkeypatch):
    monkeypatch.setattr(
        "skills.regression.ios_settings.report_writer._active_device_report_config",
        lambda: {"phone_model": "ipad_mini_7", "platform": "ipados"},
    )
    run_config = SettingsRunConfig.for_child_audit(
        max_depth=1,
        max_pages=4,
        max_child_scrolls_per_page=1,
        max_candidates_per_page=0,
        strict_child_candidate_audit=False,
    )

    payload = build_report_payload(
        run_config=run_config,
        visits=[
            PageVisit(("Settings",), "Settings", ("Settings",)),
            PageVisit(("Settings", "通用"), "通用", ("通用", "关于本机")),
        ],
        limits_hit=set(),
        blocked_pages=[],
        rejected_candidates=[],
        navigation_failures=[
            NavigationFailure(("Settings",), "Settings", "通用", "tap_no_navigation"),
        ],
        root_coverage={"expected": ["通用"], "visited": ["通用"], "missing": []},
        trace_payload=None,
    )

    assert payload["navigation_failures"] == []
    assert payload["metrics"]["navigation_failure_count"] == 0
    assert "ios-settings-navigation-tap-no-transition" not in {
        issue["id"] for issue in payload["known_issues"]
    }


@pytest.mark.smoke
def test_report_payload_uses_ipad_device_context_for_unavailable_roots(monkeypatch):
    monkeypatch.setattr(
        "skills.regression.ios_settings.report_writer._active_device_report_config",
        lambda: {"phone_model": "ipad_mini_7", "platform": "ipados"},
    )
    run_config = SettingsRunConfig.for_child_audit(
        max_depth=1,
        max_pages=4,
        max_child_scrolls_per_page=1,
        max_candidates_per_page=0,
        strict_child_candidate_audit=False,
    )
    expected = ["操作按钮", "钱包与 Apple Pay"]

    payload = build_report_payload(
        run_config=run_config,
        visits=[PageVisit(("Settings",), "Settings", ("Settings",))],
        limits_hit=set(),
        blocked_pages=[],
        rejected_candidates=[],
        navigation_failures=[
            NavigationFailure(("Settings",), "Settings", "操作按钮", "search_no_result"),
        ],
        root_coverage={"expected": expected, "visited": [], "missing": expected},
        trace_payload=None,
    )

    assert payload["config"]["platform"] == "ipados"
    assert payload["config"]["phone_model"] == "ipad_mini_7"
    assert payload["root_coverage"]["device_unavailable"] == ["操作按钮"]
    assert payload["root_coverage"]["required_missing"] == []
    assert payload["metrics"]["root_required_expected_count"] == 0


@pytest.mark.smoke
def test_report_payload_records_active_en_ocr_correction_switch(monkeypatch):
    monkeypatch.setenv("GLASSBOX_EN_OCR_CORRECTION", "1")
    get_config.cache_clear()

    try:
        run_config = SettingsRunConfig.for_child_audit(
            max_depth=1,
            max_pages=4,
            max_child_scrolls_per_page=1,
            max_candidates_per_page=0,
            strict_child_candidate_audit=False,
        )

        payload = build_report_payload(
            run_config=run_config,
            visits=[PageVisit(("Settings",), "Settings", ("Settings",))],
            limits_hit=set(),
            blocked_pages=[],
            rejected_candidates=[],
            navigation_failures=[],
            root_coverage={"expected": [], "visited": [], "missing": []},
            trace_payload=None,
        )
    finally:
        get_config.cache_clear()

    assert payload["config"]["en_ocr_correction"] is True


def _report(*, limits=None, visits=None, missing=None):
    visits = visits if visits is not None else [
        {"path": ["Settings"], "title": "设置", "texts": ["设置"]},
        *[
            {"path": ["Settings", label], "title": label, "texts": [label]}
            for label in EXPECTED_ROOT_NAV_TEXT_ZH
        ],
    ]
    for visit in visits:
        title = visit.get("title") if isinstance(visit, dict) else None
        texts = visit.get("texts") if isinstance(visit, dict) else None
        if isinstance(title, str) and title and isinstance(texts, list) and title not in texts:
            texts.insert(0, title)
    visited = [v["path"][1] for v in visits if len(v["path"]) > 1 and v["path"][1] in EXPECTED_ROOT_NAV_TEXT_ZH]
    missing = missing if missing is not None else [
        label for label in EXPECTED_ROOT_NAV_TEXT_ZH if label not in visited
    ]
    report = {
        "run_id": "run-test",
        "config": {
            "require_exhaustive": True,
            "min_pages": EXPECTED_MIN_VISITS,
            "max_pages": 240,
            "max_depth": 4,
            "max_scrolls_per_page": 12,
            "root_coverage_mode": True,
            "max_child_scrolls_per_page": 1,
            "child_navigation_enabled": False,
            "strict_child_candidate_audit": False,
            "max_candidates_per_page": 0,
            "trace_actions": True,
            "save_view_snapshots": False,
            "artifact_dir": None,
            "memory_dir": "/tmp/settings-memory",
            "memory_reuse": False,
        },
        "limits_hit": limits or [],
        "visit_count": len(visits),
        "root_coverage": {
            "expected": list(EXPECTED_ROOT_NAV_TEXT_ZH),
            "visited": visited,
            "missing": missing,
            "expected_ids": root_section_ids_for_canonical_labels(EXPECTED_ROOT_NAV_TEXT_ZH),
            "visited_ids": root_section_ids_for_canonical_labels(visited),
            "missing_ids": root_section_ids_for_canonical_labels(missing),
        },
        "blocked_pages": [],
        "rejected_candidates": [],
        "navigation_failures": [],
        "visits": visits,
    }
    _refresh_report_summaries(report)
    return report


def _refresh_report_summaries(report):
    return refresh_report_summaries(report)


@pytest.mark.smoke
def test_ios_settings_report_verifier_accepts_full_clean_report():
    assert validate_report(_report()) == []


@pytest.mark.smoke
def test_ios_settings_report_verifier_rejects_wrong_expected_run_id():
    errors = validate_report(_report(), expected_run_id="other-run")

    assert any("run_id does not match" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_requires_run_id_in_strict_mode():
    missing = _report()
    missing.pop("run_id")
    empty = _report()
    empty["run_id"] = ""

    assert any("missing run_id" in error for error in validate_report(missing))
    assert any("empty run_id" in error for error in validate_report(empty))
    assert not any(
        "run_id" in error
        for error in validate_report(missing, require_exhaustive=False)
    )


@pytest.mark.smoke
def test_detect_device_unavailable_root_labels_no_sim():
    """A 'No SIM' marker in seen text → 蜂窝网络 is device-unavailable; without it,
    Cellular stays required (so a SIM'd device is unaffected)."""
    assert detect_device_unavailable_root_labels(
        [{"texts": ["Mobile Service", "No SIM"]}]
    ) == {"蜂窝网络"}
    assert detect_device_unavailable_root_labels(
        [{"texts": ["Mobile Service", "中国移动"]}]
    ) == set()


@pytest.mark.smoke
def test_detect_device_unavailable_root_labels_ipad_static_profile():
    failures = [
        {"path": ["Settings"], "title": "Settings", "text": "Action Button", "reason": "search_no_result"},
        {"path": ["Settings"], "title": "Settings", "text": "Bluetooth", "reason": "search_no_result"},
    ]

    assert detect_device_unavailable_root_labels(
        [],
        failures,
        platform="ipados",
        phone_model="ipad_mini_7",
    ) == {"蜂窝网络", "操作按钮", "待机显示", "紧急 SOS"}
    assert detect_device_unavailable_root_labels(
        [],
        failures,
        platform="ipados",
        phone_model=None,
    ) == set()
    assert detect_device_unavailable_root_labels(
        [],
        failures,
        platform="ios",
        phone_model="iphone_17_pro_max",
    ) == set()


def _report_without_cellular(*, root_texts):
    visits = [
        {"path": ["Settings"], "title": "设置", "texts": root_texts},
        *[
            {"path": ["Settings", label], "title": label, "texts": [label, "body line"]}
            for label in EXPECTED_ROOT_NAV_TEXT_ZH
            if label != "蜂窝网络"
        ],
    ]
    return _report(visits=visits)


@pytest.mark.smoke
def test_verifier_auto_exempts_cellular_on_no_sim():
    """No-SIM phone: 蜂窝网络 is unreachable and an exhaustive run must still pass,
    with no manual --device-unavailable-root flag."""
    report = _report_without_cellular(root_texts=["设置", "蜂窝网络", "No SIM"])
    errors = validate_report(report)
    assert not any("missing expected root pages" in e for e in errors), errors


@pytest.mark.smoke
def test_verifier_still_requires_cellular_when_no_marker():
    """No no-SIM marker → 蜂窝网络 stays required, so a real nav regression is not
    silently hidden."""
    report = _report_without_cellular(root_texts=["设置", "蜂窝网络"])
    errors = validate_report(report)
    assert any("missing expected root pages" in e for e in errors)


@pytest.mark.smoke
def test_verifier_auto_exempts_ipad_search_absent_device_roots():
    visits = [
        {"path": ["Settings"], "title": "Settings", "texts": ["Settings"]},
        *[
            {"path": ["Settings", label], "title": label, "texts": [label, "body line"]}
            for label in EXPECTED_ROOT_NAV_TEXT_ZH
            if label not in {"蜂窝网络", "操作按钮", "待机显示", "紧急 SOS"}
        ],
    ]
    report = _report(
        visits=visits,
        missing=["蜂窝网络", "操作按钮", "待机显示", "紧急 SOS"],
    )
    report["config"]["platform"] = "ipados"
    report["config"]["phone_model"] = "ipad_mini_7"
    report["navigation_failures"] = [
        {"path": ["Settings"], "title": "Settings", "text": label, "reason": "search_no_result"}
        for label in ("蜂窝网络", "操作按钮", "待机显示", "紧急 SOS")
    ]
    _refresh_report_summaries(report)

    errors = validate_report(report)

    assert not any("missing expected root pages" in e for e in errors), errors


@pytest.mark.smoke
def test_report_summaries_downgrade_entry_exempt_navigation_failures():
    report = _report(
        visits=[
            {"path": ["Settings"], "title": "Settings", "texts": ["Settings"]},
            *[
                {"path": ["Settings", label], "title": label, "texts": [label, "body line"]}
                for label in EXPECTED_ROOT_NAV_TEXT_ZH
                if label != "操作按钮"
            ],
        ],
        missing=["操作按钮"],
    )
    report["config"]["platform"] = "ipados"
    report["config"]["phone_model"] = "ipad_mini_7"
    report["root_coverage"]["entry_exempt"] = ["操作按钮"]
    report["navigation_failures"] = [
        {"path": ["Settings"], "title": "Settings", "text": "操作按钮", "reason": "search_no_result"},
    ]
    _refresh_report_summaries(report)

    issue = next(item for item in report["known_issues"] if item["id"] == "ios-settings-navigation-tap-no-transition")
    assert issue["severity"] == "warning"


@pytest.mark.smoke
def test_verifier_still_requires_ipad_search_absent_roots_without_ipad_context():
    report = _report(
        visits=[
            {"path": ["Settings"], "title": "Settings", "texts": ["Settings"]},
            *[
                {"path": ["Settings", label], "title": label, "texts": [label, "body line"]}
                for label in EXPECTED_ROOT_NAV_TEXT_ZH
                if label != "操作按钮"
            ],
        ],
        missing=["操作按钮"],
    )
    report["navigation_failures"] = [
        {"path": ["Settings"], "title": "Settings", "text": "操作按钮", "reason": "search_no_result"},
    ]
    _refresh_report_summaries(report)

    errors = validate_report(report)

    assert any("missing expected root pages" in e for e in errors)


@pytest.mark.smoke
def test_verifier_rejects_sidebar_absent_root_even_with_exhaustive_evidence():
    missing = ["通知"]
    report = _report(
        visits=[
            {"path": ["Settings"], "title": "Settings", "texts": ["Settings"]},
            *[
                {"path": ["Settings", label], "title": label, "texts": [label, "body line"]}
                for label in EXPECTED_ROOT_NAV_TEXT_ZH
                if label != "通知"
            ],
        ],
        missing=missing,
    )
    report["root_coverage"]["sidebar_absent"] = ["通知"]
    report["root_coverage"]["sidebar_absent_ids"] = root_section_ids_for_canonical_labels(["通知"])
    report["root_coverage"]["sidebar_exhaustive"] = ["true"]
    _refresh_report_summaries(report)

    errors = validate_report(report)

    assert any("missing expected root pages" in e for e in errors), errors


@pytest.mark.smoke
def test_verifier_rejects_sidebar_absent_root_without_exhaustive_evidence():
    report = _report(missing=["通知"])
    report["root_coverage"]["sidebar_absent"] = ["通知"]
    report["root_coverage"]["sidebar_absent_ids"] = root_section_ids_for_canonical_labels(["通知"])
    _refresh_report_summaries(report)

    errors = validate_report(report)

    assert any("sidebar_absent requires sidebar_exhaustive" in e for e in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_rejects_missing_root_pages():
    visits = [
        {"path": ["Settings"], "title": "设置", "texts": []},
        *[
            {"path": ["Settings", label], "title": label, "texts": []}
            for label in EXPECTED_ROOT_NAV_TEXT_ZH
            if label != "蓝牙"
        ],
    ]
    errors = validate_report(_report(visits=visits))

    assert any("missing expected root pages" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_recomputes_root_coverage_from_visits():
    visits = [
        {"path": ["Settings"], "title": "设置", "texts": []},
        {"path": ["Settings", "无线局域网"], "title": "无线局域网", "texts": []},
    ]
    report = _report(visits=visits, missing=[])
    report["root_coverage"]["visited"] = list(EXPECTED_ROOT_NAV_TEXT_ZH)

    errors = validate_report(report)

    assert any("root_coverage.visited does not match visits" in error for error in errors)
    assert any("root_coverage.missing does not match visits" in error for error in errors)
    assert any("missing expected root pages" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_accepts_graph_entered_root_coverage():
    visits = [
        {"path": ["Settings"], "title": "设置", "texts": ["设置"]},
        *[
            {"path": ["Settings", label], "title": label, "texts": [label]}
            for label in EXPECTED_ROOT_NAV_TEXT_ZH
            if label != "蓝牙"
        ],
    ]
    report = _report(visits=visits)
    report["root_coverage"]["visited"] = list(EXPECTED_ROOT_NAV_TEXT_ZH)
    report["root_coverage"]["missing"] = []
    report["root_coverage"]["entered_graph"] = ["蓝牙"]
    report["root_coverage"]["visited_ids"] = root_section_ids_for_canonical_labels(EXPECTED_ROOT_NAV_TEXT_ZH)
    report["root_coverage"]["missing_ids"] = []
    _refresh_report_summaries(report)

    errors = validate_report(report)

    assert not any("visit count is below configured minimum" in error for error in errors), errors
    assert not any("root_coverage.visited does not match visits" in error for error in errors), errors
    assert not any("missing expected root pages" in error for error in errors), errors


@pytest.mark.smoke
def test_ios_settings_report_verifier_checks_root_coverage_ids():
    report = _report()
    report["root_coverage"]["visited_ids"] = []

    errors = validate_report(report)

    assert any("root_coverage.visited_ids does not match root_coverage.visited" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_requires_root_path_page_evidence():
    report = _report()
    for visit in report["visits"]:
        if visit["path"] == ["Settings", "蓝牙"]:
            visit["title"] = "通用"
            visit["texts"] = ["通用"]

    errors = validate_report(report)

    assert any("root path lacks matching page evidence" in error for error in errors)
    assert any("root_coverage.visited does not match visits" in error for error in errors)
    assert any("missing expected root pages" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_accepts_known_shortened_root_page_titles():
    report = _report()
    shortened = {
        "Safari浏览器": "Safari",
        "FaceTime 通话": "FaceTime",
        "主屏幕与 App 资源库": "主屏幕",
        "钱包与 Apple Pay": "钱包",
    }
    for visit in report["visits"]:
        if len(visit["path"]) >= 2 and visit["path"][1] in shortened:
            title = shortened[visit["path"][1]]
            visit["title"] = title
            visit["texts"] = [title]

    _refresh_report_summaries(report)
    assert validate_report(report) == []


@pytest.mark.smoke
def test_ios_settings_report_verifier_counts_english_root_labels_as_canonical_coverage():
    report = _report()
    replacements = {
        "无线局域网": "Wi-Fi",
        "蓝牙": "Bluetooth",
        "通用": "General",
        "相机": "Camera",
    }
    for visit in report["visits"]:
        if len(visit["path"]) >= 2 and visit["path"][1] in replacements:
            label = replacements[visit["path"][1]]
            visit["path"][1] = label
            visit["title"] = label
            visit["texts"] = [label]

    _refresh_report_summaries(report)
    assert validate_report(report) == []


@pytest.mark.smoke
def test_ios_settings_report_verifier_uses_report_locale_for_root_evidence():
    report = _report(
        visits=[
            {"path": ["Settings"], "title": "Settings", "texts": ["Settings"]},
            {"path": ["Settings", "无线局域网"], "title": "WLAN", "texts": ["WLAN", "Ask To Join Networks"]},
        ],
    )
    report["locale"] = "en-HK"
    _refresh_report_summaries(report)

    errors = validate_report(report, require_exhaustive=False)

    assert not any("root_coverage.visited does not match visits" in error for error in errors)
    assert not any("root_coverage.missing does not match visits" in error for error in errors)
    assert not any("root path lacks matching page evidence" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_rejects_non_settings_visit_paths():
    report = _report(
        visits=[
            {"path": ["OtherApp"], "title": "设置", "texts": []},
            {"path": ["OtherApp", "无线局域网"], "title": "无线局域网", "texts": []},
        ],
        missing=[],
    )

    errors = validate_report(report)

    assert any("path does not start at Settings" in error for error in errors)
    assert any("root_coverage.visited does not match visits" in error for error in errors)
    assert any("missing expected root pages" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_rejects_invalid_visit_payload():
    report = _report()
    report["visits"][0]["title"] = ""
    report["visits"][1]["texts"] = "not-a-list"

    errors = validate_report(report)

    assert any("visit 0 has invalid title" in error for error in errors)
    assert any("visit 1 has invalid texts" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_requires_visit_title_text_evidence():
    report = _report()
    report["visits"][0]["texts"] = ["无线局域网", "蓝牙"]

    errors = validate_report(report)

    assert any("title was not present in OCR texts" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_rejects_traversal_limits():
    errors = validate_report(_report(limits=["max_pages"]))

    assert any("traversal limits" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_treats_scroll_overshoot_as_soft_signal():
    report = _report(limits=["scroll_overshoot"])

    assert validate_report(report) == []
    assert report["metrics"]["exhaustive_ready"] is True
    assert report["failure_categories"]["perception"] == ["ios-settings-scroll-overshoot"]


@pytest.mark.smoke
def test_ios_settings_report_verifier_treats_max_depth_as_soft_budget_signal():
    report = _report(limits=["max_depth"])

    assert validate_report(report) == []
    assert report["metrics"]["exhaustive_ready"] is True
    assert report["known_issues"][0]["evidence"] == ["max_depth"]


@pytest.mark.smoke
def test_ios_settings_report_verifier_rejects_non_exhaustive_config_in_strict_mode():
    report = _report()
    report["config"]["require_exhaustive"] = False

    errors = validate_report(report)

    assert any("not produced in exhaustive mode" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_requires_full_config_schema():
    report = _report()
    report["config"].pop("root_coverage_mode")
    report["config"]["max_depth"] = True
    report["config"]["memory_reuse"] = "0"
    report["config"]["memory_dir"] = 123

    errors = validate_report(report)

    assert any("config.root_coverage_mode must be a boolean" in error for error in errors)
    assert any("config.max_depth must be an integer" in error for error in errors)
    assert any("config.memory_reuse must be a boolean" in error for error in errors)
    assert any("config.memory_dir must be null or string" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_checks_optional_ab_switch_config_types():
    report = _report()
    report["config"].update(
        {
            "language": 123,
            "region": 456,
            "ocr": False,
            "text_detector": None,
            "en_ocr_correction": "0",
            "ios_closed_set_canonicalization_enabled": "0",
            "ocr_minimum_text_height": "0",
            "ocr_unsharp_mask": "1",
            "ocr_tiling_enabled": "1",
            "ocr_tiling_rows": True,
            "ocr_tiling_overlap": "0.15",
            "ui_layout_segmentation_enabled": "1",
        }
    )

    errors = validate_report(report)

    assert any("config.language must be a string" in error for error in errors)
    assert any("config.region must be null or string" in error for error in errors)
    assert any("config.ocr must be a string" in error for error in errors)
    assert any("config.text_detector must be a string" in error for error in errors)
    assert any("config.en_ocr_correction must be a boolean" in error for error in errors)
    assert any("config.ios_closed_set_canonicalization_enabled must be a boolean" in error for error in errors)
    assert any("config.ocr_minimum_text_height must be null or number" in error for error in errors)
    assert any("config.ocr_unsharp_mask must be null or boolean" in error for error in errors)
    assert any("config.ocr_tiling_enabled must be a boolean" in error for error in errors)
    assert any("config.ocr_tiling_rows must be an integer" in error for error in errors)
    assert any("config.ocr_tiling_overlap must be a number" in error for error in errors)
    assert any("config.ui_layout_segmentation_enabled must be a boolean" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_requires_root_coverage_shape_in_strict_mode():
    report = _report()
    report["config"]["root_coverage_mode"] = False
    report["config"]["child_navigation_enabled"] = False

    errors = validate_report(report)

    assert any("root coverage mode or child navigation" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_allows_strict_child_navigation_mode():
    report = _report()
    report["config"]["root_coverage_mode"] = False
    report["config"]["child_navigation_enabled"] = True

    assert validate_report(report) == []


@pytest.mark.smoke
def test_ios_settings_report_verifier_rejects_mixed_root_coverage_and_child_navigation():
    report = _report()
    report["config"]["root_coverage_mode"] = True
    report["config"]["child_navigation_enabled"] = True

    errors = validate_report(report)

    assert any("strict root coverage report must not enable child navigation" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_rejects_candidate_cap_in_strict_mode():
    report = _report()
    report["config"]["max_candidates_per_page"] = 3

    errors = validate_report(report)

    assert any("must not cap candidates" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_rejects_too_small_page_budget_in_strict_mode():
    report = _report()
    report["config"]["min_pages"] = 1
    report["config"]["max_pages"] = 1

    errors = validate_report(report)

    assert any("config.min_pages is too small" in error for error in errors)
    assert any("config.max_pages is too small" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_rejects_visit_count_below_minimum_in_strict_mode():
    report = _report()
    report["config"]["min_pages"] = len(report["visits"]) + 1
    report["config"]["max_pages"] = len(report["visits"]) + 1

    errors = validate_report(report)

    assert any("visit count is below configured minimum" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_rejects_paths_deeper_than_configured_limit():
    report = _report()
    report["config"]["max_depth"] = 1
    report["visits"].append({
        "path": ["Settings", "通用", "关于本机"],
        "title": "关于本机",
        "texts": ["关于本机"],
    })
    report["visit_count"] = len(report["visits"])

    errors = validate_report(report, require_exhaustive=False)

    assert any("path exceeds configured max_depth" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_does_not_require_root_label_evidence_on_nested_pages():
    report = _report()
    report["visits"].append({
        "path": ["Settings", "电池", "充电"],
        "title": "充电",
        "texts": ["充电"],
    })
    report["visit_count"] = len(report["visits"])

    errors = validate_report(report, require_exhaustive=False)

    assert not any("root path lacks matching page evidence" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_allows_scrolled_root_viewport_with_section_title():
    report = _report()
    report["visits"].append({
        "path": ["Settings", "电池"],
        "title": "充电",
        "texts": ["充电", "充电上限", "优化电池充电"],
    })
    report["visit_count"] = len(report["visits"])

    errors = validate_report(report, require_exhaustive=False)

    assert not any("root path lacks matching page evidence" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_rejects_missing_config_in_strict_mode():
    report = _report()
    report.pop("config")

    errors = validate_report(report)

    assert any("missing or invalid config" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_rejects_dynamic_wifi_path_even_when_partial_allowed():
    visits = [
        {"path": ["Settings"], "title": "设置", "texts": []},
        {"path": ["Settings", "无线局域网"], "title": "无线局域网", "texts": []},
        {"path": ["Settings", "无线局域网", "Homenet_Iptv"], "title": "homenet_iptv", "texts": []},
    ]
    errors = validate_report(_report(visits=visits, missing=["蓝牙"]), require_exhaustive=False)

    assert any("unsafe dynamic/settings row" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_rejects_missing_blocked_pages_schema():
    report = _report()
    report.pop("blocked_pages")

    errors = validate_report(report)

    assert any("blocked_pages" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_rejects_missing_rejected_candidates_schema():
    report = _report()
    report.pop("rejected_candidates")

    errors = validate_report(report)

    assert any("rejected_candidates" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_rejects_missing_navigation_failures_schema():
    report = _report()
    report.pop("navigation_failures")

    errors = validate_report(report)

    assert any("navigation_failures" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_rejects_missing_metrics_schema():
    report = _report()
    report.pop("metrics")

    errors = validate_report(report)

    assert any("metrics" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_rejects_missing_known_issues_schema():
    report = _report()
    report.pop("known_issues")

    errors = validate_report(report)

    assert any("known_issues" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_rejects_missing_failure_categories_schema():
    report = _report()
    report.pop("failure_categories")

    errors = validate_report(report)

    assert any("failure_categories" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_requires_known_issue_category_mapping():
    report = _report(limits=["max_scrolls_per_page"])
    report["failure_categories"]["efficiency"] = []

    errors = validate_report(report)

    assert any("failure_categories.efficiency missing known issue id" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_rejects_category_without_known_issue_details():
    report = _report()
    report["failure_categories"]["recovery"] = ["ios-settings-search-unavailable"]

    errors = validate_report(report, require_exhaustive=False)

    assert any("references unknown known issue id" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_rejects_stale_metrics():
    report = _report()
    report["metrics"]["visit_count"] = 1

    errors = validate_report(report)

    assert any("metrics.visit_count mismatch" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_requires_blocked_evidence_for_protected_visit():
    visits = [
        {"path": ["Settings"], "title": "设置", "texts": []},
        {
            "path": ["Settings", "无线局域网"],
            "title": "无线局域网",
            "texts": ["无线局域网", "我的网络", "homenet", "其他网络"],
        },
    ]

    errors = validate_report(_report(visits=visits, missing=["蓝牙"]), require_exhaustive=False)

    assert any("missing blocked_pages evidence" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_does_not_require_blocked_evidence_for_root_sidebar_texts():
    visits = [
        {
            "path": ["Settings"],
            "title": "Settings",
            "texts": ["Settings", "Notifications", "Display As", "Show Previews"],
        },
        {"path": ["Settings", "蓝牙"], "title": "蓝牙", "texts": ["蓝牙"]},
    ]

    errors = validate_report(_report(visits=visits, missing=["无线局域网"]), require_exhaustive=False)

    assert not any("protected page is missing blocked_pages evidence: Settings " in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_allows_terminal_max_depth_protected_sample():
    visits = [
        {"path": ["Settings"], "title": "Settings", "texts": ["Settings"]},
        {
            "path": ["Settings", "通知"],
            "title": "Notifications",
            "texts": ["Notifications", "Display As", "Show Previews"],
        },
    ]
    report = _report(visits=visits, missing=["蓝牙"])
    report["config"]["child_navigation_enabled"] = True
    report["config"]["root_coverage_mode"] = False
    report["config"]["max_depth"] = 1
    _refresh_report_summaries(report)

    errors = validate_report(report, require_exhaustive=False)

    assert not any("protected page is missing blocked_pages evidence" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_accepts_blocked_evidence_for_protected_visit():
    visits = [
        {"path": ["Settings"], "title": "设置", "texts": []},
        {
            "path": ["Settings", "无线局域网"],
            "title": "无线局域网",
            "texts": ["无线局域网", "我的网络", "homenet", "其他网络"],
        },
    ]
    report = _report(visits=visits)
    report["blocked_pages"] = [
        {
            "path": ["Settings", "无线局域网"],
            "title": "无线局域网",
            "reason": "dynamic Wi-Fi rows",
            "texts": ["无线局域网", "我的网络", "homenet", "其他网络"],
        },
    ]
    _refresh_report_summaries(report)

    errors = validate_report(report, require_exhaustive=False)

    assert errors == []


@pytest.mark.smoke
def test_ios_settings_report_verifier_requires_auth_blocked_evidence_for_passcode_prompt():
    visits = [
        {"path": ["Settings"], "title": "设置", "texts": []},
        {
            "path": ["Settings", "Face ID与密码"],
            "title": "输入密码",
            "texts": ["输入密码", "请输入iPhone密码以继续"],
        },
    ]

    errors = validate_report(_report(visits=visits, missing=["蓝牙"]), require_exhaustive=False)

    assert any("protected page is missing blocked_pages evidence" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_accepts_auth_blocked_evidence():
    visits = [
        {"path": ["Settings"], "title": "设置", "texts": []},
        {
            "path": ["Settings", "Face ID与密码"],
            "title": "输入密码",
            "texts": ["输入密码", "请输入iPhone密码以继续"],
        },
    ]
    report = _report(visits=visits)
    report["blocked_pages"] = [
        {
            "path": ["Settings", "Face ID与密码"],
            "title": "输入密码",
            "reason": "authentication required",
            "texts": ["输入密码", "请输入iPhone密码以继续"],
        },
    ]
    _refresh_report_summaries(report)

    errors = validate_report(report, require_exhaustive=False)

    assert errors == []


@pytest.mark.smoke
def test_ios_settings_report_verifier_rejects_blocked_page_not_visited():
    report = _report(
        visits=[
            {"path": ["Settings"], "title": "设置", "texts": []},
            {"path": ["Settings", "蓝牙"], "title": "蓝牙", "texts": []},
        ],
        missing=["无线局域网"],
    )
    report["blocked_pages"] = [
        {
            "path": ["Settings", "无线局域网"],
            "title": "无线局域网",
            "reason": "dynamic Wi-Fi rows",
            "texts": ["无线局域网", "我的网络"],
        },
    ]

    errors = validate_report(report, require_exhaustive=False)

    assert any("blocked page path was not visited" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_rejects_blocked_reason_without_text_evidence():
    report = _report()
    report["blocked_pages"] = [
        {
            "path": ["Settings", "通用"],
            "title": "通用",
            "reason": "dynamic Wi-Fi rows",
            "texts": ["通用", "关于本机"],
        },
    ]

    errors = validate_report(report, require_exhaustive=False)

    assert any("reason lacks matching text evidence" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_rejects_non_settings_blocked_and_rejected_paths():
    report = _report()
    report["blocked_pages"] = [
        {
            "path": ["OtherApp", "无线局域网"],
            "title": "无线局域网",
            "reason": "dynamic Wi-Fi rows",
            "texts": ["无线局域网", "我的网络"],
        },
    ]
    report["rejected_candidates"] = [
        {
            "path": ["OtherApp", "通用"],
            "title": "通用",
            "text": "新设置页面",
            "reason": "unknown_navigation_label",
        },
    ]

    errors = validate_report(report, require_exhaustive=False)

    assert any("blocked_pages[0] path does not start at Settings" in error for error in errors)
    assert any("rejected_candidates[0] path does not start at Settings" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_rejects_unknown_candidate_in_strict_mode():
    report = _report()
    report["config"]["strict_child_candidate_audit"] = True
    report["visits"].append({
        "path": ["Settings", "通用"],
        "title": "通用",
        "texts": ["新设置页面"],
    })
    report["visit_count"] = len(report["visits"])
    report["rejected_candidates"] = [
        {
            "path": ["Settings", "通用"],
            "title": "通用",
            "text": "新设置页面",
            "reason": "unknown_navigation_label",
        },
    ]

    errors = validate_report(report)

    assert any("navigation candidate requires" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_allows_unknown_candidate_when_audit_not_strict():
    report = _report()
    report["visits"][0]["texts"] = [*report["visits"][0]["texts"], "Apple Pencil"]
    report["rejected_candidates"] = [
        {
            "path": ["Settings"],
            "title": "Settings",
            "text": "Apple Pencil",
            "reason": "unknown_navigation_label",
        },
    ]
    _refresh_report_summaries(report)

    errors = validate_report(report)

    assert not any("navigation candidate requires" in error for error in errors)
    assert report["known_issues"][-1]["id"] == "ios-settings-navigation-candidate-policy-gap"
    assert report["known_issues"][-1]["severity"] == "warning"


@pytest.mark.smoke
def test_ios_settings_report_verifier_allows_root_candidate_evidence_from_split_view_visit():
    report = _report()
    report["visits"][0]["texts"] = [
        text for text in report["visits"][0]["texts"] if text != "iCloud"
    ]
    report["visits"].append({
        "path": ["Settings", "Apps"],
        "title": "Apps",
        "texts": ["Apps", "App Store", "iCloud"],
    })
    report["visit_count"] = len(report["visits"])
    report["rejected_candidates"] = [
        {
            "path": ["Settings"],
            "title": "Notifications",
            "text": "iCloud",
            "reason": "unsafe_text",
        },
    ]
    _refresh_report_summaries(report)

    errors = validate_report(report)

    assert not any("text was not present in visited page" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_rejects_missing_affordance_in_strict_mode():
    report = _report()
    report["config"]["strict_child_candidate_audit"] = True
    report["visits"].append({
        "path": ["Settings", "蜂窝网络"],
        "title": "蜂窝网络",
        "texts": ["Safari浏览器"],
    })
    report["visit_count"] = len(report["visits"])
    report["rejected_candidates"] = [
        {
            "path": ["Settings", "蜂窝网络"],
            "title": "蜂窝网络",
            "text": "Safari浏览器",
            "reason": "missing_navigation_affordance",
        },
    ]

    errors = validate_report(report)

    assert any("navigation candidate requires" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_allows_known_unsafe_candidate_in_strict_mode():
    report = _report()
    report["visits"].append({
        "path": ["Settings", "通用"],
        "title": "通用",
        "texts": ["通用", "关闭"],
    })
    report["visit_count"] = len(report["visits"])
    report["rejected_candidates"] = [
        {
            "path": ["Settings", "通用"],
            "title": "通用",
            "text": "关闭",
            "reason": "unsafe_text",
        },
    ]
    _refresh_report_summaries(report)

    assert validate_report(report) == []


@pytest.mark.smoke
def test_ios_settings_report_verifier_accepts_section_header_rejection_reason():
    report = _report()
    report["visits"].append({
        "path": ["Settings", "通用"],
        "title": "通用",
        "texts": ["通用", "自动填充与密码"],
    })
    report["visit_count"] = len(report["visits"])
    report["rejected_candidates"] = [
        {
            "path": ["Settings", "通用"],
            "title": "通用",
            "text": "自动填充与密码",
            "reason": "section_header",
        },
    ]
    _refresh_report_summaries(report)

    assert validate_report(report) == []


@pytest.mark.smoke
def test_ios_settings_report_verifier_rejects_rejected_candidate_without_visit_text_evidence():
    report = _report()
    report["rejected_candidates"] = [
        {
            "path": ["Settings", "通用"],
            "title": "通用",
            "text": "未出现在页面上",
            "reason": "unknown_navigation_label",
        },
    ]

    errors = validate_report(report, require_exhaustive=False)

    assert any("text was not present in visited page" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_rejects_navigation_failure_in_strict_mode():
    report = _report()
    report["visits"].append({
        "path": ["Settings", "通用"],
        "title": "通用",
        "texts": ["通用", "关于本机"],
    })
    report["visit_count"] = len(report["visits"])
    report["navigation_failures"] = [
        {
            "path": ["Settings", "通用"],
            "title": "通用",
            "text": "关于本机",
            "reason": "tap_no_navigation",
        },
    ]

    errors = validate_report(report)

    assert any("navigation candidate did not open" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_allows_resolved_navigation_failure_in_strict_mode():
    report = _report()
    report["navigation_failures"] = [
        {
            "path": ["Settings"],
            "title": "Settings",
            "text": "通用",
            "reason": "tap_no_navigation",
        },
    ]
    _refresh_report_summaries(report)

    assert report["navigation_failures"] == []
    assert validate_report(report) == []


@pytest.mark.smoke
def test_ios_settings_report_verifier_allows_navigation_failure_in_partial_mode_with_evidence():
    report = _report()
    report["visits"].append({
        "path": ["Settings", "通用"],
        "title": "通用",
        "texts": ["通用", "关于本机"],
    })
    report["visit_count"] = len(report["visits"])
    report["navigation_failures"] = [
        {
            "path": ["Settings", "通用"],
            "title": "通用",
            "text": "关于本机",
            "reason": "tap_no_navigation",
        },
    ]
    _refresh_report_summaries(report)

    assert validate_report(report, require_exhaustive=False) == []


@pytest.mark.smoke
def test_ios_settings_report_verifier_allows_search_failure_without_visible_row_text_in_partial_mode():
    report = _report()
    report["navigation_failures"] = [
        {
            "path": ["Settings"],
            "title": "Settings",
            "text": "无线局域网",
            "reason": "search_no_result",
        },
    ]
    _refresh_report_summaries(report)

    assert validate_report(report, require_exhaustive=False) == []


@pytest.mark.smoke
def test_ios_settings_report_verifier_rejects_navigation_failure_without_evidence():
    report = _report()
    report["navigation_failures"] = [
        {
            "path": ["Settings", "未访问页面"],
            "title": "未访问页面",
            "text": "未出现在页面上",
            "reason": "tap_no_navigation",
        },
    ]

    errors = validate_report(report, require_exhaustive=False)

    assert any("navigation failure path was not visited" in error for error in errors)
    assert any("text was not present in visited page" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_aggregates_text_evidence_across_same_path_visits():
    report = _report()
    report["visits"].extend([
        {
            "path": ["Settings", "通用"],
            "title": "通用",
            "texts": ["通用"],
        },
        {
            "path": ["Settings", "通用"],
            "title": "通用",
            "texts": ["滚动新页面"],
        },
    ])
    report["visit_count"] = len(report["visits"])
    report["rejected_candidates"] = [
        {
            "path": ["Settings", "通用"],
            "title": "通用",
            "text": "滚动新页面",
            "reason": "unknown_navigation_label",
        },
    ]

    errors = validate_report(report, require_exhaustive=False)

    assert not any("text was not present in visited page" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_accepts_compact_text_evidence():
    report = _report()
    report["rejected_candidates"] = [
        {
            "path": ["Settings"],
            "title": "Settings",
            "text": "Game Center",
            "reason": "unsafe_text",
        },
    ]
    report["visits"][0]["texts"] = [*report["visits"][0]["texts"], "GameCenter"]

    errors = validate_report(report, require_exhaustive=False)

    assert not any("text was not present in visited page" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_cli(tmp_path, capsys):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(_report(), ensure_ascii=False), encoding="utf-8")

    assert main([str(path), "--expected-run-id", "run-test"]) == 0
    assert "OK" in capsys.readouterr().out
