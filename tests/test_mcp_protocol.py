"""Unit tests for stdio JSON-RPC MCP server protocol compliance."""

import pytest
from mcp_server import process_json_rpc, TOOLS


def test_mcp_initialize():
    """Verifies that MCP initialize handshake returns compliant protocol payload."""
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "agy-cli", "version": "1.0.0"}
        }
    }
    resp = process_json_rpc(req)
    assert resp is not None
    assert resp["id"] == 1
    assert "result" in resp
    assert resp["result"]["serverInfo"]["name"] == "tennenanchor"
    assert "tools" in resp["result"]["capabilities"]


def test_mcp_tools_list():
    """Verifies that tools/list exposes all 7 streamlined desktop tools."""
    req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {}
    }
    resp = process_json_rpc(req)
    assert resp is not None
    assert resp["id"] == 2
    tools = resp["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert "desktop_inspect" in tool_names
    assert "desktop_escalate" in tool_names
    assert "desktop_act" in tool_names
    assert "desktop_step" in tool_names
    assert "app_query" in tool_names
    assert "app_execute_recipe" in tool_names
    assert "app_record_struggle" in tool_names


def test_mcp_desktop_inspect_call():
    """Verifies tools/call executes desktop_inspect and returns text content block."""
    req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "desktop_inspect",
            "arguments": {"mode": "summary"}
        }
    }
    resp = process_json_rpc(req)
    assert resp is not None
    assert resp["id"] == 3
    assert resp["result"]["isError"] is False
    content = resp["result"]["content"]
    assert len(content) > 0
    assert content[0]["type"] == "text"
    assert len(content[0]["text"]) > 0


def test_mcp_desktop_escalate_call():
    """Verifies tools/call executes desktop_escalate and captures a valid screenshot."""
    req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "desktop_escalate",
            "arguments": {"target": "full_screen"}
        }
    }
    resp = process_json_rpc(req)
    assert resp is not None
    assert resp["id"] == 4
    assert resp["result"]["isError"] is False
    content = resp["result"]["content"]
    assert any(c.get("type") == "text" and "TIER 2 VISUAL ESCALATION" in c.get("text", "") for c in content)
    assert any(c.get("type") == "image" and len(c.get("data", "")) > 100 for c in content)
