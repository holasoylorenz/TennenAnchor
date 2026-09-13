# Desktop Control Harness

A deterministic Windows automation runtime for AI computer-use agents, combining lightweight Win32/UIA perception (<35ms), visual escalation fallbacks, application state machines (App-AST), and closed-loop verification.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-0078D6.svg)](https://microsoft.com/windows)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-42%20passed-brightgreen.svg)](tests/)

---

![LTspice Autonomous Circuit Optimization Demo](assets/demo.gif)

*Autonomous design verification of a Two-Stage CMOS Miller OTA in LTspice XVII: opening the schematic, running AC analysis, plotting Bode magnitude and phase response, and verifying bandwidth metrics ($A_0 = 91.73\text{ dB}$, $GBW = 36.97\text{ MHz}$) against the simulation log.*

---

## Why This Runtime Exists

Standard computer-use agents treat desktop automation as an open-loop cycle of full screenshots and coordinate clicks:

$$\text{Agent} \longrightarrow \text{Screenshot (~700 tokens)} \longrightarrow \text{VLM Inference} \longrightarrow \text{Mouse Click} \longrightarrow \dots$$

When automating native engineering software (CAD, EDA, simulation tools, Office), this pattern breaks down:

- **Context exhaustion**: Serializing full accessibility trees or screenshots consumes 3,000–5,000 tokens every step, running out of context after 10–15 actions.
- **Coordinate and DPI drift**: Per-Monitor DPI scaling (125%, 150%) and multi-monitor layouts cause pixel coordinates to drift from OS input events.
- **Custom canvas blindness**: Schematic surfaces, waveform graphs, and DirectX viewports have zero accessibility nodes, causing pure accessibility crawlers to stall.
- **Stale working buffer traps**: Modifying netlists or source files on disk while document tabs are open in GUI memory leads to silent out-of-sync simulation runs, because native desktop applications do not automatically reload modified files from disk.

`desktop-control-harness` shifts desktop automation from blind coordinate clicking to **state-aware, verified transitions**: observe state, assert preconditions, execute pinned macro recipes, and verify postconditions.

---

## Architecture Overview

```
                      +-----------------------------+
                      |   AI Agent (Claude / AGY)   |
                      +-----------------------------+
                                     |
                          Stdio JSON-RPC 2.0 (MCP)
                                     v
                      +-----------------------------+
                      |     Desktop MCP Server      |
                      |       (mcp_server.py)       |
                      +-----------------------------+
                        /            |            \
                       v             v             v
       +------------------+  +---------------+  +-------------------+
       | Perception Layer |  | App-AST Engine|  | Buffer Sync & ALM |
       | Tier 1: Win32 UIA|  | Macro Recipes |  | Shell COM Broker  |
       | Tier 2: Lanczos  |  | State Machine |  | Invalidation Plan|
       +------------------+  +---------------+  +-------------------+
                       \             |            /
                        v            v           v
                      +-----------------------------+
                      |    Target HWND / Windows    |
                      +-----------------------------+
```

### 1. Dual-Tier Perception
- **Tier 1 (Win32 / UIA)**: Walks the active window's accessibility tree in <35ms, filtering out non-interactive noise and returning labeled control IDs (`#1 [Btn "Run"]`). Uses ~70 tokens per turn.
- **Tier 2 (Visual Escalation)**: Automatically captures a 1280px Lanczos-downscaled screenshot when a window has 0 accessibility controls (e.g. custom canvases).

### 2. Application State Trees (App-AST) & Verified Recipes
Instead of asking an agent to plan 15 individual clicks through menus and file dialogs:
- Applications are modeled with explicit states (`empty_workspace`, `schematic_open`, `waveform_active`) and verified transitions.
- Multi-step procedures (`open_schematic`, `run_simulation`, `plot_trace`) execute as atomic transactions pinned to the target window handle (HWND).
- Cuts multi-step context consumption by **99.9%** (70 tokens vs 48,000 tokens).

### 3. Dual-Channel Verification
The harness verifies task completion through two complementary channels:
- **Channel A (UI Perception)**: Verifies that the application reached the target state (e.g. `waveform_active`).
- **Channel B (Ground-Truth Artifacts)**: Parses output artifacts (`.log`, `.raw`, `.csv`) with domain-specific extractors to assert real engineering constraints (*e.g.* $A_0 > 60\text{ dB}$, $GBW > 10\text{ MHz}$).

### 4. Working Buffer Synchronization & Safety
- **BufferSyncManager**: Hashes on-disk files and inspects window captions. If a file is dirty on disk and already open in memory, it executes a tab discard (`Ctrl+W`) prior to reloading.
- **Modal Dialog Awareness**: Recognizes owned child windows and modal dialogs during pinned transactions, preventing the focus guard from stealing input focus.
- **Terminal Suicide Guard**: Traverses the process tree to block `Alt+F4` or close events targeted at the agent's host terminal.
- **Self-Healing Friction Ledger**: Persists UI quirks and operational errors to `knowledge/friction_ledger.json` for automatic recovery in future runs.

---

## Benchmark Snapshot

Measured on Windows 11 with Per-Monitor v2 DPI awareness ($N=25$ iterations):

| Architecture | Median Latency | Per-Turn Tokens | 15-Step Workflow Tokens |
| :--- | :--- | :--- | :--- |
| **Raw Accessibility Tree** | ~450 ms | ~3,200 tokens | 48,000 tokens |
| **Vision (Full Screenshot)** | ~2,200 ms | ~700 tokens | 10,500 tokens |
| **Harness (Tier 1 UIA)** | **29.6 ms** | **~73 tokens** | **1,050 tokens** |
| **Harness (App-AST Recipe)** | **< 2.5 ms** | **~35 tokens** | **70 tokens (-99.9%)** |

*Detailed statistical distribution, percentiles, and token accounting are documented in [BENCHMARK.md](BENCHMARK.md).*

---

## Quickstart

### Installation
```powershell
git clone https://github.com/holasoylorenz/desktop-control-harness.git
cd desktop-control-harness
py -3 -m pip install -e .
```

### Run Tests
```powershell
py -3 -m pytest
```

### CLI Commands
```powershell
# Inspect active foreground window (<35ms)
py -3 harness.py inspect
py -3 harness.py inspect --query "Run"

# Launch or focus an application via Shell COM Broker
py -3 harness.py launch ltspice

# Inspect App-AST profiles and registered states
py -3 harness.py ast --app ltspice

# Execute an App-AST verified recipe with GIF visual proof recording
py -3 harness.py recipe ltspice open_schematic --params path=outputs/miller_ota.asc --record
py -3 harness.py recipe ltspice run_simulation --record

# Check disk vs GUI buffer synchronization
py -3 harness.py sync outputs/miller_ota.asc --app ltspice

# Record the full end-to-end showcase (used for the demo above)
py -3 scripts/record_showcase.py
```

---

## MCP Server Configuration

To connect the harness to Claude Desktop, Cursor, or Antigravity CLI, add the stdio server to your MCP configuration:

```json
{
  "mcpServers": {
    "desktop-harness": {
      "command": "py",
      "args": [
        "-3",
        "C:\\path\\to\\desktop-control-harness\\mcp_server.py"
      ]
    }
  }
}
```

Available MCP tools:
- `desktop_inspect`: Fast Tier 1 UIA crawl with control labeling.
- `desktop_escalate`: Tier 2 visual fallback (1280px Lanczos screenshot).
- `desktop_act`: Mouse and keyboard actuation by ID or coordinates.
- `desktop_step`: Combined act + settle + inspect in a single turn.
- `app_query`: Query App-AST profiles, states, and recipes.
- `app_execute_recipe`: Pinned HWND macro execution with verification.
- `app_record_struggle`: Log friction and quirks to the persistent ledger.

---

## Documentation

- [AGENTS.md](AGENTS.md) — Operational rules, focus invariants, and CLI-to-MCP mappings for AI computer-use agents.
- [BENCHMARK.md](BENCHMARK.md) — Empirical perception latency distributions and token accumulation benchmarks ($N=25$).
- [WALKTHROUGH.md](WALKTHROUGH.md) — Turn-by-turn trace of autonomous LTspice analog circuit design, simulation, and parameter re-tuning.
- [CLAUDE.md](CLAUDE.md) — Project conventions and subagent reference.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
