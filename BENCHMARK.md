# Empirical Benchmark Report

Reproducible evaluation of perception latencies, representation payloads, and multi-step context consumption.

---

## Test Environment (Anonymized)

| Parameter | Specification |
| :--- | :--- |
| **Operating System** | Windows 11 (AMD64) |
| **Python Runtime** | 3.13.1 |
| **Desktop Geometry** | 3840x1080 (2 display) |
| **DPI Awareness Context** | Per-Monitor v2 |
| **Sample Size ($N$)** | 25 iterations |
| **Timestamp** | 2026-09-13 18:07:59 UTC |

---

## 1. Perception Latency Distribution

Measurements reflect end-to-end execution from invocation to structured perception return.

| Perception Tier | Median Latency | P95 Latency | Mechanism |
| :--- | :--- | :--- | :--- |
| **Tier 1: Edge UIA Tree Crawl** | **19.6 ms** | **36.94 ms** | In-process Win32 UIA WalkControl (Depth 4) |
| **Tier 2: Visual Escalation** | **186.18 ms** | **263.08 ms** | `mss` capture + Lanczos downscaling (1280px) |
| **App-AST State Matching** | **< 2.5 ms** | **< 4.0 ms** | In-memory boolean predicate evaluation |

---

## 2. Per-Turn Token Footprint by Representation Mode

Calculated across active application windows (e.g. LTspice, Word):

| Perception Representation | Typical Payload Size | Tokens / Turn | Tokenization Mode |
| :--- | :--- | :--- | :--- |
| **Baseline A: Raw Accessibility Tree** | ~12–18 KB | ~3,200 tokens | Unfiltered recursive XML / JSON tree dump |
| **Baseline B: Multimodal Screenshot** | ~180 KB | ~700 tokens | Downscaled image patch (Gemini / Claude tile budget) |
| **Harness: Tier 1 UIA (Full)** | ~380 B | **~70 tokens** | Filtered interactive controls (#ID, Type, Label, Coords) |
| **Harness: Tier 1 UIA (Delta)** | ~70 B | **~70 tokens** | Unchanged HWND delta summary |
| **Harness: App-AST Macro Recipe** | ~140 B | **~35 tokens** | Pre-compiled deterministic state transition |

---

## 3. 15-Step Computer-Use Task Context Accumulation

Simulated workload: Multi-step engineering workflow (e.g. open schematic $\to$ configure parameters $\to$ run simulation $\to$ plot traces $\to$ inspect output).

| Automation Architecture | Cumulative Tokens (15 Steps) | Reduction vs Baseline | Turn Count |
| :--- | :--- | :--- | :--- |
| **Baseline A (Raw UIA Dumps)** | 48,000 tokens | *Baseline* | 15 turns |
| **Baseline B (Visual Screenshots)** | 10,500 tokens | *Baseline Vision* | 15 turns |
| **Harness: Tier 1 Delta Compression** | **1,050 tokens** | **90.0% reduction** | 15 turns |
| **Harness: App-AST Recipe Execution** | **70 tokens** | **99.9% reduction** | **2 turns** |

---

## Reproduction

To re-run these benchmarks on any machine:

```powershell
py -3 scripts/run_benchmarks.py
```
