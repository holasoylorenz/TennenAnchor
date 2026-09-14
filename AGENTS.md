# AGENTS.md — GroundPlane Agent Guide

Operational runtime guidance for AI computer-use agents (Claude Code, Antigravity CLI, Cursor, OpenAI) interacting with Windows desktop and EDA applications via GroundPlane.

---

## 1. Quickstart & Verification Commands

All commands assume Windows 10/11 with Python 3.10+ and Per-Monitor v2 DPI awareness.

```powershell
# 0. One-time setup (install dependencies in editable mode)
py -3 -m pip install -e .

# 1. Run unit test suite (fast verification, 47 tests, ~5s)
py -3 -m pytest

# 2. Inspect active foreground window (Tier 1 UIA, <35ms)
py -3 harness.py inspect
py -3 harness.py inspect --query "Run"

# 3. Focus / Launch target application via Shell COM Broker
py -3 harness.py launch ltspice

# 4. Query App-AST profiles, states, and verified recipes
py -3 harness.py ast
py -3 harness.py ast --app ltspice

# 5. Execute an App-AST verified recipe (add --record for GIF visual proof)
py -3 harness.py recipe ltspice open_schematic --params path=C:/path/circuit.asc
py -3 harness.py recipe ltspice run_simulation --record

# 6. Check buffer synchronization (disk vs GUI memory)
py -3 harness.py sync outputs/miller_ota.asc --app ltspice

# 7. Check struggle & friction ledger
py -3 harness.py struggles --app ltspice

# 8. Run empirical latency & token benchmark
py -3 harness.py benchmark --samples 10 --no-save
```

---

## 2. MCP Server Configuration & CLI-to-MCP Translation

### Execution Context Guidance
- **Terminal/Shell-Based Agents (Claude Code, Antigravity bash/powershell)**: Execute operations directly via `py -3 harness.py <command>`.
- **Connected MCP Agents (Cursor, Claude Desktop, Antigravity MCP)**: Invoke the corresponding MCP tools over JSON-RPC 2.0.

### CLI Command $\longleftrightarrow$ MCP Tool Mapping

| Intent | CLI Command (`harness.py`) | MCP Tool Equivalent (`mcp_server.py`) | Operational Profile |
| :--- | :--- | :--- | :--- |
| **Inspect UI** | `py -3 harness.py inspect [-q Q]` | `desktop_inspect(query=Q)` | Tier 1 UIA crawl (<35ms, ~70 tokens) |
| **Visual Fallback** | `py -3 harness.py escalate` | `desktop_escalate()` | Tier 2 Lanczos 1280px screenshot (~700 tokens) |
| **Act + Settle + Inspect** | *(Composite turn)* | `desktop_step(action=..., ...)` | Actuates + 250ms settle + delta perception in 1 turn |
| **Execute Macro Recipe**| `py -3 harness.py recipe <app> <r> -p k=v` | `app_execute_recipe(app, recipe, params)`| Pinned HWND transaction + dual verification |
| **Query App Profiles** | `py -3 harness.py ast [--app A]` | `app_query(app=A)` | Lists states, verified recipes & domain hints |
| **Check Friction Ledger**| `py -3 harness.py struggles [--app A]` | `app_query(app=A)` | Returns logged failure telemetry & workarounds |
| **Record New Friction** | *(Automated upon recipe failure)* | `app_record_struggle(...)` | Writes to persistent `knowledge/friction_ledger.json` |
| **Launch / Focus App** | `py -3 harness.py launch <app>` | *Handled automatically in `app_execute_recipe`* | Interactive Shell COM dispatch (`winsta0\default`) |
| **Working Buffer Sync** | `py -3 harness.py sync <path> --app A` | *Handled automatically in `app_execute_recipe`* | Detects stale tabs, enforces `Ctrl+W` discard |

### MCP Server Protocol
The MCP server entry point is [`mcp_server.py`](mcp_server.py).
It communicates over **stdio JSON-RPC 2.0** with strict stream isolation:
- `stdout`: Reserved exclusively for JSON-RPC messages. **NEVER print to stdout.**
- `stderr`: Structured diagnostic logs.

### Client Configuration (`mcp_config.json`)
```json
{
  "mcpServers": {
    "groundplane": {
      "command": "py",
      "args": ["-3", "C:\\path\\to\\groundplane\\mcp_server.py"]
    }
  }
}
```

### Available MCP Tools

| MCP Tool | Purpose | Primary Arguments |
| :--- | :--- | :--- |
| `desktop_inspect` | Fast Tier 1 UIA screen parse (<35ms). Returns active window controls (#ID, Type, Label, Coords). | `query` (optional string), `mode` (`summary` \| `find` \| `all`) |
| `desktop_escalate` | Tier 2 visual fallback (screenshot downscaled to 1280px Lanczos). Used for custom canvases / EDA. | `target` (`active_window` \| `full_screen`) |
| `desktop_act` | Unified actuation (mouse clicks, typing, hotkeys). Target by `#ID` or coordinates. | `action` (`click`, `double_click`, `right_click`, `type`, `hotkey`, `press_key`), `element_id`, `coordinates`, `text`, `keys`, `key` |
| `desktop_step` | **Composite Power Tool**: Acts + waits 250ms UI settle + re-inspects in 1 turn (cuts tokens 50%). | Same as `desktop_act` plus `wait_ms` (default 250) |
| `app_query` | Introspects registered App-AST profiles, states, recipes, domain hints, and friction ledger. | `app` (optional string, e.g. `'ltspice'`, omit for list) |
| `app_execute_recipe`| Executes multi-step App-AST macro with HWND pinning, focus protection, dual verification, and optional GIF recording. | `app` (string), `recipe` (string), `params` (object), `record` (optional bool) |
| `app_record_struggle`| Logs operational quirks, state mismatches, or UI failures into persistent ledger. | `app`, `action`, `symptom`, `resolution`, `refinement`, `category`, `severity` |

---

## 3. Core Architectural Invariants (Golden Rules)

### Rule 1: Prefer Recipes over Raw Clicks (99.9% Token Reduction)
Do not manually click through dialogs or menus when an App-AST recipe exists.
- **Bad**: `desktop_inspect` $\to$ click File $\to$ `desktop_inspect` $\to$ click Open $\to$ `desktop_inspect` $\to$ type path $\to$ click OK (15 turns, ~10k tokens).
- **Good**: `app_execute_recipe(app="ltspice", recipe="open_schematic", params={"path": "..."})` (1 turn, ~35 tokens).

### Rule 2: Foreground Focus & User-Space Invariant
GroundPlane operates on applications running in the user's interactive desktop space.
Because agent subshells running in sandboxed console sessions cannot cross Windows station boundaries to cold-spawn top-level GUI surfaces from a closed state, **the target application must already be open in the user's desktop space**.
- **Operation**: Once the application is running in user space, GroundPlane discovers its HWND, un-minimizes it, asserts focus, and executes closed-loop macro recipes automatically.
- **Rule for Agents**: Ensure the target application is running in user space. If not found, inform the user to open the application so GroundPlane can attach to it.

### Rule 3: Working Buffer Synchronization (Disk vs GUI)
Native desktop software (LTspice, Word, CAD) **does NOT automatically reload modified files from disk** if the file tab is already open in memory.
- If you edit a file on disk (e.g., netlist or document), the open tab is stale.
- Always check reload strategy via `py -3 harness.py sync <path> --app <app>` or use recipes that enforce clean tab discarding (`Ctrl+W` before `Ctrl+O`).

### Rule 4: Coordinate Spaces & Grounding
- When using `element_id` from `desktop_inspect`, IDs are valid for that specific window state.
- When using `desktop_escalate` (Tier 2 image), coordinates can be:
  - **Normalized [0, 1000]**: Set `is_normalized: True` in `coordinates: {"x": 500, "y": 250, "is_normalized": true}`. The harness maps this to the window's physical rect.
  - **Physical Pixels**: Raw screen coordinates matching the physical desktop bounds.

### Rule 5: Terminal Suicide Guard
`core/safety.py` tracks the process tree of the agent and terminal shell.
- Any attempt to send `Alt+F4`, close, or terminate the host terminal PID is classified as `CRITICAL_BLOCKED` and rejected.

---

## 4. App-AST Profile Reference

Profiles are stored as JSON in [`knowledge/apps/`](knowledge/apps/).

### LTspice (`ltspice`)
- **Executable**: `LTspice.exe` (searches PATH, `%LOCALAPPDATA%\Programs\ADI\LTspice`, `ProgramFiles`)
- **States**:
  - `empty_workspace`: No schematic loaded. Available: `open_schematic`.
  - `schematic_open`: `.asc` schematic active. Available: `run_simulation`.
  - `waveform_active`: `.raw` viewer open. Available: `open_trace_picker`.
  - `trace_picker_dialog`: Modal dialog for net/current selection.
- **Verified Recipes**:
  - `open_schematic(path=...)`: Sends `Ctrl+W` (discard tab) $\to$ `Ctrl+O` $\to$ types path $\to$ Enter.
  - `run_simulation()`: Clicks toolbar Run button $\to$ waits for waveform viewer.
  - `open_trace_picker()`: Clicks "Pick Visible Traces".
- **Known Quirks**:
  - `os.startfile` does not load into active running instance; must use `open_schematic` recipe.
  - Avoid LTspice batch mode (`-b`) without GUI context; it may hang indefinitely.

### Microsoft Word (`winword`)
- **Executable**: `winword.exe`
- **States**:
  - `document_active`: Open document ready for editing. Available: `save_document`, `new_blank_document`.
  - `save_dialog`: Modal Save As dialog.
- **Known Quirks**:
  - Word COM API rejects calls (`-2147418111`) during modal dialogs or cell edit mode.

---

## 5. Self-Healing & Friction Tracking

When encountering an unhandled UI state, unresponsive control, or quirk:
1. Log it immediately via `app_record_struggle` (MCP) or inspect with `py -3 harness.py struggles`.
2. Entries are saved to [`knowledge/friction_ledger.json`](knowledge/friction_ledger.json).
3. The Playbook Runner queries this ledger to select known workarounds on subsequent executions.
