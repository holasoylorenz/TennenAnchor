"""
Abstract Behavior Tree Nodes for Desktop Automation Policies.

Implements the formal Behavior Tree specification for robust OS-level interaction:
- NodeStatus: SUCCESS, FAILURE, RUNNING
- Composite Nodes: Selector (Fallback with dynamic branch re-weighting), Sequence
- Leaf Nodes: ConditionNode (Predicates), ActionNode (Actuation primitives), VerifyNode (Post-condition assertions)
"""

from __future__ import annotations

from enum import Enum
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Union

logger = logging.getLogger("tennenanchor.policies")


class NodeStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    RUNNING = "RUNNING"


class ExecutionContext:
    """Carries execution state, parameters, hardware controllers, and perception parsers."""

    def __init__(
        self,
        params: Optional[Dict[str, Any]] = None,
        hwnd: Optional[int] = None,
        controller: Optional[Any] = None,
        parser: Optional[Any] = None,
    ) -> None:
        self.params: Dict[str, Any] = params or {}
        self.hwnd: Optional[int] = hwnd
        self.variables: Dict[str, Any] = {}
        self.telemetry: List[Dict[str, Any]] = []

        # Lazy loading of controller and parser if not provided
        if controller is None:
            from actuation.controller import DesktopController
            self.controller = DesktopController()
        else:
            self.controller = controller

        if parser is None:
            from perception.edge_parser import EdgeUIAParser
            self.parser = EdgeUIAParser()
        else:
            self.parser = parser

    def interpolate(self, text: str) -> str:
        """Interpolates {param} tokens from context parameters and variables."""
        result = text
        merged = {**self.params, **self.variables}
        for k, v in merged.items():
            result = result.replace(f"{{{k}}}", str(v))
        return result


class BehaviorNode:
    """Base class for all Behavior Tree nodes."""

    def __init__(
        self,
        node_id: str,
        name: str = "",
        description: str = "",
        weight: float = 1.0,
        success_count: int = 0,
        failure_count: int = 0,
    ) -> None:
        self.node_id = node_id
        self.name = name or node_id
        self.description = description
        self.weight = float(weight)
        self.success_count = success_count
        self.failure_count = failure_count

    def tick(self, ctx: ExecutionContext) -> NodeStatus:
        raise NotImplementedError

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.node_id,
            "name": self.name,
            "description": self.description,
            "weight": self.weight,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BehaviorNode:
        node_type = data.get("type", "").lower()
        if node_type == "selector":
            return SelectorNode.from_dict(data)
        elif node_type == "sequence":
            return SequenceNode.from_dict(data)
        elif node_type == "condition":
            return ConditionNode.from_dict(data)
        elif node_type == "action":
            return ActionNode.from_dict(data)
        elif node_type == "verify":
            return VerifyNode.from_dict(data)
        else:
            raise ValueError(f"Unknown behavior node type: {node_type}")


class SelectorNode(BehaviorNode):
    """
    Selector / Fallback Composite Node ('?').
    Tries child branches in descending order of learned weight (confidence).
    Succeeds immediately if any child succeeds.
    Dynamically adjusts branch weights when a fallback resolves an obstacle.
    """

    def __init__(
        self,
        node_id: str,
        children: Optional[List[BehaviorNode]] = None,
        name: str = "",
        description: str = "",
        weight: float = 1.0,
        success_count: int = 0,
        failure_count: int = 0,
    ) -> None:
        super().__init__(node_id, name, description, weight, success_count, failure_count)
        self.children: List[BehaviorNode] = children or []

    def add_child(self, child: BehaviorNode) -> SelectorNode:
        self.children.append(child)
        return self

    def tick(self, ctx: ExecutionContext) -> NodeStatus:
        # Sort children by weight descending (probabilistic routing / learned priority)
        sorted_children = sorted(self.children, key=lambda c: c.weight, reverse=True)

        for idx, child in enumerate(sorted_children):
            t0 = time.perf_counter()
            status = child.tick(ctx)
            dt_ms = (time.perf_counter() - t0) * 1000

            if status == NodeStatus.SUCCESS:
                child.success_count += 1
                # Reward successful branch
                child.weight = min(10.0, child.weight + 0.1)
                self.success_count += 1
                ctx.telemetry.append({
                    "node_id": self.node_id,
                    "event": "selector_success",
                    "chosen_branch": child.node_id,
                    "branch_rank": idx + 1,
                    "latency_ms": dt_ms,
                })
                return NodeStatus.SUCCESS
            else:
                child.failure_count += 1
                # Penalize failing branch slightly
                child.weight = max(0.1, child.weight - 0.1)
                ctx.telemetry.append({
                    "node_id": self.node_id,
                    "event": "selector_branch_failed",
                    "failed_branch": child.node_id,
                    "branch_rank": idx + 1,
                    "latency_ms": dt_ms,
                })

        self.failure_count += 1
        return NodeStatus.FAILURE

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["type"] = "selector"
        d["children"] = [c.to_dict() for c in self.children]
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SelectorNode:
        children = [BehaviorNode.from_dict(c) for c in data.get("children", [])]
        return cls(
            node_id=data.get("id", "selector"),
            children=children,
            name=data.get("name", ""),
            description=data.get("description", ""),
            weight=data.get("weight", 1.0),
            success_count=data.get("success_count", 0),
            failure_count=data.get("failure_count", 0),
        )


class SequenceNode(BehaviorNode):
    """
    Sequence Composite Node ('->').
    Executes children in strict sequential order.
    Fails immediately if any child fails.
    """

    def __init__(
        self,
        node_id: str,
        children: Optional[List[BehaviorNode]] = None,
        name: str = "",
        description: str = "",
        weight: float = 1.0,
        success_count: int = 0,
        failure_count: int = 0,
    ) -> None:
        super().__init__(node_id, name, description, weight, success_count, failure_count)
        self.children: List[BehaviorNode] = children or []

    def add_child(self, child: BehaviorNode) -> SequenceNode:
        self.children.append(child)
        return self

    def tick(self, ctx: ExecutionContext) -> NodeStatus:
        for child in self.children:
            t0 = time.perf_counter()
            status = child.tick(ctx)
            dt_ms = (time.perf_counter() - t0) * 1000

            if status != NodeStatus.SUCCESS:
                self.failure_count += 1
                ctx.telemetry.append({
                    "node_id": self.node_id,
                    "event": "sequence_halted",
                    "failing_step": child.node_id,
                    "latency_ms": dt_ms,
                })
                return NodeStatus.FAILURE

        self.success_count += 1
        return NodeStatus.SUCCESS

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["type"] = "sequence"
        d["children"] = [c.to_dict() for c in self.children]
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SequenceNode:
        children = [BehaviorNode.from_dict(c) for c in data.get("children", [])]
        return cls(
            node_id=data.get("id", "sequence"),
            children=children,
            name=data.get("name", ""),
            description=data.get("description", ""),
            weight=data.get("weight", 1.0),
            success_count=data.get("success_count", 0),
            failure_count=data.get("failure_count", 0),
        )


class ConditionNode(BehaviorNode):
    """
    Condition Leaf Node ('[C]').
    Evaluates a boolean state predicate without side-effects.
    """

    def __init__(
        self,
        node_id: str,
        predicate: Dict[str, Any],
        name: str = "",
        description: str = "",
        weight: float = 1.0,
        success_count: int = 0,
        failure_count: int = 0,
    ) -> None:
        super().__init__(node_id, name, description, weight, success_count, failure_count)
        self.predicate = predicate

    def tick(self, ctx: ExecutionContext) -> NodeStatus:
        pred_type = self.predicate.get("type", "in_range")

        # Range check on a parameter
        if pred_type == "in_range":
            var_name = self.predicate.get("var", "index")
            val = ctx.params.get(var_name)
            if val is None:
                return NodeStatus.FAILURE
            try:
                num_val = float(val)
                min_v = float(self.predicate.get("min", float("-inf")))
                max_v = float(self.predicate.get("max", float("inf")))
                if min_v <= num_val <= max_v:
                    return NodeStatus.SUCCESS
                return NodeStatus.FAILURE
            except ValueError:
                return NodeStatus.FAILURE

        # Equality check
        elif pred_type == "equals":
            var_name = self.predicate.get("var", "")
            expected = self.predicate.get("value")
            actual = ctx.params.get(var_name, ctx.variables.get(var_name))
            if str(actual) == str(expected):
                return NodeStatus.SUCCESS
            return NodeStatus.FAILURE

        # UIA element existence check
        elif pred_type == "has_control":
            c_type = self.predicate.get("control_type")
            target_idx = self.predicate.get("index")
            active = ctx.parser.parse_active_window()
            elements = active.get("elements", [])
            matches = [
                el for el in elements
                if (not c_type or el.get("type", "").lower() == c_type.lower())
            ]
            if target_idx is not None:
                try:
                    idx = int(target_idx)
                    if 0 <= idx < len(matches):
                        return NodeStatus.SUCCESS
                    return NodeStatus.FAILURE
                except ValueError:
                    pass
            if len(matches) > 0:
                return NodeStatus.SUCCESS
            return NodeStatus.FAILURE

        # Custom boolean expression
        elif pred_type == "expression":
            expr = self.predicate.get("expr", "True")
            try:
                # Safe evaluation with merged context variables
                eval_env = {**ctx.params, **ctx.variables}
                if eval(expr, {"__builtins__": {}}, eval_env):
                    return NodeStatus.SUCCESS
                return NodeStatus.FAILURE
            except Exception as e:
                logger.debug("Condition eval error '%s': %s", expr, e)
                return NodeStatus.FAILURE

        return NodeStatus.FAILURE

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["type"] = "condition"
        d["predicate"] = self.predicate
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ConditionNode:
        return cls(
            node_id=data.get("id", "condition"),
            predicate=data.get("predicate", {}),
            name=data.get("name", ""),
            description=data.get("description", ""),
            weight=data.get("weight", 1.0),
            success_count=data.get("success_count", 0),
            failure_count=data.get("failure_count", 0),
        )


class ActionNode(BehaviorNode):
    """
    Action Leaf Node ('(A)').
    Executes an actuation primitive via DesktopController or UIA.
    """

    def __init__(
        self,
        node_id: str,
        action: Dict[str, Any],
        name: str = "",
        description: str = "",
        weight: float = 1.0,
        success_count: int = 0,
        failure_count: int = 0,
    ) -> None:
        super().__init__(node_id, name, description, weight, success_count, failure_count)
        self.action = action

    def tick(self, ctx: ExecutionContext) -> NodeStatus:
        act_type = self.action.get("type", "").lower()
        wait_ms = float(self.action.get("wait_ms", 150))

        try:
            # Hotkey dispatch
            if act_type == "hotkey":
                raw_keys = self.action.get("keys", [])
                keys = [ctx.interpolate(k) for k in raw_keys]
                repeat = int(self.action.get("repeat", 1))
                for _ in range(max(1, repeat)):
                    ctx.controller.hotkey(keys, target_hwnd=ctx.hwnd)
                    if repeat > 1:
                        time.sleep(0.08)

            # Type text
            elif act_type == "type":
                text = ctx.interpolate(self.action.get("text", ""))
                ctx.controller.type_text(text, target_hwnd=ctx.hwnd)

            # Single keypress
            elif act_type == "press_key":
                key = ctx.interpolate(self.action.get("key", ""))
                ctx.controller.press_key(key, target_hwnd=ctx.hwnd)

            # Direct coordinate click
            elif act_type == "click":
                x = int(ctx.interpolate(str(self.action.get("x", 0))))
                y = int(ctx.interpolate(str(self.action.get("y", 0))))
                ctx.controller.click(x, y, target_hwnd=ctx.hwnd)

            # UIA Accessibility Selection Item Pattern
            elif act_type == "uia_select":
                c_type = self.action.get("control_type", "TabItem")
                idx_raw = ctx.interpolate(str(self.action.get("index", "0")))
                idx = int(idx_raw)

                import uiautomation as auto
                hwnd = ctx.hwnd or ctx.controller.get_foreground_hwnd()
                ctrl = auto.ControlFromHandle(hwnd)
                items = [c for c in ctrl.GetChildren() if c.ControlTypeName == c_type]
                if 0 <= idx < len(items):
                    pattern = items[idx].GetSelectionItemPattern()
                    if pattern:
                        pattern.Select()
                    else:
                        rect = items[idx].BoundingRectangle
                        ctx.controller.click(rect.xcenter(), rect.ycenter())
                else:
                    return NodeStatus.FAILURE

            # Pause / Settle
            elif act_type == "wait":
                time.sleep(wait_ms / 1000.0)
                return NodeStatus.SUCCESS

            else:
                logger.warning("Unrecognized action type: %s", act_type)
                return NodeStatus.FAILURE

            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)

            return NodeStatus.SUCCESS

        except Exception as e:
            logger.warning("ActionNode '%s' failed: %s", self.node_id, e)
            return NodeStatus.FAILURE

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["type"] = "action"
        d["action"] = self.action
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ActionNode:
        return cls(
            node_id=data.get("id", "action"),
            action=data.get("action", {}),
            name=data.get("name", ""),
            description=data.get("description", ""),
            weight=data.get("weight", 1.0),
            success_count=data.get("success_count", 0),
            failure_count=data.get("failure_count", 0),
        )


class VerifyNode(BehaviorNode):
    """
    Verify Leaf Node ('[V]').
    Asserts that the target post-condition was achieved within a configured timeout.
    """

    def __init__(
        self,
        node_id: str,
        verify: Dict[str, Any],
        timeout_ms: float = 800.0,
        name: str = "",
        description: str = "",
        weight: float = 1.0,
        success_count: int = 0,
        failure_count: int = 0,
    ) -> None:
        super().__init__(node_id, name, description, weight, success_count, failure_count)
        self.verify = verify
        self.timeout_ms = timeout_ms

    def tick(self, ctx: ExecutionContext) -> NodeStatus:
        v_type = self.verify.get("type", "window_title")
        expected = ctx.interpolate(str(self.verify.get("value", "")))
        deadline = time.perf_counter() + (self.timeout_ms / 1000.0)

        while time.perf_counter() < deadline:
            active = ctx.parser.parse_active_window()
            win_title = active.get("window", "")

            # Title contains check
            if v_type == "window_title":
                if expected.lower() in win_title.lower():
                    return NodeStatus.SUCCESS

            # Control selection check
            elif v_type == "control_selected":
                c_type = self.verify.get("control_type", "TabItem")
                idx = int(ctx.interpolate(str(self.verify.get("index", 0))))
                import uiautomation as auto
                hwnd = ctx.hwnd or ctx.controller.get_foreground_hwnd()
                ctrl = auto.ControlFromHandle(hwnd)
                items = [c for c in ctrl.GetChildren() if c.ControlTypeName == c_type]
                if 0 <= idx < len(items):
                    sel = items[idx].GetSelectionItemPattern()
                    if sel and sel.IsSelected:
                        return NodeStatus.SUCCESS

            # Generic non-empty elements
            elif v_type == "has_elements":
                if len(active.get("elements", [])) >= int(expected or 1):
                    return NodeStatus.SUCCESS

            time.sleep(0.08)

        return NodeStatus.FAILURE

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["type"] = "verify"
        d["verify"] = self.verify
        d["timeout_ms"] = self.timeout_ms
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> VerifyNode:
        return cls(
            node_id=data.get("id", "verify"),
            verify=data.get("verify", {}),
            timeout_ms=data.get("timeout_ms", 800.0),
            name=data.get("name", ""),
            description=data.get("description", ""),
            weight=data.get("weight", 1.0),
            success_count=data.get("success_count", 0),
            failure_count=data.get("failure_count", 0),
        )
