# CLAUDE.md — Desktop Control Harness Agent Guide

See [AGENTS.md](AGENTS.md) for full architectural guidelines, invariants, and App-AST references.

## Quickstart Commands
```powershell
# 1. Run unit test suite (fast verification, 38 tests, ~5s)
py -3 -m pytest

# 2. Inspect active foreground window (Tier 1 UIA, <35ms)
py -3 harness.py inspect
py -3 harness.py inspect --query "Run"

# 3. Focus / Launch target application via Shell COM Broker
py -3 harness.py launch ltspice

# 4. Query App-AST profiles, states, and verified recipes
py -3 harness.py ast
py -3 harness.py ast --app ltspice

# 5. Execute an App-AST verified recipe
py -3 harness.py recipe ltspice open_schematic --params path=C:/path/circuit.asc
py -3 harness.py recipe ltspice run_simulation

# 6. Check working buffer synchronization (disk vs GUI memory)
py -3 harness.py sync outputs/miller_ota.asc --app ltspice

# 7. Check friction ledger
py -3 harness.py struggles --app ltspice
```

## Golden Rules
1. **Prefer Recipes over Raw Clicks**: Always call `app_execute_recipe` or `harness.py recipe` when an App-AST recipe exists (~35 tokens vs 10k tokens).
2. **Foreground Focus Invariant**: Run `py -3 harness.py launch <app>` before inspecting; `desktop_inspect` inspects the foreground window.
3. **Working Buffer Sync**: Desktop apps (LTspice, Word) do not auto-reload modified files from disk if the tab is open. Use `Ctrl+W` before `Ctrl+O` or run `harness.py sync`.
4. **Normalized Coordinates**: In Tier 2 escalation images (1280px Lanczos), set `is_normalized: True` with `[0, 1000]` coordinates.
5. **Terminal Protection**: Host terminal process tree is protected (`CRITICAL_BLOCKED` on `Alt+F4`).
