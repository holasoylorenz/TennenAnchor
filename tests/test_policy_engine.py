"""
Unit tests for policies/policy_engine.py and Behavior Tree nodes.
Verifies Selector fallback routing, dynamic branch re-weighting, Condition checks,
and JSON policy loading and persistence.
"""

import json
from pathlib import Path
import pytest

from policies.nodes import (
    ActionNode,
    BehaviorNode,
    ConditionNode,
    ExecutionContext,
    NodeStatus,
    SelectorNode,
    SequenceNode,
)
from policies.engine import PolicyEngine


class MockController:
    """Mock desktop controller for unit tests without hardware side-effects."""
    def __init__(self):
        self.history = []

    def hotkey(self, keys, target_hwnd=None):
        self.history.append(("hotkey", keys))

    def type_text(self, text, target_hwnd=None):
        self.history.append(("type", text))

    def press_key(self, key, target_hwnd=None):
        self.history.append(("press_key", key))

    def click(self, x, y, target_hwnd=None):
        self.history.append(("click", (x, y)))

    def get_foreground_hwnd(self):
        return 12345


class MockParser:
    """Mock screen parser for unit tests."""
    def parse_active_window(self, query=None):
        return {
            "status": "ok",
            "window": "Google Chrome - New Tab",
            "elements": [
                {"id": 1, "type": "TabItem", "name": "Tab 1"},
                {"id": 2, "type": "TabItem", "name": "Tab 2"},
            ],
        }


def test_condition_node_in_range():
    cond = ConditionNode(
        node_id="test_cond",
        predicate={"type": "in_range", "var": "index", "min": 1, "max": 8},
    )
    ctx_pass = ExecutionContext(params={"index": 3}, controller=MockController(), parser=MockParser())
    assert cond.tick(ctx_pass) == NodeStatus.SUCCESS

    ctx_fail = ExecutionContext(params={"index": 9}, controller=MockController(), parser=MockParser())
    assert cond.tick(ctx_fail) == NodeStatus.FAILURE


def test_sequence_node_execution():
    mock_ctrl = MockController()
    ctx = ExecutionContext(params={"index": 2}, controller=mock_ctrl, parser=MockParser())

    seq = SequenceNode(node_id="seq_test")
    seq.add_child(ConditionNode("c1", {"type": "in_range", "var": "index", "min": 1, "max": 5}))
    seq.add_child(ActionNode("a1", {"type": "hotkey", "keys": ["ctrl", "{index}"]}))

    status = seq.tick(ctx)
    assert status == NodeStatus.SUCCESS
    assert ("hotkey", ["ctrl", "2"]) in mock_ctrl.history


def test_selector_fallback_and_dynamic_reweighting():
    mock_ctrl = MockController()
    ctx = ExecutionContext(params={"index": 9}, controller=mock_ctrl, parser=MockParser())

    sel = SelectorNode(node_id="sel_test")

    # Branch 1: Fails condition (index in 1..8)
    branch1 = SequenceNode("branch_1", weight=1.0)
    branch1.add_child(ConditionNode("c1", {"type": "in_range", "var": "index", "min": 1, "max": 8}))
    branch1.add_child(ActionNode("a1", {"type": "hotkey", "keys": ["ctrl", "1"]}))

    # Branch 2: Succeeds condition (index == 9)
    branch2 = SequenceNode("branch_2", weight=0.8)
    branch2.add_child(ConditionNode("c2", {"type": "equals", "var": "index", "value": 9}))
    branch2.add_child(ActionNode("a2", {"type": "hotkey", "keys": ["ctrl", "9"]}))

    sel.add_child(branch1)
    sel.add_child(branch2)

    status = sel.tick(ctx)
    assert status == NodeStatus.SUCCESS
    assert ("hotkey", ["ctrl", "9"]) in mock_ctrl.history

    # Verify branch 2 weight was rewarded
    assert branch2.weight > 0.8
    # Verify branch 1 weight was penalized
    assert branch1.weight < 1.0


def test_behavior_tree_serialization():
    sel = SelectorNode(node_id="sel_root", weight=2.0)
    seq = SequenceNode(node_id="seq_child")
    seq.add_child(ConditionNode("cond", {"type": "equals", "var": "mode", "value": "fast"}))
    sel.add_child(seq)

    data = sel.to_dict()
    assert data["type"] == "selector"
    assert len(data["children"]) == 1
    assert data["children"][0]["type"] == "sequence"

    rebuilt = BehaviorNode.from_dict(data)
    assert isinstance(rebuilt, SelectorNode)
    assert len(rebuilt.children) == 1
    assert isinstance(rebuilt.children[0], SequenceNode)


def test_policy_engine_load_and_execute(tmp_path):
    policies_dir = tmp_path / "policies"
    policies_dir.mkdir()

    policy_payload = {
        "policy_id": "test_policy",
        "domain": "test",
        "tree": {
            "type": "selector",
            "id": "root",
            "children": [
                {
                    "type": "sequence",
                    "id": "seq_main",
                    "children": [
                        {
                            "type": "condition",
                            "id": "cond_check",
                            "predicate": {"type": "in_range", "var": "val", "min": 0, "max": 10},
                        },
                        {
                            "type": "action",
                            "id": "act_test",
                            "action": {"type": "wait", "wait_ms": 10},
                        },
                    ],
                }
            ],
        },
    }

    test_file = policies_dir / "test_policy.json"
    test_file.write_text(json.dumps(policy_payload), encoding="utf-8")

    engine = PolicyEngine(policies_dir=policies_dir)
    res = engine.execute("test_policy", params={"val": 5})
    assert res["status"] == "ok"
    assert res["policy_id"] == "test_policy"

    # Test failure case
    res_fail = engine.execute("test_policy", params={"val": 99})
    assert res_fail["status"] == "error"
