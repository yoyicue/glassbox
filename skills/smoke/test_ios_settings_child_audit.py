from __future__ import annotations

from glassbox.cognition import Box, Scene, UIElement
from skills.regression.ios_settings import child_audit
from skills.regression.ios_settings import crawler as settings_crawler


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


class FakePhone:
    def __init__(self):
        self.stack = ["root"]
        self.actions: list[tuple[str, object]] = []

    def _viewport_size(self):
        return 448, 973

    def perceive(self):
        return {
            "root": ROOT,
            "general": GENERAL,
            "about": ABOUT,
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


def test_high_value_child_audit_can_write_report(tmp_path):
    path = tmp_path / "child-audit.json"

    child_audit.write_report({"status": "passed"}, path)

    assert path.read_text(encoding="utf-8").startswith("{")
