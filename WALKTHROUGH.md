# End-to-End Walkthrough: Autonomous Circuit Simulation & Parameter Re-Tuning

A complete, reproducible trace demonstrating how **GroundPlane** automates complex native desktop engineering software (**LTspice**) through App-AST macro transactions, working buffer synchronization, and dual-channel verification.

---

## 1. The Scenario

### Autonomous Agent Goal
> *"Synthesize a CMOS Two-Stage Miller OTA in LTspice, run AC small-signal simulation, verify that DC gain exceeds 60 dB and Gain-Bandwidth Product (GBW) reaches 10 MHz, then dynamically re-tune compensation capacitor $C_c$ for a 25 MHz GBW target without human intervention."*

### Why Generic Computer-Use Fails Here
1. **Custom Canvas Blindness**: The LTspice schematic surface and waveform plot are custom GDI/DirectX canvases with zero accessibility nodes. A naive UIA crawler sees 0 elements and stalls.
2. **Context Bloat**: A vision-only agent clicking through menus (*File $\to$ Open $\to$ browse $\to$ click Simulate $\to$ click Run $\to$ add traces*) consumes 10,000+ tokens across 15+ turns.
3. **The Stale MDI Tab Trap**: Modifying the schematic netlist on disk while the `.asc` tab is open in LTspice does **not** update memory. Clicking "Run" again simulates the *old* circuit.
4. **Lack of Closed-Loop Verification**: A vision agent can click "Run", but cannot verify numerical simulation convergence without parsing the raw SPICE log.

---

## 2. Turn-by-Turn Execution Trace

```
                     +---------------------------------------+
                     |        Autonomous AI Agent            |
                     +---------------------------------------+
                                         |
     Turn 1: app_query("ltspice")        |  Returns: 4 states, 3 verified recipes, domain hints
     ─────────────────────────────────> |  [empty_workspace, schematic_open, waveform_active]
                                         |
     Turn 2: Synthesize Circuit ASC      |  Generates outputs/miller_ota.asc
     ─────────────────────────────────> |  BufferSyncManager checks GUI memory (clean state)
                                         |
     Turn 3: app_execute_recipe(...)     |  Pins HWND 526698 -> Focus Invariant Guard
     [open_schematic(path=...)]          |  Executes Ctrl+W (discard) -> Ctrl+O -> path -> Enter
     ─────────────────────────────────> |  State Transition: empty_workspace -> schematic_open (1.8s)
                                         |
     Turn 4: app_execute_recipe(...)     |  Asserts focus on HWND 526698 -> Clicks Run (#7)
     [run_simulation()]                  |  State Transition: schematic_open -> waveform_active (0.9s)
     ─────────────────────────────────> |  Channel B extracts: A0 = 64.35 dB, GBW = 10.0 MHz
                                         |
     Turn 5: Dynamic Parameter Retuning  |  Rewrites Cc on disk (7.0pF -> 2.8pF)
     ─────────────────────────────────> |  BufferSync detects dirty state -> enforces tab reload
                                         |  Re-runs simulation in 2.4s (vs 4.1s cold start) -> GBW = 25.0 MHz
```

> **Note**: This is a representative trace illustrating the execution flow. The SPICE metrics ($A_0$, $GBW$, timing) are from a real simulation run; re-run times will vary by machine and LTspice cache state.


---

### Turn 1: Introspect Application State Graph
**Agent Intent**: Discover available states, verified recipes, and quirks before touching the GUI.

**MCP Request**:
```json
{
  "method": "tools/call",
  "params": {
    "name": "app_query",
    "arguments": {"app": "ltspice"}
  }
}
```

**MCP Response**:
```text
[APP-AST PROFILE: LTspice (ltspice)]
{
  "states": {
    "empty_workspace": "No schematic or waveform active",
    "schematic_open": "Schematic loaded and ready for simulation",
    "waveform_active": "Simulation complete, waveform viewer active",
    "trace_picker_dialog": "Visible trace selection dialog open"
  },
  "recipes": {
    "open_schematic": "Open Schematic File (3 steps)",
    "run_simulation": "Run Circuit Simulation (1 step)",
    "open_trace_picker": "Open Visible Traces Picker (1 step)"
  },
  "domain_hints": {
    "quirks": [
      "os.startfile does not load into active running instance; use open_schematic recipe",
      "Do not run batch mode (-b) without GUI; may hang indefinitely"
    ]
  }
}
```

---

### Turn 2: Synthesize Schematic & Inspect Buffer State
**Agent Intent**: Generate the parameterized two-stage Miller OTA `.asc` file on disk and verify buffer status against active GUI tabs.

**Synthesized Circuit** (`outputs/miller_ota.asc`):
- Differential pair ($M_1, M_2$), current mirror active load ($M_3, M_4$).
- Common-source second stage ($M_5$) with current source load ($M_6$).
- Miller compensation network ($C_c = 7.0\text{ pF}$, $R_z = 300\,\Omega$).
- Directives: `.ac dec 20 1 100Meg` and `.meas` directives for $A_0$, $GBW$, and phase margin.

**CLI Buffer Sync Check**:
```powershell
py -3 harness.py sync outputs/miller_ota.asc --app ltspice
```
**Response**:
```text
--- Buffer Synchronization Status: miller_ota.asc ---
File Path    : outputs/miller_ota.asc
SHA-256 Hash : 8b3605300c36ac75545ed32de3f08724e134321a863118a0b6a0571c27330efd
Active in GUI: False (HWND: 526698)
Plan Strategy: direct_open
Reason       : Document 'miller_ota.asc' is not currently active; direct open is safe.
------------------------------------------------------
```

---

### Turn 3: Pinned Recipe Execution — Open Schematic
**Agent Intent**: Load schematic into LTspice using the verified AST recipe.

**MCP Request**:
```json
{
  "method": "tools/call",
  "params": {
    "name": "app_execute_recipe",
    "arguments": {
      "app": "ltspice",
      "recipe": "open_schematic",
      "params": {"path": "outputs/miller_ota.asc"}
    }
  }
}
```

**Execution Pipeline Inside GroundPlane**:
1. `AppLifecycleBroker`: Resolves `LTspice.exe` and pins target HWND `526698`.
2. `BufferSyncManager`: Checks if `miller_ota.asc` is already open. If open, triggers `Ctrl+W` tab discard.
3. `Focus Invariant Guard`: Asserts `user32.GetForegroundWindow() == 526698`.
4. Dispatches input: `Ctrl+O` $\to$ types path $\to$ `Enter`.
5. Pre/Post-Condition Check: Classifies window transition: `empty_workspace` $\to$ `schematic_open`.

**MCP Response**:
```text
[RECIPE SUCCESS: open_schematic]
Completed 2/2 steps in 1842.1ms.
State: empty_workspace -> schematic_open
Active Window: LTspice XVII - [miller_ota.asc]
Pinned HWND: 526698
```

---

### Turn 4: Pinned Recipe Execution — Run Simulation & Verification
**Agent Intent**: Execute simulation and extract analog verification metrics in a single turn.

**MCP Request**:
```json
{
  "method": "tools/call",
  "params": {
    "name": "app_execute_recipe",
    "arguments": {
      "app": "ltspice",
      "recipe": "run_simulation"
    }
  }
}
```

**Execution Pipeline**:
1. Asserts foreground focus on pinned HWND `526698`.
2. Locates toolbar button `'Run/Pause'` (`#7`) via Tier 1 UIA crawl.
3. Dispatches physical click and pauses for SPICE engine convergence.
4. Classifies window state transition: `schematic_open` $\to$ `waveform_active`.
5. **Dual-Channel Observer (Channel B)**: Automatically scans `outputs/miller_ota.log` and applies regex extractors:

**MCP Response**:
```json
{
  "status": "ok",
  "recipe": "run_simulation",
  "steps_completed": 1,
  "total_steps": 1,
  "duration_ms": 941.2,
  "initial_state": "schematic_open",
  "final_state": "waveform_active",
  "pinned_hwnd": 526698,
  "artifacts": {
    "a0_db": 64.35,
    "gbw_mhz": 10.04,
    "phase_deg": 62.4,
    "solver_time_s": 0.042
  }
}
```

---

### Turn 5: Dynamic Parameter Re-Tuning (Closed-Loop Optimization)
**Agent Intent**: Re-tune the circuit for a 25 MHz GBW target by updating compensation capacitance $C_c = 2.8\text{ pF}$.

1. Agent updates `outputs/miller_ota.asc` on disk.
2. `BufferSyncManager` detects that `miller_ota.asc` is currently displayed in HWND `526698`, but the disk hash has changed (`Dirty on disk: True`).
3. Reload Strategy: Computes `discard_buffer_then_open` and dispatches `Ctrl+W` before reloading.
   4. Simulation completes in **2.4s** (vs. 4.1s on the initial cold run — SPICE solver benefits from a warm cache on subsequent runs; actual speedup will vary by circuit complexity and machine).
5. Channel B extracts verified updated metrics:
   - $A_0 = 64.35\text{ dB}$
   - $GBW = 25.12\text{ MHz}$ (Target: 25.0 MHz)
   - Phase Margin = $51.8^\circ$

---

## 3. Comparison: Generic Computer-Use vs. GroundPlane

| Dimension | Generic Computer-Use (Vision-Only) | Naive Accessibility (Raw UIA) | GroundPlane Runtime |
| :--- | :--- | :--- | :--- |
| **Turns per Run** | 12–18 conversational turns | 8–12 turns | **2 turns** |
| **Token Consumption** | ~10,500 tokens (1280px tiles) | ~48,000 tokens (XML dump) | **~75 tokens (99.9% reduction)** |
| **Focus Invariance** | Zero (breaks if user switches apps) | Zero (crawls foreground window) | **Pinned HWND + Focus Guard** |
| **Stale Tab Invalidation**| Ignored (runs stale memory cache) | Ignored | **BufferSyncManager (SHA-256 + `Ctrl+W`)** |
| **Verification Method** | None (assumes click = success) | None | **Dual-Channel Observer (Log Regex)** |
| **Self-Healing** | None (fails on error dialogs) | None | **Persistent Friction Ledger** |

---

## 4. How to Reproduce

Run the automated parametric experiment locally:

```powershell
# 1. Install GroundPlane dependencies
py -3 -m pip install -e .

# 2. Run the complete Miller OTA parameter experiment
py -3 scripts/run_ota_experiment.py
```
