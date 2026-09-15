"""
Local Autonomous Agent Loop for TennenAnchor.
Bridges local llama.cpp models (Gemma 2 2B / Llama 3.2 3B) directly to the TennenAnchor MCP tools.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
import urllib.request
import urllib.error

HARNESS_ROOT = Path(__file__).resolve().parent.parent
if str(HARNESS_ROOT) not in sys.path:
    sys.path.insert(0, str(HARNESS_ROOT))

from mcp_server import process_json_rpc, TOOLS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("local_agent")

DEFAULT_SERVER_URL = "http://127.0.0.1:8080/v1/chat/completions"


def format_mcp_tools_for_openai() -> list[dict]:
    """Translates TennenAnchor MCP tool definitions to OpenAI / llama-server function schemas."""
    openai_tools = []
    for tool in TOOLS:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool.get("inputSchema", {}),
            }
        })
    return openai_tools


class LocalMCPAgent:
    """Turn-by-turn agent loop executing autonomous desktop actions via local llama-server."""

    def __init__(self, api_url: str = DEFAULT_SERVER_URL, model_name: str = "local-model"):
        self.api_url = api_url
        self.model_name = model_name
        self.tools = format_mcp_tools_for_openai()
        self.system_prompt = (
            "You are TennenAnchor Local Agent, an autonomous desktop assistant running on Windows.\n"
            "You have direct access to desktop tools: desktop_inspect, desktop_act, desktop_step, app_query, app_execute_recipe.\n"
            "Rules:\n"
            "1. When asked to interact with an application, inspect the window first or execute an App-AST verified recipe.\n"
            "2. Always output concise reasoning followed by calling the appropriate tool.\n"
            "3. Strive to complete the user's objective in as few steps as possible."
        )

    def execute_tool(self, tool_name: str, arguments: dict) -> str:
        """Dispatches tool call to TennenAnchor MCP processor."""
        logger.info("[MCP EXEC] Tool: %s | Args: %s", tool_name, arguments)
        req = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000) % 100000,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            }
        }
        res = process_json_rpc(req)
        if not res or "result" not in res:
            return json.dumps({"error": res.get("error", "Unknown MCP execution error") if res else "No response"})

        # Extract text content block from MCP response
        content_blocks = res["result"].get("content", [])
        text_outputs = [b.get("text", "") for b in content_blocks if b.get("type") == "text"]
        result_text = "\n".join(text_outputs)
        logger.info("[MCP RESULT] %s", result_text[:200] + ("..." if len(result_text) > 200 else ""))
        return result_text

    def step(self, messages: list[dict]) -> dict:
        """Sends chat completion request to llama-server."""
        payload = {
            "model": self.model_name,
            "messages": messages,
            "tools": self.tools,
            "tool_choice": "auto",
            "temperature": 0.1,
            "max_tokens": 512,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.api_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result["choices"][0]["message"]
        except urllib.error.URLError as e:
            raise ConnectionError(
                f"Could not connect to llama-server at {self.api_url}. "
                "Ensure llama-server.exe is running! "
                "Start it with: C:\\llama.cpp\\llama-server.exe -m C:\\llama.cpp\\models\\gemma-2-2b-it-Q4_K_M.gguf --port 8080"
            ) from e

    def run_goal(self, user_goal: str, max_turns: int = 10) -> None:
        """Runs an autonomous goal loop."""
        print("\n" + "=" * 60)
        print(f"  TennenAnchor Local Agent — Goal: {user_goal}")
        print("=" * 60 + "\n")

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_goal},
        ]

        for turn in range(1, max_turns + 1):
            print(f"\n--- Turn {turn}/{max_turns} ---")
            msg = self.step(messages)
            content = msg.get("content") or ""
            tool_calls = msg.get("tool_calls") or []

            if content:
                print(f"[Agent Thoughts]:\n{content}\n")

            messages.append(msg)

            if not tool_calls:
                print("[Agent]: Goal completed or waiting for user input.")
                break

            for tc in tool_calls:
                func = tc.get("function", {})
                t_name = func.get("name")
                t_args_raw = func.get("arguments", "{}")
                t_args = json.loads(t_args_raw) if isinstance(t_args_raw, str) else t_args_raw

                t_res = self.execute_tool(t_name, t_args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", f"call_{int(time.time())}"),
                    "name": t_name,
                    "content": t_res,
                })


def main() -> None:
    goal = "Inspect what application is currently open on my screen and report what controls you see."
    if len(sys.argv) > 1:
        goal = " ".join(sys.argv[1:])

    agent = LocalMCPAgent()
    agent.run_goal(goal)


if __name__ == "__main__":
    main()
