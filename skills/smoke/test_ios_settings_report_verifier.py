from __future__ import annotations

import json

import pytest

from skills.regression.ios_settings.policy import (
    EXPECTED_ROOT_NAV_TEXT_ZH,
)
from skills.regression.ios_settings.reporting import refresh_report_summaries
from skills.regression.ios_settings.verify_report import EXPECTED_MIN_VISITS, main, validate_report


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
        {"path": ["Settings", "无线局域网", "Kacler_Iptv"], "title": "kacier_iptv", "texts": []},
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
            "texts": ["无线局域网", "我的网络", "kacier", "其他网络"],
        },
    ]

    errors = validate_report(_report(visits=visits, missing=["蓝牙"]), require_exhaustive=False)

    assert any("missing blocked_pages evidence" in error for error in errors)


@pytest.mark.smoke
def test_ios_settings_report_verifier_accepts_blocked_evidence_for_protected_visit():
    visits = [
        {"path": ["Settings"], "title": "设置", "texts": []},
        {
            "path": ["Settings", "无线局域网"],
            "title": "无线局域网",
            "texts": ["无线局域网", "我的网络", "kacier", "其他网络"],
        },
    ]
    report = _report(visits=visits)
    report["blocked_pages"] = [
        {
            "path": ["Settings", "无线局域网"],
            "title": "无线局域网",
            "reason": "dynamic Wi-Fi rows",
            "texts": ["无线局域网", "我的网络", "kacier", "其他网络"],
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
def test_ios_settings_report_verifier_rejects_missing_affordance_in_strict_mode():
    report = _report()
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
def test_ios_settings_report_verifier_cli(tmp_path, capsys):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(_report(), ensure_ascii=False), encoding="utf-8")

    assert main([str(path), "--expected-run-id", "run-test"]) == 0
    assert "OK" in capsys.readouterr().out
