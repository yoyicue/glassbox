from __future__ import annotations

import json

from glassbox.cognition import Box, Scene, UIElement
from skills.regression.ios_settings import child_audit
from skills.regression.ios_settings import crawler as settings_crawler
from skills.regression.ios_settings import reporting as settings_reporting


def _el(text: str, x: int, y: int, w: int = 90, h: int = 24, ty: str = "text") -> UIElement:
    return UIElement(type=ty, box=Box(x=x, y=y, w=w, h=h), text=text, confidence=0.9)


def _scene(*elements: UIElement) -> Scene:
    return Scene(frame_id=0, timestamp=0.0, elements=list(elements))


ROOT = _scene(
    _el("设置", 198, 72, w=48),
    _el("无线局域网", 54, 218, w=88, ty="list_item"),
    _el("蓝牙", 54, 272, w=42, ty="list_item"),
    _el("通用", 54, 326, w=42, ty="list_item"),
    _el("辅助功能", 54, 380, w=72, ty="list_item"),
)
GENERAL = _scene(
    _el("<", 18, 74, w=18, ty="nav_back"),
    _el("通用", 198, 72, w=42),
    _el("关于本机", 54, 286, w=72, ty="list_item"),
    _el("软件更新", 54, 340, w=72, ty="list_item"),
)
ABOUT = _scene(
    _el("<", 18, 74, w=18, ty="nav_back"),
    _el("关于本机", 180, 72, w=88),
    _el("名称", 54, 286, w=42),
    _el("软件版本", 54, 340, w=72),
)
ACCESSIBILITY = _scene(
    _el("<", 18, 74, w=18, ty="nav_back"),
    _el("辅助功能", 180, 72, w=88),
    _el("个性化", 54, 286, w=72),
)


class FakePhone:
    def __init__(self):
        self.stack = ["root"]
        self.actions: list[tuple[str, object]] = []

    def viewport_size(self):

        return self._viewport_size()

    def _viewport_size(self):
        return 448, 973

    def perceive(self):
        return {
            "root": ROOT,
            "general": GENERAL,
            "about": ABOUT,
            "accessibility": ACCESSIBILITY,
        }[self.stack[-1]]

    def invalidate_perceive_cache(self):
        pass

    def home(self):
        self.actions.append(("home", None))
        self.stack = ["root"]

    def key(self, mod, key):
        self.actions.append(("key", (mod, key)))
        if len(self.stack) > 1:
            self.stack.pop()

    def tap_xy(self, x, y):
        self.actions.append(("tap_xy", (x, y)))
        current = self.stack[-1]
        if current == "root" and 300 <= y <= 350:
            self.stack.append("general")
        elif current == "root" and 360 <= y <= 400:
            self.stack.append("accessibility")
        elif current == "general" and 260 <= y <= 315:
            self.stack.append("about")
        elif 45 <= y <= 100 and len(self.stack) > 1:
            self.stack.pop()

    def wheel_scroll_up(self):
        self.actions.append(("wheel_scroll_up", None))

    def wheel_scroll_down(self):
        self.actions.append(("wheel_scroll_down", None))


def test_high_value_child_audit_reaches_child_depth(monkeypatch):
    monkeypatch.setattr(settings_crawler.time, "sleep", lambda _: None)
    phone = FakePhone()

    report = child_audit.probe_high_value_child_audit(
        phone,
        target_root_labels=("通用",),
        max_depth=2,
        max_pages=8,
        max_child_scrolls_per_page=1,
        max_candidates_per_page=1,
    )

    assert report["status"] == "passed"
    assert report["opened_target_roots"] == ["通用"]
    assert report["visited_child_paths"] == [["Settings", "通用", "关于本机"]]
    assert report["target_roots_with_child"] == ["通用"]
    assert report["target_roots_missing_child"] == []
    assert report["metrics"]["root_expected_count"] == 1
    assert report["metrics"]["root_required_expected_count"] == 1
    assert report["metrics"]["target_roots_with_child_count"] == 1
    assert report["metrics"]["target_roots_missing_child_count"] == 0
    assert report["metrics"]["child_visit_count"] == 1
    assert all(not values for values in report["failure_categories"].values())


def test_high_value_child_audit_reports_unopened_target(monkeypatch):
    monkeypatch.setattr(settings_crawler.time, "sleep", lambda _: None)
    phone = FakePhone()

    report = child_audit.probe_high_value_child_audit(
        phone,
        target_root_labels=("不存在",),
        max_depth=2,
        max_pages=8,
        max_child_scrolls_per_page=1,
        max_candidates_per_page=1,
    )

    assert report["status"] == "failed"
    assert report["target_failures"] == [{"label": "不存在", "reason": "target_root_not_opened"}]
    assert report["failure_categories"]["recovery"] == [
        "ios-settings-child-audit-target-root-unopened"
    ]


def test_high_value_child_audit_requires_each_target_root_to_reach_child(monkeypatch):
    monkeypatch.setattr(settings_crawler.time, "sleep", lambda _: None)
    phone = FakePhone()

    report = child_audit.probe_high_value_child_audit(
        phone,
        target_root_labels=("通用", "辅助功能"),
        max_depth=2,
        max_pages=8,
        max_child_scrolls_per_page=1,
        max_candidates_per_page=1,
    )

    assert report["status"] == "failed"
    assert report["target_roots_with_child"] == ["通用"]
    assert report["target_roots_missing_child"] == ["辅助功能"]
    assert report["metrics"]["target_roots_with_child_count"] == 1
    assert report["metrics"]["target_roots_missing_child_count"] == 1
    assert report["failure_categories"]["operation"] == [
        "ios-settings-child-audit-target-root-no-child-depth"
    ]


def test_high_value_child_audit_can_write_report(tmp_path):
    path = tmp_path / "child-audit.json"

    child_audit.write_report({"status": "passed"}, path)

    assert path.read_text(encoding="utf-8").startswith("{")


def test_high_value_child_audit_can_accept_safely_blocked_target_root():
    report = child_audit._build_report(
        target_root_labels=("无线局域网",),
        opened_targets=["无线局域网"],
        target_failures=[],
        return_root_failed=False,
        visits=[
            settings_reporting.PageVisit(
                path=("Settings", "无线局域网"),
                title="WLAN",
                texts=("WLAN", "My Networks", "Auto-Join"),
            )
        ],
        limits_hit=set(),
        blocked_pages=[
            settings_reporting.BlockedPage(
                path=("Settings", "无线局域网"),
                title="WLAN",
                reason="dynamic Wi-Fi rows",
                texts=("WLAN", "My Networks", "Auto-Join"),
            )
        ],
        rejected_candidates=[],
        navigation_failures=[],
        trace_payload=None,
        sample_limits_hit=[],
        config={},
        allow_blocked_target_roots=True,
    )

    assert report["status"] == "passed"
    assert report["target_roots_blocked"] == ["无线局域网"]
    assert report["target_roots_missing_child"] == []
    assert report["target_roots_without_child"] == ["无线局域网"]
    assert report["metrics"]["target_roots_blocked_count"] == 1


def test_high_value_child_audit_counts_noncanonical_target_root_coverage():
    report = child_audit._build_report(
        target_root_labels=("Camera",),
        opened_targets=["Camera"],
        target_failures=[],
        return_root_failed=False,
        visits=[
            settings_reporting.PageVisit(
                path=("Settings", "Camera"),
                title="Camera",
                texts=("Camera", "Formats", "Record Video"),
            ),
            settings_reporting.PageVisit(
                path=("Settings", "Camera", "Formats"),
                title="Formats",
                texts=("Formats", "High Efficiency", "Most Compatible"),
            ),
        ],
        limits_hit=set(),
        blocked_pages=[],
        rejected_candidates=[],
        navigation_failures=[],
        trace_payload=None,
        sample_limits_hit=[],
        config={},
    )

    assert report["status"] == "passed"
    assert report["metrics"]["root_expected_count"] == 1
    assert report["metrics"]["root_visited_count"] == 1
    assert report["metrics"]["root_required_missing_count"] == 0
    assert report["target_roots_with_child"] == ["Camera"]


def test_high_value_child_audit_can_accept_root_only_inventory_targets():
    report = child_audit._build_report(
        target_root_labels=("Wallpaper",),
        opened_targets=["Wallpaper"],
        target_failures=[],
        return_root_failed=False,
        visits=[
            settings_reporting.PageVisit(
                path=("Settings", "Wallpaper"),
                title="Wallpaper",
                texts=("Wallpaper", "Add New Wallpaper"),
            )
        ],
        limits_hit=set(),
        blocked_pages=[],
        rejected_candidates=[],
        navigation_failures=[],
        trace_payload=None,
        sample_limits_hit=[],
        config={},
        allow_root_only_target_roots=True,
    )

    assert report["status"] == "passed"
    assert report["target_roots_missing_child"] == []
    assert report["target_roots_without_child"] == ["Wallpaper"]
    assert report["known_issues"] == []
    assert report["metrics"]["target_roots_without_child_count"] == 1
    assert report["metrics"]["allow_root_only_target_roots"] is True


def test_root_only_single_target_can_start_from_already_open_page(monkeypatch):
    phone = FakePhone()
    visits: list[settings_reporting.PageVisit] = []

    monkeypatch.setattr(settings_crawler.time, "sleep", lambda _: None)
    monkeypatch.setattr(settings_crawler, "_open_settings_from_home_if_visible", lambda _phone: None)
    monkeypatch.setattr(settings_crawler, "_opened_requested_root", lambda _scene, label: label == "Wallpaper")

    def fail_return(_phone):
        raise AssertionError("root-only already-open target should not force root recovery")

    def record_current_page(
        _phone,
        *,
        path,
        visits,
        seen_sigs,
        depth,
        max_depth,
        limits_hit,
        blocked_pages,
        rejected_candidates,
        navigation_failures,
    ):
        visits.append(settings_reporting.PageVisit(
            path=path,
            title=path[-1],
            texts=(path[-1],),
        ))

    monkeypatch.setattr(settings_crawler, "_return_to_settings_root", fail_return)
    monkeypatch.setattr(settings_crawler, "_crawl_current_page", record_current_page)

    result = settings_crawler.crawl_high_value_child_settings(
        phone,
        target_root_labels=("Wallpaper",),
        max_depth=1,
        max_pages=4,
        max_child_scrolls_per_page=0,
        max_candidates_per_page=0,
        strict_child_candidate_audit=False,
        allow_root_only_target_roots=True,
    )

    assert result.opened_targets == ["Wallpaper"]
    assert [visit.path for visit in result.visits] == [("Settings", "Wallpaper")]
    assert result.return_root_failed is False
    assert visits == []


def test_child_audit_cli_writes_report_with_requested_roots(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    class Runtime:
        phone = object()

        def close(self, *, close_source: bool = False):
            captured["closed"] = close_source

    def fake_probe(phone, **kwargs):
        captured["phone"] = phone
        captured.update(kwargs)
        return {
            "status": "passed",
            "target_root_labels": list(kwargs["target_root_labels"]),
            "metrics": {},
        }

    monkeypatch.setattr(child_audit, "make_source", lambda *, cfg: object())
    monkeypatch.setattr(child_audit, "build_phone", lambda *, source, cfg: Runtime())
    monkeypatch.setattr(child_audit, "probe_high_value_child_audit", fake_probe)

    report_path = tmp_path / "child-audit.json"
    rc = child_audit.main([
        "--report", str(report_path),
        "--target-root", "Apple Pencil",
        "--max-depth", "1",
        "--max-pages", "5",
        "--max-child-scrolls-per-page", "0",
        "--max-candidates-per-page", "0",
        "--startup-settle-s", "0",
        "--allow-root-only-target-roots",
        "--assume-settings-open",
        "--language", "en",
        "--region", "HK",
        "--phone-model", "ipad_mini_7",
        "--platform", "ipados",
    ])

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert rc == 0
    assert payload["target_root_labels"] == ["Apple Pencil"]
    assert captured["target_root_labels"] == ("Apple Pencil",)
    assert captured["max_depth"] == 1
    assert captured["max_pages"] == 5
    assert captured["max_child_scrolls_per_page"] == 0
    assert captured["max_candidates_per_page"] == 0
    assert captured["allow_root_only_target_roots"] is True
    assert captured["assume_settings_open"] is True
    assert captured["closed"] is True
