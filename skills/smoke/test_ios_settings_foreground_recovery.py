from __future__ import annotations

from glassbox.cognition import Box, Scene, UIElement
from skills.regression.ios_settings import foreground_recovery


def _el(text: str, x: int, y: int, w: int = 60, h: int = 20) -> UIElement:
    return UIElement(type="text", box=Box(x=x, y=y, w=w, h=h), text=text, confidence=0.9)


def _scene(*elements: UIElement) -> Scene:
    return Scene(frame_id=0, timestamp=0.0, elements=list(elements))


HOME_1 = _scene(
    _el("文件", 42, 176),
    _el("预览", 154, 176),
    _el("DemoApp", 252, 176, w=82),
    _el("搜索", 196, 892, w=48),
)
HOME_2 = _scene(
    _el("邮件", 42, 176),
    _el("日历", 154, 176),
    _el("地图", 252, 176),
    _el("搜索", 196, 892, w=48),
)
APP_LIBRARY = _scene(
    _el("Q App资源库", 88, 112, w=140),
    _el("AI办公", 92, 198),
    _el("App Store", 94, 272, w=82),
    _el("GlassboxHelper", 94, 790, w=78),
)
SETTINGS_ROOT = _scene(
    _el("设置", 196, 72, w=48),
    _el("无线局域网", 54, 218, w=88),
    _el("蓝牙", 54, 272, w=42),
    _el("通用", 54, 326, w=42),
)


class FakePhone:
    def __init__(self, pages: list[Scene]):
        self.pages = pages
        self.index = 0
        self.opened = False
        self.actions: list[str] = []

    def viewport_size(self):

        return self._viewport_size()

    def _viewport_size(self):
        return 448, 973

    def perceive(self):
        if self.opened:
            return SETTINGS_ROOT
        return self.pages[self.index]

    def invalidate_perceive_cache(self):
        pass

    def home(self):
        self.actions.append("home")
        self.index = 0

    def swipe_left(self, *args, **kwargs):
        self.actions.append("swipe_left")
        self.index = min(self.index + 1, len(self.pages) - 1)


def test_app_library_foreground_probe_records_success(monkeypatch):
    monkeypatch.setattr(foreground_recovery.time, "sleep", lambda _: None)

    def fake_open(phone, labels, *, max_pages: int = 8, settle_s: float = 0.8):
        phone.actions.append("open_settings")
        phone.opened = True
        return True

    monkeypatch.setattr(foreground_recovery, "open_app_from_springboard", fake_open)
    phone = FakePhone([HOME_1, HOME_2, APP_LIBRARY])

    report = foreground_recovery.probe_app_library_recovery(
        phone,
        settle_s=0.0,
        swipe_y_fractions=(0.74,),
    )

    assert report["status"] == "passed"
    assert report["app_library_reached"] is True
    assert report["settings_opened"] is True
    assert report["metrics"]["final_scene_type"] == "settings_root"
    assert all(not values for values in report["failure_categories"].values())
    assert phone.actions == ["home", "swipe_left", "swipe_left", "open_settings"]


def test_app_library_foreground_probe_reports_unreachable(monkeypatch):
    monkeypatch.setattr(foreground_recovery.time, "sleep", lambda _: None)
    phone = FakePhone([HOME_1])

    report = foreground_recovery.probe_app_library_recovery(
        phone,
        max_swipes=3,
        settle_s=0.0,
        swipe_y_fractions=(0.74,),
    )

    assert report["status"] == "failed"
    assert report["failure_reason"] == "app_library_unreachable"
    assert report["app_library_reached"] is False
    assert report["settings_opened"] is False
    assert report["failure_categories"]["recovery"] == ["ios-foreground-app-library-unreachable"]
    assert phone.actions == ["home", "swipe_left", "swipe_left"]


def test_app_library_foreground_probe_reports_settings_open_failure(monkeypatch):
    monkeypatch.setattr(foreground_recovery.time, "sleep", lambda _: None)
    monkeypatch.setattr(foreground_recovery, "open_app_from_springboard", lambda *args, **kwargs: False)
    phone = FakePhone([APP_LIBRARY])

    report = foreground_recovery.probe_app_library_recovery(
        phone,
        settle_s=0.0,
        swipe_y_fractions=(0.74,),
    )

    assert report["status"] == "failed"
    assert report["failure_reason"] == "settings_not_opened_from_app_library_start"
    assert report["app_library_reached"] is True
    assert report["settings_opened"] is False


def test_app_library_foreground_probe_can_write_report(tmp_path):
    report = {"status": "failed", "failure_reason": "app_library_unreachable"}
    path = tmp_path / "foreground.json"

    foreground_recovery.write_report(report, path)

    assert path.read_text(encoding="utf-8").startswith("{")
