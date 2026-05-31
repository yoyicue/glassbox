from __future__ import annotations

import json

import pytest

from glassbox.memory.schema import UTG, ScreenEdge, ScreenNode, ScreenSignature
from skills.regression.ios_settings.state_machine_acceptance import (
    main as acceptance_main,
)
from skills.regression.ios_settings.state_machine_acceptance import (
    validate_state_machine_acceptance,
)


def _report(**root_coverage_overrides):
    root_coverage = {
        "expected": ["蓝牙", "通知"],
        "visited": ["蓝牙"],
        "missing": ["通知"],
        "entered_graph": ["蓝牙"],
        "required_missing": [],
    }
    root_coverage.update(root_coverage_overrides)
    return {
        "config": {"memory_dir": ""},
        "root_coverage": root_coverage,
    }


def _utg(*, fragmented_root: bool = False, include_root_edge: bool = True) -> UTG:
    root = ScreenNode(
        screen_id="scr_root",
        page_id="settings/root",
        platform_scene_kind="settings_root",
        signature=ScreenSignature(
            stable_texts=["settings", "bluetooth", "notifications"],
            type_histogram={"settings_root": 1},
        ),
    )
    detail = ScreenNode(
        screen_id="scr_bluetooth",
        page_id="settings/Bluetooth",
        platform_scene_kind="settings_detail",
        signature=ScreenSignature(
            stable_texts=["settings/bluetooth"],
            type_histogram={"settings_detail": 1},
        ),
    )
    nodes = {root.screen_id: root, detail.screen_id: detail}
    if fragmented_root:
        nodes["scr_root_2"] = root.model_copy(
            update={
                "screen_id": "scr_root_2",
                "signature": ScreenSignature(
                    stable_texts=["settings", "general"],
                    type_histogram={"settings_root": 1},
                ),
            },
            deep=True,
        )
    edges = []
    if include_root_edge:
        edges.append(ScreenEdge(
            from_id=root.screen_id,
            to_id=detail.screen_id,
            action_op="tap",
            policy_action="tap_root_row",
            success_count=1,
            count=1,
            success_rate=1.0,
        ))
    edges.append(ScreenEdge(
        from_id=detail.screen_id,
        to_id=root.screen_id,
        action_op="back",
        policy_action="back",
        success_count=1,
        count=1,
        success_rate=1.0,
    ))
    return UTG(bundle_id="com.apple.Preferences", nodes=nodes, edges=edges)


@pytest.mark.smoke
def test_state_machine_acceptance_passes_for_projected_root_graph():
    result = validate_state_machine_acceptance(
        _report(sidebar_absent=["通知"], sidebar_exhaustive=["true"]),
        _utg(),
        min_detail_to_root_edges=1,
        require_sidebar_exhaustive=True,
    )

    assert result.errors == []
    assert result.metrics["root_node_count"] == 1
    assert result.metrics["root_to_detail_success_edge_count"] == 1
    assert result.metrics["detail_to_root_return_success_edge_count"] == 1
    assert result.metrics["sidebar_exhaustive"] is True


@pytest.mark.smoke
def test_state_machine_acceptance_rejects_fragmented_root_and_missing_edges():
    result = validate_state_machine_acceptance(
        _report(entered_graph=[]),
        _utg(fragmented_root=True, include_root_edge=False),
        max_root_signatures=1,
        min_entered_graph=1,
    )

    assert any("fragmented" in error for error in result.errors)
    assert any("root→detail success edges below threshold" in error for error in result.errors)
    assert any("entered_graph below threshold" in error for error in result.errors)


@pytest.mark.smoke
def test_state_machine_acceptance_rejects_sidebar_absent_without_exhaustive_evidence():
    result = validate_state_machine_acceptance(
        _report(sidebar_absent=["通知"]),
        _utg(),
    )

    assert result.errors == ["sidebar_absent requires sidebar_exhaustive evidence"]


@pytest.mark.smoke
def test_state_machine_acceptance_cli_reads_report_and_utg(tmp_path, capsys):
    report_path = tmp_path / "report.json"
    utg_path = tmp_path / "com.apple.Preferences.json"
    report_path.write_text(
        json.dumps(_report(sidebar_absent=["通知"], sidebar_exhaustive=["true"]), ensure_ascii=False),
        encoding="utf-8",
    )
    utg_path.write_text(
        json.dumps(_utg().model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )

    code = acceptance_main([
        str(report_path),
        "--utg", str(utg_path),
        "--require-sidebar-exhaustive",
    ])

    assert code == 0
    assert "OK" in capsys.readouterr().out
