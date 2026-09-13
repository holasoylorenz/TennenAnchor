"""
Model Context Protocol (MCP) Server for Windows Desktop Automation.
Exposes high-efficiency desktop tools, App-AST state graphs, verified action recipes,
and struggle/friction tracking to Antigravity CLI (AGY CLI).
Strictly adheres to stdio JSON-RPC 2.0 with stream isolation (all logs to stderr).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# Stream isolation: stdout for JSON-RPC only, logs to stderr
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [desktop_mcp] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("desktop_mcp")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from actuation.controller import DesktopController
from core.app_ast import ProfileRegistry
from core.dpi import init_dpi_awareness, transform_to_screen_coords
from core.playbook_runner import PlaybookRunner
from core.safety import validate_target_action
from core.struggle_tracker import StruggleTracker
from perception.edge_parser import EdgeUIAParser
from perception.screenshot_escalator import ScreenshotEscalator

# Initialize subsystems
init_dpi_awareness()
parser = EdgeUIAParser()
escalator = ScreenshotEscalator()
controller = DesktopController()
registry = ProfileRegistry()
tracker = StruggleTracker()
runner = PlaybookRunner(controller=controller, parser=parser, tracker=tracker, registry=registry)

# Cache latest state
LATEST_STATE: Dict[str, Any] = {
    "tier": 1,
    "window_name": "",
    "hwnd": None,
    "rect": None,
    "elements": {},
    "last_escalation": None,
}

TOOLS = [
    {
        "name": "desktop_inspect",
        "description": (
            "Fast Tier 1 Edge AI screen perception (<35ms). Returns active window name, dimensions, "
            "and compact list of interactable UI controls (#ID, Type, Label, Coordinates). "
            "Provide 'query' to filter for specific controls (e.g. 'Save', 'Search')."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional search term to filter controls by text/name (e.g. 'File', 'Submit').",
                },
                "mode": {
                    "type": "string",
                    "enum": ["summary", "find", "all"],
                    "default": "summary",
                    "description": "Perception mode. 'summary' returns top interactive controls; 'find' filters by query.",
                },
            },
        },
    },
    {
        "name": "desktop_escalate",
        "description": (
            "Tier 2 Visual Escalation Fallback. Captures an optimized, compressed screenshot (max 1280px) "
            "when Tier 1 finds 0 controls (e.g. custom graphics, canvas, games) or when visual inspection is needed. "
            "Returns image file path, dimensions, and normalized coordinate mapping info."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "enum": ["active_window", "full_screen"],
                    "default": "active_window",
                    "description": "Target capture area.",
                }
            },
        },
    },
    {
        "name": "desktop_act",
        "description": (
            "Executes mouse or keyboard actions. Target can be specified either via 'element_id' (#ID from desktop_inspect) "
            "OR via 'coordinates' (x, y from desktop_escalate visual screenshot)."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["click", "double_click", "right_click", "move", "drag", "scroll", "type", "hotkey", "press_key"],
                    "description": "Action type to execute.",
                },
                "element_id": {
                    "type": "integer",
                    "description": "Target element #ID from latest desktop_inspect result.",
                },
                "coordinates": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "number", "description": "X coordinate."},
                        "y": {"type": "number", "description": "Y coordinate."},
                        "is_normalized": {
                            "type": "boolean",
                            "default": False,
                            "description": "Set True if coordinates are in [0, 1000] space (Gemini vision grounding).",
                        },
                    },
                    "description": "Coordinates for mouse action if element_id is not used.",
                },
                "text": {
                    "type": "string",
                    "description": "Text to type for 'type' action.",
                },
                "press_enter": {
                    "type": "boolean",
                    "default": False,
                    "description": "Whether to press Enter key after typing text.",
                },
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keys for 'hotkey' action (e.g. ['win', 'r'], ['ctrl', 's']).",
                },
                "key": {
                    "type": "string",
                    "description": "Single key for 'press_key' action (e.g. 'enter', 'esc', 'tab').",
                },
                "scroll_direction": {
                    "type": "string",
                    "enum": ["up", "down"],
                    "default": "down",
                    "description": "Direction for 'scroll' action.",
                },
                "scroll_clicks": {
                    "type": "integer",
                    "default": 3,
                    "description": "Number of scroll clicks.",
                },
            },
        },
    },
    {
        "name": "desktop_step",
        "description": (
            "Composite Power Tool: Executes an action, waits 250ms for UI transition, and automatically returns "
            "the updated foreground window status in a single turn. Cuts multi-step token consumption in half."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["click", "double_click", "right_click", "type", "hotkey", "press_key"],
                    "description": "Action type to perform.",
                },
                "element_id": {"type": "integer", "description": "Element #ID to target."},
                "text": {"type": "string", "description": "Text to type."},
                "press_enter": {"type": "boolean", "default": False},
                "keys": {"type": "array", "items": {"type": "string"}},
                "key": {"type": "string"},
                "wait_ms": {"type": "integer", "default": 250, "description": "Wait time in ms for UI to settle."},
            },
        },
    },
    {
        "name": "app_query",
        "description": (
            "Queries the App-AST profile for a desktop application (e.g. 'ltspice', 'winword'). "
            "Returns recognized UI states, verified macro action recipes, domain hints, and top logged struggles."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "app": {
                    "type": "string",
                    "description": "Application ID to inspect (e.g. 'ltspice'). Omit to list all registered applications.",
                },
            },
        },
    },
    {
        "name": "app_execute_recipe",
        "description": (
            "Executes a pre-compiled, verified App-AST macro recipe in a single turn. "
            "Drastically cuts token consumption and enforces pre- and post-condition checks."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["app", "recipe"],
            "properties": {
                "app": {
                    "type": "string",
                    "description": "Application ID (e.g. 'ltspice').",
                },
                "recipe": {
                    "type": "string",
                    "description": "Recipe ID to execute (e.g. 'open_schematic', 'run_simulation').",
                },
                "params": {
                    "type": "object",
                    "description": "Key-value parameters for the recipe (e.g. {'path': 'C:/path/file.asc'}).",
                },
            },
        },
    },
    {
        "name": "app_record_struggle",
        "description": (
            "Records an operational friction point or quirk into the persistent struggle ledger for future self-refinement."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["app", "action", "symptom"],
            "properties": {
                "app": {"type": "string", "description": "Application ID."},
                "action": {"type": "string", "description": "Action attempted."},
                "symptom": {"type": "string", "description": "Failure symptom or unhandled state."},
                "resolution": {"type": "string", "description": "Resolution or workaround discovered."},
                "refinement": {"type": "string", "description": "Refinement suggestion for AST or prompts."},
                "category": {
                    "type": "string",
                    "enum": ["EXECUTION_ERROR", "STATE_MISMATCH", "UNRESPONSIVE_MECHANISM", "AGENT_FRICTION"],
                    "default": "AGENT_FRICTION",
                },
                "severity": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                    "default": "medium",
                },
            },
        },
    },
]


def resolve_coordinates(params: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    """Resolves physical screen (x, y) from either element_id or coordinates parameter."""
    element_id = params.get("element_id")
    if element_id is not None:
        cached_el = parser.last_cache.get(element_id)
        if cached_el and "center" in cached_el:
            return cached_el["center"]
        logger.warning("element_id #%s not found in cache. Cached IDs: %s", element_id, list(parser.last_cache.keys()))
        return None

    coords = params.get("coordinates")
    if coords and "x" in coords and "y" in coords:
        raw_x = float(coords["x"])
        raw_y = float(coords["y"])
        is_norm = coords.get("is_normalized", False)

        rect = LATEST_STATE.get("rect")
        if not rect:
            from core.dpi import get_screen_metrics
            m = get_screen_metrics()
            rect = (m["left"], m["top"], m["width"], m["height"])

        return transform_to_screen_coords(raw_x, raw_y, rect, is_normalized=is_norm)

    return None


def handle_desktop_inspect(params: Dict[str, Any]) -> str:
    """Handles Tier 1 edge inspection."""
    query = params.get("query")
    res = parser.parse_active_window(query=query)

    LATEST_STATE["tier"] = 1
    LATEST_STATE["window_name"] = res.get("window", "")
    LATEST_STATE["hwnd"] = res.get("hwnd")
    LATEST_STATE["rect"] = res.get("rect")

    return parser.format_compact_text(res)


def handle_desktop_escalate(params: Dict[str, Any]) -> Union[str, List[Dict[str, Any]]]:
    """Handles Tier 2 visual escalation, returning standard MCP image content and metadata."""
    target = params.get("target", "active_window")
    hwnd = LATEST_STATE.get("hwnd")
    res = escalator.capture(target=target, hwnd=hwnd)

    if res.get("status") != "ok":
        return f"[ESCALATION FAILED]: {res.get('reason')}"

    LATEST_STATE["tier"] = 2
    LATEST_STATE["rect"] = res.get("original_rect")
    LATEST_STATE["last_escalation"] = res

    text_msg = (
        f"[TIER 2 VISUAL ESCALATION SUCCESS]\n"
        f"Saved: {res['image_path']}\n"
        f"Target: {res['target']} | Physical Rect: {res['original_rect']}\n"
        f"Scaled Size: {res['scaled_size']} (Tokens: ~700)\n"
        f"Instructions: Use desktop_act with coordinates (normalized [0, 1000] or pixels) to interact."
    )

    content: List[Dict[str, Any]] = [{"type": "text", "text": text_msg}]
    if res.get("base64_image"):
        content.append({
            "type": "image",
            "data": res["base64_image"],
            "mimeType": "image/png",
        })

    return content


def handle_desktop_act(params: Dict[str, Any]) -> str:
    """Handles unified actuation."""
    action = params.get("action")
    hwnd = LATEST_STATE.get("hwnd")

    if action in ("click", "double_click", "right_click", "move"):
        coords = resolve_coordinates(params)
        if not coords:
            return (
                "Error: Target coordinates could not be resolved. "
                "Specify valid element_id (from desktop_inspect) or coordinates {\"x\": ..., \"y\": ...}."
            )

        target_btn = "left"
        if action == "double_click":
            target_btn = "double"
        elif action == "right_click":
            target_btn = "right"

        if action == "move":
            res = controller.move_cursor(coords[0], coords[1])
        else:
            res = controller.click(coords[0], coords[1], button=target_btn)

        if res.get("status") != "ok":
            return f"Actuation failed: {res.get('error')}"
        return f"Success: {action} at ({coords[0]}, {coords[1]})"

    elif action == "drag":
        coords = params.get("coordinates", {})
        start_x = int(coords.get("start_x", 0))
        start_y = int(coords.get("start_y", 0))
        end_x = int(coords.get("end_x", 0))
        end_y = int(coords.get("end_y", 0))
        res = controller.drag(start_x, start_y, end_x, end_y)
        return f"Drag result: {res.get('status')} {res.get('error', '')}"

    elif action == "scroll":
        direction = params.get("scroll_direction", "down")
        clicks = params.get("scroll_clicks", 3)
        res = controller.scroll(clicks=clicks, direction=direction)
        return f"Scroll result: {res.get('status')} {direction} {clicks} clicks"

    elif action == "type":
        text = params.get("text", "")
        press_enter = params.get("press_enter", False)
        res = controller.type_text(text, press_enter=press_enter, target_hwnd=hwnd)
        if res.get("status") != "ok":
            return f"Type failed: {res.get('error')}"
        return f"Success: Typed {len(text)} characters (Enter={press_enter})"

    elif action == "hotkey":
        keys = params.get("keys", [])
        if not keys:
            return "Error: 'keys' array required for hotkey action (e.g. ['win', 'r'])."
        res = controller.hotkey(keys, target_hwnd=hwnd)
        if res.get("status") != "ok":
            return f"Hotkey failed: {res.get('error')}"
        return f"Success: Pressed hotkey {keys}"

    elif action == "press_key":
        key = params.get("key", "")
        if not key:
            return "Error: 'key' required for press_key action (e.g. 'enter')."
        res = controller.press_key(key)
        return f"Press key result: {res.get('status')} for '{key}'"

    return f"Unknown action: {action}"


def handle_desktop_step(params: Dict[str, Any]) -> str:
    """Executes action, pauses for UI settle, and returns new foreground state in 1 turn."""
    act_summary = handle_desktop_act(params)

    wait_ms = params.get("wait_ms", 250)
    time.sleep(max(50, wait_ms) / 1000.0)

    inspect_res = parser.parse_active_window()
    LATEST_STATE["hwnd"] = inspect_res.get("hwnd")
    LATEST_STATE["rect"] = inspect_res.get("rect")

    post_state = parser.format_compact_text(inspect_res, delta_only=True)
    return f"Step Action: {act_summary}\n\nPost-Action State:\n{post_state}"


def handle_app_query(params: Dict[str, Any]) -> str:
    """Queries App-AST profiles and struggle ledger."""
    app_id = params.get("app")
    registry.reload()

    if not app_id:
        apps = registry.list_apps()
        lines = [f"Registered App-AST Profiles ({len(apps)}):"]
        for a in apps:
            p = registry.get(a)
            if p:
                lines.append(f"• {p.app_id} ({p.name}) - {len(p.states)} states, {len(p.recipes)} verified recipes")
        lines.append("\nQuery specific app via app_query(app='<app_id>') for state tree and recipes.")
        return "\n".join(lines)

    profile = registry.get(app_id)
    if not profile:
        return f"Error: Application profile '{app_id}' not found. Available: {', '.join(registry.list_apps())}"

    # Also query struggles for this app
    struggles_report = tracker.format_report(app=app_id)

    payload = {
        "app_id": profile.app_id,
        "name": profile.name,
        "states": {k: s.name for k, s in profile.states.items()},
        "recipes": {k: f"{r.name} ({len(r.steps)} steps)" for k, r in profile.recipes.items()},
        "domain_hints": profile.domain_hints,
    }

    return (
        f"[APP-AST PROFILE: {profile.name} ({profile.app_id})]\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        f"{struggles_report}"
    )


def handle_app_execute_recipe(params: Dict[str, Any]) -> str:
    """Executes a pre-compiled App-AST recipe."""
    app_id = params.get("app")
    recipe_id = params.get("recipe")
    recipe_params = params.get("params", {})

    profile = registry.get(app_id)
    if not profile:
        return f"Error: App profile '{app_id}' not found."

    hwnd = LATEST_STATE.get("hwnd")
    res = runner.execute(profile=profile, recipe_id=recipe_id, params=recipe_params, hwnd=hwnd)

    if res.get("status") != "ok":
        return f"[RECIPE FAILED]: {res.get('error')} (Completed {res.get('steps_completed')}/{res.get('total_steps')} steps)"

    if res.get("pinned_hwnd"):
        LATEST_STATE["hwnd"] = res.get("pinned_hwnd")

    out_lines = [
        f"[RECIPE SUCCESS: {recipe_id}]",
        f"Completed {res.get('steps_completed')}/{res.get('total_steps')} steps in {res.get('duration_ms')}ms.",
        f"State: {res.get('initial_state')} -> {res.get('final_state')}",
        f"Active Window: {res.get('window')}",
    ]
    if res.get("pinned_hwnd"):
        out_lines.append(f"Pinned HWND: {res.get('pinned_hwnd')}")
    if res.get("artifacts"):
        out_lines.append(f"Extracted Artifacts: {json.dumps(res.get('artifacts'), indent=2)}")

    return "\n".join(out_lines)


def handle_app_record_struggle(params: Dict[str, Any]) -> str:
    """Records an operational friction point."""
    app = params.get("app", "generic")
    action = params.get("action", "")
    symptom = params.get("symptom", "")
    resolution = params.get("resolution")
    refinement = params.get("refinement")
    category = params.get("category", "AGENT_FRICTION")
    severity = params.get("severity", "medium")

    ev = tracker.record(
        app=app,
        action=action,
        category=category,
        symptom=symptom,
        resolution=resolution,
        refinement=refinement,
        severity=severity,
    )
    return f"Friction logged: {ev.id} for {ev.app} (Total hits: {ev.occurrences})"


def process_json_rpc(request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Processes incoming JSON-RPC 2.0 requests from AGY CLI."""
    method = request.get("method")
    msg_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "desktop-harness",
                    "version": "1.1.0",
                },
            },
        }

    elif method == "notifications/initialized":
        logger.info("AGY CLI initialized connection.")
        return None

    elif method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"tools": TOOLS},
        }

    elif method == "tools/call":
        params = request.get("params", {})
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        try:
            if tool_name == "desktop_inspect":
                raw_out = handle_desktop_inspect(arguments)
            elif tool_name == "desktop_escalate":
                raw_out = handle_desktop_escalate(arguments)
            elif tool_name == "desktop_act":
                raw_out = handle_desktop_act(arguments)
            elif tool_name == "desktop_step":
                raw_out = handle_desktop_step(arguments)
            elif tool_name == "app_query":
                raw_out = handle_app_query(arguments)
            elif tool_name == "app_execute_recipe":
                raw_out = handle_app_execute_recipe(arguments)
            elif tool_name == "app_record_struggle":
                raw_out = handle_app_record_struggle(arguments)
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"Tool '{tool_name}' not found."},
                }

            if isinstance(raw_out, list):
                content_payload = raw_out
            else:
                content_payload = [{"type": "text", "text": str(raw_out)}]

            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": content_payload,
                    "isError": False,
                },
            }
        except Exception as e:
            logger.exception("Error executing tool %s: %s", tool_name, e)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": f"Execution error: {str(e)}"}],
                    "isError": True,
                },
            }

    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"Method '{method}' not recognized."},
    }


def main() -> None:
    """Main stdio JSON-RPC server loop."""
    logger.info("Desktop Control MCP Server v1.1.0 starting on stdio...")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
            resp = process_json_rpc(req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
        except json.JSONDecodeError as e:
            logger.error("JSON parse error: %s", e)
        except Exception as e:
            logger.exception("Unexpected server loop error: %s", e)


if __name__ == "__main__":
    main()
