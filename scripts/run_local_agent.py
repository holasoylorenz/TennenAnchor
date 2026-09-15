"""
Interactive Local Agent for TennenAnchor.
Bridges local llama.cpp models (Gemma 2 2B / Llama 3.2 3B) directly to TennenAnchor MCP tools.
Supports both interactive chat and one-shot goal execution with dual tool-call parsing (JSON & ACTION format).
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import urllib.error
import urllib.request

HARNESS_ROOT = Path(__file__).resolve().parent.parent
if str(HARNESS_ROOT) not in sys.path:
    sys.path.insert(0, str(HARNESS_ROOT))

from mcp_server import TOOLS, process_json_rpc

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("local_agent")

DEFAULT_SERVER_URL = "http://127.0.0.1:8080/v1/chat/completions"


def format_mcp_tools_for_openai() -> List[Dict[str, Any]]:
    """Translates TennenAnchor MCP tool definitions to OpenAI / llama-server function schemas."""
    openai_tools = []
    for tool in TOOLS:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool.get("inputSchema", {}),
            },
        })
    return openai_tools


def parse_text_action(text: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Parses text-based action calls like: ACTION: tool_name(arg1=val1, arg2=val2)"""
    m = re.search(r"ACTION:\s*([a-zA-Z0-9_]+)\s*\((.*?)\)", text, re.DOTALL)
    if not m:
        return None
    tool_name = m.group(1).strip()
    args_raw = m.group(2).strip()
    if not args_raw:
        return tool_name, {}

    # Try Python AST keyword parsing
    try:
        expr = ast.parse(f"call({args_raw})", mode="eval")
        kwargs = {}
        for kw in expr.body.keywords:  # type: ignore
            kwargs[kw.arg] = ast.literal_eval(kw.value)
        return tool_name, kwargs
    except Exception:
        pass

    # Fallback: JSON parsing
    try:
        return tool_name, json.loads(args_raw)
    except Exception:
        pass

    return tool_name, {}


class LocalMCPAgent:
    """Turn-by-turn agent loop executing autonomous desktop actions via local llama-server."""

    def __init__(self, api_url: str = DEFAULT_SERVER_URL):
        self.api_url = api_url
        self.tools = format_mcp_tools_for_openai()
        self.system_prompt = (
            "You are TennenAnchor Local Agent, an autonomous desktop assistant running on Windows.\n"
            "You have direct access to desktop tools:\n"
            "- desktop_inspect(query=None, mode='summary'): inspect active foreground window controls\n"
            "- desktop_act(action='click', coordinates={'x': ..., 'y': ...}): click or type\n"
            "- desktop_step(action='click', ...): act and re-inspect\n"
            "- app_execute_recipe(app='chrome', recipe='navigate', params={'url': '...'}): run verified app recipes\n"
            "- app_query(app='chrome'): query app state graphs\n\n"
            "INSTRUCTIONS:\n"
            "1. When the user asks you to inspect, check, or interact with the screen/PC, call a tool immediately.\n"
            "2. To perform an action, output:\n"
            "ACTION: tool_name(argument=value)\n"
            "Examples:\n"
            "  ACTION: desktop_inspect()\n"
            "  ACTION: app_execute_recipe(app='chrome', recipe='navigate', params={'url': 'https://google.com'})\n"
            "3. After receiving the tool observation, explain the result clearly to the user.\n"
        )

    def check_connection(self) -> str:
        """Verifies connection to llama-server and returns the loaded model name."""
        models_url = self.api_url.replace("/chat/completions", "/models")
        try:
            req = urllib.request.Request(models_url, headers={"User-Agent": "TennenAnchor/1.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = data.get("data", []) or data.get("models", [])
                if models:
                    return models[0].get("id") or models[0].get("name", "local-model")
                return "local-model"
        except Exception as e:
            raise ConnectionError(
                f"Cannot connect to llama-server at {models_url}.\n"
                "Please make sure llama-server is running in a terminal:\n"
                "  C:\\llama.cpp\\llama-server.exe -m C:\\llama.cpp\\models\\gemma-2-2b-it-Q4_K_M.gguf -c 4096 --port 8080\n"
            ) from e

    def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Dispatches a tool call directly to TennenAnchor MCP processor."""
        print(f"\n⚙️  [TennenAnchor Action]: {tool_name}({arguments})")
        req = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000) % 100000,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }
        res = process_json_rpc(req)
        if not res or "result" not in res:
            err = res.get("error", "No response from MCP") if res else "No response"
            return json.dumps({"error": err})

        content_blocks = res["result"].get("content", [])
        text_outputs = [b.get("text", "") for b in content_blocks if b.get("type") == "text"]
        result_text = "\n".join(text_outputs)
        preview = result_text[:280] + ("..." if len(result_text) > 280 else "")
        print(f"👁️  [Perception Result]:\n{preview}\n")
        return result_text

    def call_llm(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Queries the local llama-server."""
        payload = {
            "messages": messages,
            "tools": self.tools,
            "tool_choice": "auto",
            "temperature": 0.1,
            "max_tokens": 512,
        }
        req = urllib.request.Request(
            self.api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]

    def run_turn(self, user_text: str, conversation_history: List[Dict[str, Any]], max_steps: int = 4) -> None:
        """Runs a user turn with iterative tool execution."""
        conversation_history.append({"role": "user", "content": user_text})

        for step in range(1, max_steps + 1):
            print("⏳ [Model is thinking...]", end="\r", flush=True)
            msg = self.call_llm(conversation_history)
            print(" " * 30, end="\r")  # Clear thinking indicator

            content = (msg.get("content") or "").strip()
            tool_calls = msg.get("tool_calls") or []

            # Check for text-based ACTION if native tool_calls is empty
            action_parsed = None
            if not tool_calls and "ACTION:" in content:
                action_parsed = parse_text_action(content)

            if content:
                # Remove raw action string from user display for clean output
                clean_display = re.sub(r"ACTION:\s*[a-zA-Z0-9_]+\(.*?\)", "", content).strip()
                if clean_display:
                    print(f"\n🤖 [Agent]: {clean_display}")

            conversation_history.append(msg)

            # If no tools called, we're done with this turn
            if not tool_calls and not action_parsed:
                break

            # Execute native tool calls
            if tool_calls:
                for tc in tool_calls:
                    func = tc.get("function", {})
                    t_name = func.get("name")
                    t_args_raw = func.get("arguments", "{}")
                    t_args = json.loads(t_args_raw) if isinstance(t_args_raw, str) else t_args_raw
                    t_res = self.execute_tool(t_name, t_args)
                    conversation_history.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", f"call_{int(time.time())}"),
                        "name": t_name,
                        "content": t_res,
                    })

            # Execute text-based ACTION
            elif action_parsed:
                t_name, t_args = action_parsed
                t_res = self.execute_tool(t_name, t_args)
                conversation_history.append({
                    "role": "user",
                    "content": f"[Observation from {t_name}]:\n{t_res}\nPlease explain what you found or take the next action.",
                })


def main() -> None:
    agent = LocalMCPAgent()
    try:
        model_name = agent.check_connection()
    except ConnectionError as e:
        print(f"\n❌ {e}")
        return

    print("=" * 65)
    print(f"  TennenAnchor Local Agent — Connected to llama-server")
    print(f"  Active Model: {model_name}")
    print(f"  Tools: desktop_inspect, desktop_act, app_execute_recipe ...")
    print("=" * 65)
    print("Type your request below (or 'exit' to quit):\n")

    # If argument passed via CLI, run that single goal
    if len(sys.argv) > 1:
        user_input = " ".join(sys.argv[1:])
        print(f"You: {user_input}")
        history = [{"role": "system", "content": agent.system_prompt}]
        agent.run_turn(user_input, history)
        return

    # Otherwise enter interactive REPL
    history = [{"role": "system", "content": agent.system_prompt}]
    while True:
        try:
            user_input = input("You: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "q"):
                print("Goodbye!")
                break

            agent.run_turn(user_input, history)
            print()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break


if __name__ == "__main__":
    main()
