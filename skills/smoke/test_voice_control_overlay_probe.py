from __future__ import annotations

import json

import pytest

from skills.regression import voice_control_overlay_probe as probe
from skills.regression.voice_control_overlay_probe import analyze_probe_result, main


def _capture(
    label: str,
    *,
    selected: int,
    mapped: list[tuple[str, str]] | None = None,
    visible_texts: list[str] | None = None,
) -> dict[str, object]:
    mapped = mapped or []
    visible_texts = visible_texts or []
    return {
        "label": label,
        "page_id": "settings/Overlay",
        "ocr_count": 10,
        "visible_texts": visible_texts,
        "mode_counts": {
            "item_numbers": selected,
            "item_names": 0,
            "numbered_grid": selected,
        },
        "overlay_hint_mapping": {
            "scene_marker_count": selected,
            "mapped": [
                {"text": text, "accessibility_id": accessibility_id}
                for text, accessibility_id in mapped
            ],
        },
    }


@pytest.mark.smoke
def test_analyze_probe_result_summarizes_marker_counts_and_scroll_id_changes():
    result = {
        "overlay_mode": "item_numbers",
        "steps": [
            {"action": "tap_item_numbers_initial", "outcome": {"ok": True, "transport_ok": True}},
            {"capture": _capture("01_item_numbers_initial", selected=10)},
            {"action": "tap_none", "outcome": {"ok": True, "transport_ok": True}},
            {"capture": _capture("02_overlay_none_off", selected=0)},
            {"action": "tap_item_numbers", "outcome": {"ok": True, "transport_ok": True}},
            {
                "capture": _capture(
                    "03_item_numbers_restored",
                    selected=11,
                    mapped=[
                        ("Siri", "vc:item_number:22"),
                        ("Wallpaper", "vc:item_number:23"),
                    ],
                )
            },
            {
                "capture": _capture(
                    "04_item_numbers_after_scroll",
                    selected=11,
                    mapped=[
                        ("Siri", "vc:item_number:13"),
                        ("Wallpaper", "vc:item_number:23"),
                    ],
                )
            },
        ],
    }

    analysis = analyze_probe_result(result)

    assert analysis["overlay_mode"] == "item_numbers"
    assert analysis["preflight_ok"] is None
    assert analysis["preflight_page_id"] is None
    assert analysis["action_count"] == 3
    assert analysis["preflight_stopped_before_actions"] is False
    assert analysis["actions_transport_ok"] is True
    assert analysis["overlay_off_selected_count"] == 0
    assert analysis["overlay_off_all_zero"] is True
    assert analysis["restored_selected_count"] == 11
    assert analysis["mapping_common_count"] == 2
    assert analysis["mapping_stable_count"] == 1
    assert analysis["mapping_changed"] == [
        {
            "text": "Siri",
            "before": "vc:item_number:22",
            "after": "vc:item_number:13",
        }
    ]


@pytest.mark.smoke
def test_analyze_probe_result_reports_nonzero_other_mode_counts():
    result = {
        "overlay_mode": "item_names",
        "steps": [
            {
                "capture": {
                    "label": "01_item_names_initial",
                    "page_id": "settings/Overlay",
                    "ocr_count": 10,
                    "mode_counts": {
                        "item_numbers": 0,
                        "item_names": 27,
                        "numbered_grid": 2,
                    },
                    "overlay_hint_mapping": {"scene_marker_count": 27, "mapped": []},
                }
            }
        ],
    }

    analysis = analyze_probe_result(result)

    assert analysis["captures"][0]["selected_mode_count"] == 27
    assert analysis["captures"][0]["other_mode_counts"] == {"numbered_grid": 2}


@pytest.mark.smoke
def test_analyze_probe_result_reports_wheel_visible_text_delta():
    result = {
        "overlay_mode": "item_numbers",
        "steps": [
            {"capture": _capture("03_item_numbers_restored", selected=10, visible_texts=["Siri", "Wallpaper"])},
            {"action": "wheel_scroll_probe", "outcome": {"ok": True, "transport_ok": True}},
            {"capture": _capture("04_item_numbers_after_wheel", selected=8, visible_texts=["Wallpaper", "Apps"])},
        ],
    }

    analysis = analyze_probe_result(result)

    assert analysis["actions_transport_ok"] is True
    assert analysis["wheel_visible_text_changed"] is True
    assert analysis["wheel_texts_added"] == ["Apps"]
    assert analysis["wheel_texts_removed"] == ["Siri"]
    assert analysis["wheel_semantic_text_changed"] is True
    assert analysis["wheel_semantic_texts_added"] == ["Apps"]
    assert analysis["wheel_semantic_texts_removed"] == ["Siri"]
    assert analysis["wheel_frame_diff"] is None
    assert analysis["wheel_scroll_evidence"] == "small_frame_change_with_semantic_or_ocr_delta"


@pytest.mark.smoke
def test_analyze_probe_result_reports_wheel_page_change():
    result = {
        "overlay_mode": "item_numbers",
        "steps": [
            {"capture": _capture("03_item_numbers_restored", selected=10)},
            {"action": "wheel_scroll_probe", "outcome": {"ok": True, "transport_ok": True}},
            {
                "capture": {
                    **_capture(
                        "04_item_numbers_after_wheel",
                        selected=8,
                        visible_texts=["Notifications"],
                    ),
                    "page_id": "settings/Notifications",
                }
            },
        ],
    }

    analysis = analyze_probe_result(result)

    assert analysis["wheel_scroll_evidence"] == "page_changed_after_focus_or_wheel"


@pytest.mark.smoke
def test_analyze_probe_result_reports_second_wheel_pass():
    result = {
        "overlay_mode": "item_numbers",
        "wheel_second_ticks": -90,
        "steps": [
            {"capture": _capture("03_item_numbers_restored", selected=10, visible_texts=["Siri"])},
            {"action": "wheel_scroll_probe", "outcome": {"ok": True, "transport_ok": True}},
            {"capture": _capture("04_item_numbers_after_wheel", selected=10, visible_texts=["Siri"])},
            {"action": "wheel_second_scroll_probe", "outcome": {"ok": True, "transport_ok": True}},
            {
                "capture": _capture(
                    "05_item_numbers_after_wheel_second",
                    selected=8,
                    visible_texts=["Wallpaper", "Apps"],
                )
            },
        ],
    }

    analysis = analyze_probe_result(result)

    assert analysis["wheel_second_ticks"] == -90
    assert analysis["wheel_scroll_evidence"] == "no_visible_change"
    assert analysis["wheel_second_visible_text_changed"] is True
    assert analysis["wheel_second_semantic_text_changed"] is True
    assert analysis["wheel_second_scroll_evidence"] == "small_frame_change_with_semantic_or_ocr_delta"


@pytest.mark.smoke
def test_analyze_probe_result_reports_keyboard_text_visibility():
    result = {
        "overlay_mode": "item_numbers",
        "keyboard_text": "gbvckbd",
        "steps": [
            {"capture": _capture("03_item_numbers_restored", selected=10)},
            {"action": "type_keyboard_text", "outcome": {"ok": True, "transport_ok": True}},
            {
                "capture": _capture(
                    "05_item_numbers_after_keyboard_type",
                    selected=3,
                    visible_texts=["Search", "gbvckbd", "No Results"],
                )
            },
        ],
    }

    analysis = analyze_probe_result(result)

    assert analysis["keyboard_text"] == "gbvckbd"
    assert analysis["keyboard_text_visible"] is True
    assert analysis["keyboard_capture_page_id"] == "settings/Overlay"


@pytest.mark.smoke
def test_analyze_probe_result_reports_keyboard_focus_and_return_status():
    result = {
        "overlay_mode": "item_numbers",
        "keyboard_text": "gbvccmdf",
        "keyboard_focus_method": "cmd_f",
        "keyboard_clear_before_type": True,
        "keyboard_press_return": True,
        "steps": [
            {"capture": _capture("03_item_numbers_restored", selected=10, visible_texts=["Overlay"])},
            {"action": "keyboard_focus_cmd_f", "outcome": {"ok": True, "transport_ok": True}},
            {
                "capture": _capture(
                    "04_item_numbers_keyboard_focus",
                    selected=4,
                    visible_texts=["Overlay", "Search", "Cancel"],
                )
            },
            {"action": "type_keyboard_text", "outcome": {"ok": True, "transport_ok": True}},
            {
                "capture": _capture(
                    "05_item_numbers_after_keyboard_type",
                    selected=4,
                    visible_texts=["Search", "gbvccmdf"],
                )
            },
            {"action": "keyboard_return_after_type", "outcome": {"ok": True, "transport_ok": True}},
            {
                "capture": _capture(
                    "06_item_numbers_after_keyboard_return",
                    selected=4,
                    visible_texts=["Search", "gbvccmdf", "No Results"],
                )
            },
        ],
    }

    analysis = analyze_probe_result(result)

    assert analysis["keyboard_focus_method"] == "cmd_f"
    assert analysis["keyboard_clear_before_type"] is True
    assert analysis["keyboard_press_return"] is True
    assert analysis["keyboard_focus_visible_text_changed"] is True
    assert analysis["keyboard_focus_texts_added"] == ["Cancel", "Search"]
    assert analysis["keyboard_focus_page_changed"] is False
    assert analysis["keyboard_text_visible"] is True
    assert analysis["keyboard_text_visible_after_return"] is True
    assert analysis["keyboard_return_capture_page_id"] == "settings/Overlay"


@pytest.mark.smoke
def test_analyze_probe_result_reports_keyboard_overlay_off_control():
    result = {
        "overlay_mode": "item_numbers",
        "keyboard_text": "gbvcoff",
        "keyboard_focus_method": "double_tap",
        "keyboard_disable_overlay_before_focus": True,
        "keyboard_switch_input_before_type": True,
        "steps": [
            {"capture": _capture("03_item_numbers_restored", selected=10, visible_texts=["Overlay"])},
            {"action": "keyboard_disable_overlay_before_focus", "outcome": {"ok": True, "transport_ok": True}},
            {"capture": _capture("04_item_numbers_keyboard_overlay_off", selected=0, visible_texts=["Overlay"])},
            {"action": "double_tap_keyboard_field_first", "outcome": {"ok": True, "transport_ok": True}},
            {"action": "double_tap_keyboard_field_second", "outcome": {"ok": True, "transport_ok": True}},
            {
                "capture": _capture(
                    "04_item_numbers_keyboard_focus",
                    selected=0,
                    visible_texts=["Overlay", "Search"],
                )
            },
            {"action": "keyboard_switch_input_before_type", "outcome": {"ok": True, "transport_ok": True}},
            {
                "capture": _capture(
                    "05_item_numbers_after_keyboard_input_switch",
                    selected=0,
                    visible_texts=["Search", "Input Sources"],
                )
            },
            {"action": "type_keyboard_text", "outcome": {"ok": True, "transport_ok": True}},
            {
                "capture": _capture(
                    "05_item_numbers_after_keyboard_type",
                    selected=0,
                    visible_texts=["Search", "gbvcoff"],
                )
            },
        ],
    }

    analysis = analyze_probe_result(result)

    assert analysis["keyboard_focus_method"] == "double_tap"
    assert analysis["keyboard_disable_overlay_before_focus"] is True
    assert analysis["keyboard_switch_input_before_type"] is True
    assert analysis["keyboard_overlay_off_selected_count"] == 0
    assert analysis["keyboard_overlay_off_all_zero"] is True
    assert analysis["keyboard_overlay_off_page_id"] == "settings/Overlay"
    assert analysis["keyboard_input_switch_capture_page_id"] == "settings/Overlay"
    assert analysis["keyboard_input_switch_visible_text_changed"] is True
    assert analysis["keyboard_input_switch_texts_added"] == ["Input Sources"]
    assert analysis["keyboard_text_visible"] is True


@pytest.mark.smoke
def test_probe_cli_requires_explicit_unsafe_input_switch_confirmation(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--keyboard-probe", "--keyboard-switch-input-before-type"])

    assert exc.value.code == 2
    stderr = capsys.readouterr().err
    assert "--allow-unsafe-keyboard-input-switch" in stderr


@pytest.mark.smoke
def test_probe_cli_preflight_only_stops_before_actions(monkeypatch, tmp_path):
    seen: dict[str, object] = {}

    def fake_run_probe(**kwargs):
        seen.update(kwargs)
        return {
            "run_dir": str(tmp_path / "run"),
            "overlay_mode": kwargs["overlay_mode"],
            "preflight_only": kwargs["preflight_only"],
            "preflight_ok": True,
            "preflight_page_id": "settings/Overlay",
            "steps": [
                {
                    "capture": _capture(
                        "00_preflight",
                        selected=7,
                        visible_texts=["Overlay", "Item Numbers"],
                    )
                }
            ],
        }

    monkeypatch.setattr(probe, "run_probe", fake_run_probe)
    monkeypatch.setattr(probe, "_print_summary", lambda _result, _json_path: None)

    code = main(["--output-dir", str(tmp_path), "--preflight-only"])

    data = json.loads((tmp_path / "voice_control_overlay_ab.json").read_text())
    assert code == 0
    assert seen["preflight_only"] is True
    assert data["preflight_only"] is True
    assert data["analysis"]["preflight_only"] is True
    assert data["analysis"]["preflight_ready_for_probe"] is True
    assert data["analysis"]["preflight_blocker"] is None
    assert data["analysis"]["action_count"] == 0
    assert data["analysis"]["preflight_stopped_before_actions"] is True
    assert [step for step in data["steps"] if "action" in step] == []


@pytest.mark.smoke
def test_probe_cli_preflight_only_returns_2_when_not_ready(monkeypatch, tmp_path):
    def fake_run_probe(**kwargs):
        return {
            "run_dir": str(tmp_path / "run"),
            "overlay_mode": kwargs["overlay_mode"],
            "preflight_only": kwargs["preflight_only"],
            "preflight_ok": False,
            "preflight_page_id": None,
            "preflight_fka_help_overlay": True,
            "preflight_error": (
                "voice_control_overlay_probe requires the device to start on "
                "settings/Overlay; got Full Keyboard Access help overlay. Clear the "
                "FKA help overlay before running on-rig probes."
            ),
            "steps": [
                {
                    "capture": {
                        **_capture(
                            "00_preflight",
                            selected=0,
                            visible_texts=[
                                "Basic",
                                "Help",
                                "Move forwards",
                                "Move backwards",
                                "Movement",
                                "Interaction",
                                "Device",
                                "Home",
                            ],
                        ),
                        "page_id": None,
                    }
                }
            ],
        }

    monkeypatch.setattr(probe, "run_probe", fake_run_probe)
    monkeypatch.setattr(probe, "_print_summary", lambda _result, _json_path: None)

    code = main(["--output-dir", str(tmp_path), "--preflight-only"])

    data = json.loads((tmp_path / "voice_control_overlay_ab.json").read_text())
    assert code == 2
    assert data["preflight_only"] is True
    assert data["analysis"]["preflight_fka_help_overlay"] is True
    assert data["analysis"]["preflight_ready_for_probe"] is False
    assert data["analysis"]["preflight_blocker"] == "fka_help_overlay"
    assert data["analysis"]["action_count"] == 0
    assert data["analysis"]["preflight_stopped_before_actions"] is True
    assert data["analysis"]["fka_help_overlay_capture_labels"] == ["00_preflight"]
    assert [step for step in data["steps"] if "action" in step] == []


@pytest.mark.smoke
def test_probe_cli_fka_hard_stop_cannot_be_bypassed_by_no_require(
    monkeypatch,
    tmp_path,
):
    seen: dict[str, object] = {}

    def fake_run_probe(**kwargs):
        seen.update(kwargs)
        return {
            "run_dir": str(tmp_path / "run"),
            "overlay_mode": kwargs["overlay_mode"],
            "preflight_only": kwargs["preflight_only"],
            "preflight_ok": False,
            "preflight_page_id": None,
            "preflight_fka_help_overlay": True,
            "preflight_error": (
                "voice_control_overlay_probe requires the device to start on "
                "settings/Overlay; got Full Keyboard Access help overlay. Clear the "
                "FKA help overlay before running on-rig probes."
            ),
            "steps": [
                {
                    "capture": {
                        **_capture(
                            "00_preflight",
                            selected=0,
                            visible_texts=[
                                "Basic",
                                "Help",
                                "Move forwards",
                                "Move backwards",
                                "Movement",
                                "Interaction",
                                "Device",
                                "Home",
                            ],
                        ),
                        "page_id": None,
                    }
                }
            ],
        }

    monkeypatch.setattr(probe, "run_probe", fake_run_probe)
    monkeypatch.setattr(probe, "_print_summary", lambda _result, _json_path: None)

    code = main(["--output-dir", str(tmp_path), "--no-require-overlay-page"])

    data = json.loads((tmp_path / "voice_control_overlay_ab.json").read_text())
    assert code == 2
    assert seen["require_overlay_page"] is False
    assert seen["preflight_only"] is False
    assert data["analysis"]["preflight_fka_help_overlay"] is True
    assert data["analysis"]["preflight_ready_for_probe"] is False
    assert data["analysis"]["preflight_blocker"] == "fka_help_overlay"
    assert data["analysis"]["action_count"] == 0
    assert data["analysis"]["preflight_stopped_before_actions"] is True
    assert [step for step in data["steps"] if "action" in step] == []


@pytest.mark.smoke
def test_fka_preflight_hard_stop_cannot_be_bypassed():
    assert probe._should_stop_after_preflight(
        preflight_ok=False,
        preflight_fka_help_overlay=True,
        require_overlay_page=False,
        preflight_only=False,
    )
    assert not probe._should_stop_after_preflight(
        preflight_ok=False,
        preflight_fka_help_overlay=False,
        require_overlay_page=False,
        preflight_only=False,
    )
    assert probe._should_stop_after_preflight(
        preflight_ok=True,
        preflight_fka_help_overlay=False,
        require_overlay_page=True,
        preflight_only=True,
    )


@pytest.mark.smoke
def test_analyze_probe_result_reports_fka_help_overlay_trap():
    result = {
        "overlay_mode": "item_numbers",
        "keyboard_switch_input_before_type": True,
        "steps": [
            {"capture": _capture("03_item_numbers_restored", selected=10, visible_texts=["Overlay"])},
            {
                "capture": {
                    **_capture(
                        "05_item_numbers_after_keyboard_input_switch",
                        selected=0,
                        visible_texts=[
                            "Basic",
                            "Help",
                            "Move forwards",
                            "Move backwards",
                            "Movement",
                            "Interaction",
                            "Device",
                            "Home",
                        ],
                    ),
                    "page_id": None,
                }
            },
        ],
    }

    analysis = analyze_probe_result(result)

    assert analysis["fka_help_overlay_detected"] is True
    assert analysis["fka_help_overlay_capture_labels"] == [
        "05_item_numbers_after_keyboard_input_switch"
    ]
    assert analysis["captures"][1]["fka_help_overlay"] is True
    assert analysis["keyboard_input_switch_opened_fka_help"] is True


@pytest.mark.smoke
def test_analyze_probe_result_carries_preflight_status():
    result = {
        "overlay_mode": "item_numbers",
        "preflight_only": True,
        "preflight_ok": False,
        "preflight_page_id": "notes_list",
        "preflight_error": "voice_control_overlay_probe requires the device to start on settings/Overlay; got 'notes_list'",
        "steps": [
            {"capture": _capture("00_preflight", selected=0)},
        ],
    }

    analysis = analyze_probe_result(result)

    assert analysis["preflight_ok"] is False
    assert analysis["preflight_only"] is True
    assert analysis["preflight_page_id"] == "notes_list"
    assert analysis["preflight_error"].endswith("got 'notes_list'")
    assert analysis["preflight_fka_help_overlay"] is False
    assert analysis["preflight_ready_for_probe"] is False
    assert analysis["preflight_blocker"] == "wrong_page:'notes_list'"


@pytest.mark.smoke
def test_analyze_probe_result_reports_fka_help_preflight():
    result = {
        "overlay_mode": "item_numbers",
        "preflight_ok": False,
        "preflight_page_id": None,
        "preflight_error": (
            "voice_control_overlay_probe requires the device to start on "
            "settings/Overlay; got Full Keyboard Access help overlay. Clear the "
            "FKA help overlay before running on-rig probes."
        ),
        "steps": [
            {
                "capture": _capture(
                    "00_preflight",
                    selected=0,
                    visible_texts=[
                        "Basic",
                        "Help",
                        "Move forwards",
                        "Move backwards",
                        "Movement",
                        "Interaction",
                        "Device",
                        "Home",
                    ],
                )
            },
        ],
    }

    analysis = analyze_probe_result(result)

    assert analysis["preflight_ok"] is False
    assert analysis["preflight_fka_help_overlay"] is True
    assert analysis["preflight_ready_for_probe"] is False
    assert analysis["preflight_blocker"] == "fka_help_overlay"
    assert analysis["fka_help_overlay_detected"] is True
    assert analysis["fka_help_overlay_capture_labels"] == ["00_preflight"]
    assert "Full Keyboard Access help overlay" in analysis["preflight_error"]
