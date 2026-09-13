# desktop-control-harness

A stateful execution and verification runtime for AI computer-use agents on Windows.

---

## Overview

Most computer-use systems treat desktop control as an open-loop sequence of raw perception and mouse clicks:

$$\text{Agent} \longrightarrow \text{Screenshot} \longrightarrow \text{Vision/Reasoning} \longrightarrow \text{Raw Click} \longrightarrow \text{Screenshot} \longrightarrow \dots$$

In native Windows environments with complex desktop software, this pattern breaks down quickly:
1. **Context Bloat**: Serializing raw UI Automation trees or full screenshots consumes 3,000–5,000 tokens per turn, exhausting agent context in 10–15 steps.
2. **Display & Coordinate Drift**: Per-Monitor DPI scaling (125%, 150%) and multi-monitor setups cause severe drift between screenshot pixels and OS mouse events.
3. **Canvas Blindness**: Custom-rendered GUIs (EDA tools, DirectX, Electron canvas) lack accessibility DOMs, causing pure UIA crawlers to stall.
4. **Lack of Invariants & Verification**: Blind coordinate clicks have no semantic security boundary, no preconditions, and no deterministic verification of state transitions.

`desktop-control-harness` shifts the paradigm from **"click coordinate and hope"** to **"observe state $\to$ execute verified transition $\to$ verify postcondition"**, combining an in-process UIA crawler with visual escalation fallback, an Application State Tree (App-AST) intermediate representation, and an operational friction ledger.

---

## Architecture

```
+-----------------------------------------------------------------------------------+
|                           AI Agent / Client (e.g. AGY CLI)                        |
+-----------------------------------------------------------------------------------+
                                         |
                        Stdio JSON-RPC 2.0 Protocol Stream
                                         v
+-----------------------------------------------------------------------------------+
|                        Desktop MCP Server (mcp_server.py)                         |
|                                                                                   |
|  +-------------------------------------+   +-----------------------------------+  |
|  |     App-AST & Playbook Engine       |   |    Struggle & Friction Ledger     |  |
|  | - State Predicate Matching (<15ms)  |   | - Action Error & Retry Telemetry  |  |
|  | - 1-Turn Macro Recipe Execution    |   | - Workaround & Refinement Logging |  |
|  | - Profile Storage (knowledge/apps/) |   | - CLI Gap Analysis (harness.py)   |  |
|  +-------------------------------------+   +-----------------------------------+  |
|               |                                                ^                  |
|        Perception Call                                   Action Call              |
|               v                                                |                  |
|  +---------------------------+               +---------------------------------+  |
|  |    Dual-Tier Perception   |               |     Unified Actuation Engine    |  |
|  |                           |               |                                 |  |
|  | Tier 1: Local UIA Edge    |   Escalate    | - Per-Monitor v2 DPI Transform  |  |
|  | - 2.0s Threaded Timeout   | ------------> | - Win32 Thread Input Attachment |  |
|  | - Delta State Compression |  (Fallback)   | - AGY Terminal Suicide Guard    |  |
|  | - ~45 Tokens / Inspection |               | - Caught FailSafe Recovery      |  |
|  |                           |               |                                 |  |
|  | Tier 2: Visual Escalation |               |                                 |  |
|  | - Max 1280px Lanczos PNG  |               |                                 |  |
|  | - Physical Rect Transform |               |                                 |  |
|  +---------------------------+               +---------------------------------+  |
+----------------------------------------------------------------|------------------+
                                                                 v
                                                     Windows Desktop Environment
```

---

## Key Subsystems

### 1. Dual-Tier Perception
- **Tier 1 (Edge AI UIA Crawl)**: Inspects the active foreground window in `<35ms` with a 2.0s threaded watchdog. Extracts interactive controls (`Button`, `Edit`, `MenuItem`, `ComboBox`, `TabItem`, `CheckBox`) and formats them into an ultra-compact string (~45 tokens) with smart delta compression across consecutive turns.
- **Tier 2 (Visual Escalation Fallback)**: Automatically triggers when Tier 1 detects 0 controls (e.g. custom canvases, games) or times out. Captures a physical multi-monitor screenshot via `mss`, resizes it preserving aspect ratio (max dimension 1280px) via Lanczos filtering, and emits coordinate mapping metadata for vision grounding.

### 2. Application State Tree (App-AST)
Models applications as directed graphs of UI states and transitions:
- **State Nodes**: Detected via boolean predicates over window titles, active control signatures, and element count bounds.
- **Verified Recipes**: Multi-step action macros (e.g. `open_schematic`, `run_simulation`, `plot_traces`) executed deterministically in a single conversational turn, reducing token consumption by up to 80%.
- **Pre-Seeded Profiles**: Ships with verified profiles for **LTspice** and **Microsoft Word** in `knowledge/apps/`.

### 3. Struggle & Friction Ledger
A persistent telemetry store (`knowledge/friction_ledger.json`) tracking operational friction points:
- Categorizes failures (`EXECUTION_ERROR`, `STATE_MISMATCH`, `UNRESPONSIVE_MECHANISM`, `AGENT_FRICTION`).
- Deduplicates and tallies hit counts.
- Stores verified workarounds and refinement recommendations for subsequent agent sessions.

### 4. Coordinate & System Safety
- **Per-Monitor v2 DPI Awareness**: Normalizes physical screen capture and PyAutoGUI cursor positioning across scaled displays (100% to 200%).
- **Interactive Desktop Binding**: Uses `OpenInputDesktop` and `SetThreadDesktop` to ensure background workers operate inside the user's interactive session.
- **Terminal Suicide Guard**: Inspects process trees to block accidental closing (`Alt+F4` or click) of the agent's host terminal.

---

## Empirical Benchmark & Performance

To substantiate performance claims with reproducible data, the harness includes a multi-sample statistical benchmark suite directly executable via CLI:

```powershell
py -3 harness.py benchmark --samples 25
```

### Measured Perception Latency Distribution ($N=25$)

| Perception Tier | Median Latency | P95 Latency | Mechanism | Per-Turn Tokens |
| :--- | :--- | :--- | :--- | :--- |
| **Tier 1: UIA Edge (Full)** | **29.6 ms** | **35.4 ms** | In-process Win32 UIA WalkControl (Depth 4) | ~70 tokens |
| **Tier 1: UIA Edge (Delta)** | **15.2 ms** | **22.4 ms** | In-process HWND delta cache | ~15 tokens |
| **Tier 2: Visual Escalation** | **187.1 ms** | **261.7 ms** | Physical multi-monitor capture (`mss`) + Lanczos (1280px) | ~700 tokens |
| **App-AST Recipe Execution** | **< 2.5 ms** | **< 4.0 ms** | Deterministic in-memory state transition | ~35 tokens |

### 15-Step Computer-Use Context Accumulation

Workload simulation: Multi-step engineering workflow (e.g. open schematic $\to$ configure parameters $\to$ run simulation $\to$ plot traces $\to$ inspect output).

| Automation Architecture | Cumulative Tokens (15 Steps) | Reduction vs Baseline | Agent Turns |
| :--- | :--- | :--- | :--- |
| **Baseline A: Raw Accessibility Tree** | 48,000 tokens | *Baseline* | 15 turns |
| **Baseline B: Multimodal Vision** | 10,500 tokens | *Baseline Vision* | 15 turns |
| **Harness: Tier 1 Delta Compression** | **1,050 tokens** | **90.0% reduction** | 15 turns |
| **Harness: App-AST Macro Recipes** | **70 tokens** | **99.9% reduction** | **2 turns** |

*Hardware context: Windows 11 (AMD64), Per-Monitor v2 DPI awareness, dual-monitor desktop (3840x1080). Detailed methodology and statistical distribution in [BENCHMARK.md](BENCHMARK.md).*

---

## Case Study: Automating Engineering Software (LTspice)

Complex native desktop software (CAD/EDA/simulation tools) exposes the limits of generic vision-only computer-use agents. In LTspice, the schematic and waveform surfaces are custom GDI/DirectX canvases with zero accessibility nodes, while toolbar buttons are native Win32 controls.

`desktop-control-harness` executes the complete engineering workflow:

```
[Agent Goal] "Simulate amplifier circuit, plot waveforms, and measure -3dB bandwidth."
     │
     ├── 1. Generates netlist / schematic: outputs/amplifier.asc (Version 4, SHEET, WIRE, SYMBOL)
     ├── 2. Invokes App-AST Recipe: open_schematic(path="outputs/amplifier.asc")
     │      └─ In-app Ctrl+O sequence bypassing OS shell routing (discovered via friction ledger)
     ├── 3. Invokes App-AST Recipe: run_simulation()
     │      └─ Clicks Run/Pause (#7) and verifies transition to waveform_active state
     ├── 4. Invokes App-AST Recipe: open_trace_picker() + Selects V(out), V(in)
     │      └─ Renders dual waveforms in 2 turns instead of 15 manual steps
     └── 5. Verifies Output & Measurement: f_-3dB = 1.73 MHz
```

---

## Action Risk & Semantic Security Boundary

Generic desktop MCP servers expose unrestricted raw mouse and keyboard primitives (`mouse_click`, `type_text`, `press_key`), which effectively cede unconstrained control of the host machine to the caller.

`desktop-control-harness` elevates the **semantic action itself** to the security boundary. By invoking verified App-AST recipes (`app_execute_recipe`) instead of raw pixel clicks:
* **Preconditions & Postconditions**: The runtime asserts application state predicates before and after transitions.
* **Process Tree Isolation**: Actions are bound strictly to target application HWNDs, preventing coordinate clicks from slipping onto background windows or the host agent terminal.
* **4-Tier Classification**: Every action is classified and checked prior to dispatch:

| Risk Level | Actions | Side-Effect Profile | Enforcement Policy |
| :--- | :--- | :--- | :--- |
| **`READ`** | `inspect`, `screenshot`, `query`, `ast`, `struggles` | Zero side-effects. Safe to run unconditionally. | Automatically permitted |
| **`LOW_RISK_WRITE`** | `click`, `move`, `scroll`, `type`, `press_key` | Standard UI interactions within foreground window. | Permitted with bounds checking |
| **`HIGH_RISK_WRITE`** | `hotkey`, `close`, `drag`, `execute`, `recipe` | State-modifying, file-altering, or composite procedures. | Pre-validated against AST invariants |
| **`CRITICAL_BLOCKED`** | Host terminal closure, `Alt+F4` on agent process, `Ctrl+Alt+Del` | Fatal disruption or host agent termination. | **Hard blocked by process tree guard** |


---

## MCP Server Tools

The MCP server adheres strictly to stdio JSON-RPC 2.0 with stream isolation (all logging routed to `stderr`):

| Tool | Parameters | Description |
| :--- | :--- | :--- |
| `desktop_inspect` | `query`, `mode` (`summary`, `find`, `all`) | Fast Tier 1 edge perception. Returns active window controls and assigned `#ID`s. |
| `desktop_escalate` | `target` (`active_window`, `full_screen`) | Tier 2 visual fallback. Captures downscaled screenshot with coordinate mapping. |
| `desktop_act` | `action`, `element_id`, `coordinates`, `text`, `keys`, `key` | Unified mouse/keyboard actuation by `#ID` or physical/normalized coordinates. |
| `desktop_step` | `action`, `element_id`, `text`, `keys`, `wait_ms` | Composite turn: Acts + Waits for UI + Returns post-state in 1 turn (~35 tokens). |
| `app_query` | `app` | Inspects App-AST profile, state hierarchy, verified recipes, and logged struggles. |
| `app_execute_recipe` | `app`, `recipe`, `params` | Runs a multi-step App-AST macro recipe in a single turn with condition verification. |
| `app_record_struggle`| `app`, `action`, `symptom`, `resolution`, `refinement` | Persists an operational friction point or quirk for agent self-refinement. |

---

## CLI Usage

### Benchmark System Latency
```powershell
py -3 harness.py benchmark
```

### Inspect Active Window
```powershell
py -3 harness.py inspect
# Filter controls by name:
py -3 harness.py inspect --query "Run"
```

### Query App-AST Profiles
```powershell
py -3 harness.py ast
# Inspect specific profile (e.g. LTspice):
py -3 harness.py ast --app ltspice
```

### Review Friction & Struggle Ledger
```powershell
py -3 harness.py struggles
# Filter by application:
py -3 harness.py struggles --app ltspice
```

### Execute a Verified Recipe
```powershell
py -3 harness.py recipe ltspice open_schematic --params path=C:/circuits/amp.asc
```

---

## Installation & Setup

### Requirements
- Windows 10 / 11
- Python 3.10+
- Administrative privileges recommended for interactive desktop attachment

### Installation
```powershell
git clone https://github.com/holasoylorenz/desktop-control-harness.git
cd desktop-control-harness
py -3 -m pip install -e .
```

### Run Test Suite
```powershell
py -3 -m pytest -v
```

---

## MCP Registration

To enable native tool use in AGY CLI (Gemini), add the following entry to `~/.gemini/config/mcp_config.json`:

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

---

## Development Note

This project was developed through **human-in-the-loop "vibe coding"** (AI-assisted rapid systems engineering). Systems architecture, safety invariants, and domain workflows (such as EDA / LTspice circuit simulation and waveform extraction) were directed by human engineering design, while code implementation, Win32 API bindings, and test suites were accelerated using AI pair programming and rigorously verified through deterministic tests and empirical benchmarks.

---

## License

MIT License. See [LICENSE](LICENSE) for details.

