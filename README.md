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

## Architecture (Harness 2.0)

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
|  | - Pinned Transaction Runner         |   | - Workaround & Refinement Logging |  |
|  | - Profile Storage (knowledge/apps/) |   | - Dynamic Self-Healing via Ledger |  |
|  +-------------------------------------+   +-----------------------------------+  |
|               |                 |                                  ^              |
|        Channel A (UI)    Channel B (Disk)                    Action Call          |
|               v                 v                                  |              |
|  +-------------------------------------+   +-----------------------------------+  |
|  |       Dual-Channel Observer         |   |      App Lifecycle Broker         |  |
|  |                                     |   | - Shell.Application COM Dispatch  |  |
|  | Tier 1: Local UIA Edge (<35ms)      |   | - ctypes unicode window discovery |  |
|  | Tier 2: Visual Escalation (1280px)  |   | - Interactive session attachment  |  |
|  | Channel B: Artifact Metrics (Regex) |   +-----------------------------------+  |
|  +-------------------------------------+                     |                    |
|                                                              v                    |
|                                            +-----------------------------------+  |
|                                            |      Buffer Synchronization       |  |
|                                            | - Disk sha256 vs GUI window title |  |
|                                            | - Tab invalidation (Ctrl+W reload)|  |
|                                            | - Active working buffer tracking  |  |
|                                            +-----------------------------------+  |
+--------------------------------------------------------------|--------------------+
                                                               v
                                                   Windows Desktop Environment
```

---

## Key Subsystems

### 1. Interactive Application Lifecycle Broker (`core/lifecycle.py`)
- **Interactive Shell COM Dispatch**: Bypasses headless background traps (`Session 0` detachment) by launching target applications through the Windows Shell COM broker (`Shell.Application` $\to$ `ShellExecute`), ensuring processes run on the user's interactive desktop (`winsta0\default`).
- **Robust ctypes Window Discovery**: Discovers running top-level windows using `ctypes.windll.user32.EnumWindows` with unicode buffers, bypassing pywin32 trampolining issues on Python 3.13.
- **Warm-Up Watchdog**: Polls for valid non-zero-sized top-level HWNDs and automatically asserts foreground focus prior to dispatching actions.

### 2. Working Buffer Synchronization Manager (`core/buffer_sync.py`)
- **In-Memory Buffer vs. Disk State**: In native desktop software (e.g. LTspice, text editors, CAD), modifying a file on disk while the GUI has the document open causes silent failures (the application ignores on-disk changes because the tab is already loaded).
- **Active Document Detection**: Inspects active window titles and caption signatures to identify whether the target file is currently displayed in the GUI.
- **Buffer Invalidation Planning**: Computes optimal reload strategies. If a file is dirty on disk and open in the GUI, it executes a clean tab discard (`Ctrl+W`) before triggering the open sequence (`Ctrl+O`).

### 3. Pinned Transaction Runner (`core/playbook_runner.py`)
- **HWND Pinning**: Binds multi-step recipes to specific application window handles.
- **Pre-Event Focus Invariant Guards**: Prior to dispatching every keystroke or click, checks `GetForegroundWindow()` against the pinned `HWND` and re-asserts focus if OS notifications or background tasks caused focus drift.
- **Friction-Driven Self-Healing**: Consults the persistent friction ledger to dynamically apply known workarounds if an intermediate step encounters an unhandled UI state.

### 4. Dual-Channel Observer (`core/dual_observer.py`)
- **Channel A (UI State)**: Tier 1 Edge UIA crawl (<35ms, ~45 tokens) with automated fallback to Tier 2 screenshot capture (1280px Lanczos) when custom canvases have 0 accessibility controls.
- **Channel B (Ground-Truth Artifact Extraction)**: Parses domain output artifacts (simulation `.log` files, netlists, `.csv`, `.raw`) using regex extractors to parse numerical metrics and status flags.
- **Closed-Loop Verification**: Combines both channels so the agent asserts not just *"button was clicked"*, but *"simulation completed with $A_0 = 64.3\text{ dB}$ and $GBW = 15.42\text{ MHz}$"*.

### 5. Struggle & Friction Ledger (`core/struggle_tracker.py`)
A persistent telemetry store (`knowledge/friction_ledger.json`) tracking operational friction points:
- Categorizes failures (`EXECUTION_ERROR`, `STATE_MISMATCH`, `UNRESPONSIVE_MECHANISM`, `AGENT_FRICTION`).
- Deduplicates and tallies hit counts.
- Stores verified workarounds and refinement recommendations for subsequent agent sessions.

### 6. Coordinate & System Safety
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

## Case Studies: Real-World EDA Verification (LTspice)

Complex native desktop software (CAD/EDA/simulation tools) exposes the limits of generic vision-only computer-use agents. In LTspice, the schematic and waveform surfaces are custom GDI/DirectX canvases with zero accessibility nodes, while toolbar buttons are native Win32 controls.

### Case 1: Inverting Buck-Boost DC-DC Converter
```
[Agent Goal] "Synthesize 12V -> -5V Buck-Boost Converter, simulate 5ms startup transient, verify inductor current ripple."
     │
     ├── 1. Generates netlist: outputs/buck_boost.asc (P-MOSFET, Schottky diode, L=47uH, C=100uH)
     ├── 2. Lifecycle Broker: Resolves LTspice.exe via Shell COM and attaches to HWND
     ├── 3. Buffer Sync: Discards stale buffer tab if already open, cleanly reloads on-disk ASC
     ├── 4. Pinned Recipe: Executes open_schematic + run_simulation with focus invariant protection
     └── 5. Dual-Channel Verification: Verifies steady-state V(out) = -4.98V with <50mV ripple in 2.6s
```

### Case 2: Two-Stage Miller OTA Closed-Loop Parameter Optimization
Evaluating automated circuit parameter tuning with dual-channel verification ($A_0$ DC gain and Gain-Bandwidth Product GBW):

```
[Agent Goal] "Design CMOS Miller OTA for target GBW, then dynamically re-tune for a different GBW specification."
     │
     ├── Trial 1 (C_c = 1.0 pF):
     │      ├── Synthesizes schematic outputs/miller_ota.asc with .ac dec 20 1 100Meg and .meas directives
     │      ├── Invokes Pinned Recipe: open_schematic + run_simulation (Execution time: 4.1s)
     │      └── Channel B Verification: Extracted A_0 = 64.35 dB, GBW = 15.42 MHz from outputs/miller_ota.log
     │
     └── Trial 2 (C_c = 4.7 pF - Parameter Retuning):
            ├── Modifies compensation capacitor on disk without human intervention
            ├── BufferSyncManager detects document dirty on disk vs GUI tab; enforces [ctrl, w] buffer discard
            ├── Invokes Pinned Recipe: reloads updated netlist and simulates (Execution time: 2.4s)
            └── Channel B Verification: Extracted A_0 = 64.35 dB, GBW = 3.32 MHz (41.5% speedup vs Trial 1)
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
| `app_execute_recipe` | `app`, `recipe`, `params` | Runs a multi-step App-AST macro recipe pinned to HWND with dual-channel verification. |
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

### Ensure Application is Running (Lifecycle Broker)
```powershell
py -3 harness.py launch ltspice
```

### Check Working Buffer Synchronization (Buffer Sync)
```powershell
py -3 harness.py sync outputs/miller_ota.asc --app ltspice
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

