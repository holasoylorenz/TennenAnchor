"""
Standalone Desktop Automation CLI Harness.
Allows inspecting the screen, testing actuation, querying App-AST profiles,
reviewing the struggle ledger, and executing multi-step desktop recipes directly from the CLI.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from typing import Any, Dict

from actuation.controller import DesktopController
from core.app_ast import ProfileRegistry
from core.dpi import get_screen_metrics, init_dpi_awareness
from core.playbook_runner import PlaybookRunner
from core.struggle_tracker import StruggleTracker
from perception.edge_parser import EdgeUIAParser
from perception.screenshot_escalator import ScreenshotEscalator

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("desktop_harness")


def cmd_inspect(args: argparse.Namespace) -> None:
    """Inspects active window using Tier 1 Edge AI parser."""
    parser = EdgeUIAParser()
    t0 = time.perf_counter()
    res = parser.parse_active_window(query=args.query)
    dt = (time.perf_counter() - t0) * 1000

    print(f"\n--- Tier 1 Edge Perception (Latency: {dt:.1f}ms) ---")
    print(parser.format_compact_text(res))
    print("--------------------------------------------------\n")


def cmd_escalate(args: argparse.Namespace) -> None:
    """Captures and optimizes a Tier 2 visual screenshot."""
    escalator = ScreenshotEscalator()
    t0 = time.perf_counter()
    res = escalator.capture(target=args.target)
    dt = (time.perf_counter() - t0) * 1000

    print(f"\n--- Tier 2 Visual Escalation (Latency: {dt:.1f}ms) ---")
    if res.get("status") == "ok":
        print("Status: OK")
        print(f"Saved to: {res['image_path']}")
        print(f"Target: {res['target']} | Original Rect: {res['original_rect']}")
        print(f"Scaled Resolution: {res['scaled_size']} (Est. Tokens: ~700)")
    else:
        print(f"Error: {res.get('reason')}")
    print("----------------------------------------------------\n")


def cmd_benchmark(args: argparse.Namespace) -> None:
    """Benchmarks perception and screen capture performance."""
    print("\n--- Benchmarking Desktop Harness ---")
    metrics = get_screen_metrics()
    print(f"Desktop Geometry: {metrics['width']}x{metrics['height']} across {metrics['monitors']} monitor(s)")

    parser = EdgeUIAParser()
    t0 = time.perf_counter()
    res = parser.parse_active_window()
    t_edge = (time.perf_counter() - t0) * 1000
    print(f"Tier 1 (UIA Edge Crawl): {t_edge:.2f}ms (Found {len(res.get('elements', []))} interactive elements)")

    escalator = ScreenshotEscalator()
    t0 = time.perf_counter()
    res_esc = escalator.capture(target="active_window")
    t_esc = (time.perf_counter() - t0) * 1000
    print(f"Tier 2 (Capture + Resize + Compression): {t_esc:.2f}ms")
    print("------------------------------------\n")


def cmd_struggles(args: argparse.Namespace) -> None:
    """Displays struggle & friction ledger report."""
    tracker = StruggleTracker()
    print(tracker.format_report(app=args.app))


def cmd_ast(args: argparse.Namespace) -> None:
    """Displays App-AST states, recipes, and domain hints for registered apps."""
    registry = ProfileRegistry()
    apps = registry.list_apps()

    if not apps:
        print("No App-AST profiles found in knowledge/apps/.")
        return

    if args.app:
        profile = registry.get(args.app)
        if not profile:
            print(f"App profile '{args.app}' not found. Available apps: {', '.join(apps)}")
            return
        print(f"\n=== App-AST Profile: {profile.name} ({profile.app_id}) ===")
        print(f"Executable Patterns: {profile.executable_patterns}")
        print("\n--- States ---")
        for s_id, state in profile.states.items():
            print(f"  * {s_id}: {state.name} - {state.description}")
            print(f"    Available Recipes: {state.available_recipes}")
        print("\n--- Verified Recipes ---")
        for r_id, recipe in profile.recipes.items():
            print(f"  * {r_id}: {recipe.name} ({len(recipe.steps)} steps)")
            print(f"    Params: {recipe.parameters} -> Initial: {recipe.initial_state} -> Final: {recipe.expected_final_state}")
        print("\n--- Domain Hints ---")
        print(json.dumps(profile.domain_hints, indent=2))
        print("=" * 60 + "\n")
    else:
        print(f"\nRegistered App-AST Profiles ({len(apps)}):")
        for a in apps:
            p = registry.get(a)
            if p:
                print(f"  - {p.app_id:12} : {p.name:20} ({len(p.states)} states, {len(p.recipes)} recipes)")
        print("\nUse 'harness.py ast --app <name>' to inspect full AST hierarchy.\n")


def cmd_recipe(args: argparse.Namespace) -> None:
    """Executes a pre-compiled App-AST recipe."""
    registry = ProfileRegistry()
    profile = registry.get(args.app)
    if not profile:
        print(f"Error: App profile '{args.app}' not found.")
        sys.exit(1)

    params: Dict[str, Any] = {}
    if args.params:
        for item in args.params:
            if "=" in item:
                k, v = item.split("=", 1)
                params[k.strip()] = v.strip()

    runner = PlaybookRunner(registry=registry)
    res = runner.execute(profile=profile, recipe_id=args.recipe, params=params)

    print(f"\n--- Recipe Execution Result: {args.recipe} ---")
    print(f"Status          : {res.get('status').upper()}")
    print(f"Steps Completed : {res.get('steps_completed')}/{res.get('total_steps')}")
    print(f"Duration        : {res.get('duration_ms')}ms")
    print(f"Initial State   : {res.get('initial_state')}")
    print(f"Final State     : {res.get('final_state')}")
    if res.get("error"):
        print(f"Error           : {res.get('error')}")
    print("-------------------------------------------\n")


def main() -> None:
    init_dpi_awareness()
    parser = argparse.ArgumentParser(description="Desktop Control Harness CLI")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Inspect
    p_inspect = subparsers.add_parser("inspect", help="Inspect active foreground window")
    p_inspect.add_argument("--query", "-q", type=str, default=None, help="Filter elements by query")

    # Escalate
    p_esc = subparsers.add_parser("escalate", help="Capture visual screenshot (Tier 2)")
    p_esc.add_argument("--target", choices=["active_window", "full_screen"], default="active_window")

    # Benchmark
    subparsers.add_parser("benchmark", help="Benchmark perception and capture latency")

    # Struggles
    p_struggles = subparsers.add_parser("struggles", help="Display struggle & friction ledger report")
    p_struggles.add_argument("--app", "-a", type=str, default=None, help="Filter by application ID (e.g. ltspice)")

    # AST
    p_ast = subparsers.add_parser("ast", help="Query App-AST state graphs and recipes")
    p_ast.add_argument("--app", "-a", type=str, default=None, help="Inspect specific application profile")

    # Recipe
    p_recipe = subparsers.add_parser("recipe", help="Execute an App-AST action recipe")
    p_recipe.add_argument("app", type=str, help="Application ID (e.g. ltspice)")
    p_recipe.add_argument("recipe", type=str, help="Recipe ID (e.g. run_simulation)")
    p_recipe.add_argument("--params", "-p", nargs="*", help="Key=value parameters (e.g. path=file.asc)")

    args = parser.parse_args()

    if args.command == "inspect":
        cmd_inspect(args)
    elif args.command == "escalate":
        cmd_escalate(args)
    elif args.command == "benchmark":
        cmd_benchmark(args)
    elif args.command == "struggles":
        cmd_struggles(args)
    elif args.command == "ast":
        cmd_ast(args)
    elif args.command == "recipe":
        cmd_recipe(args)
    else:
        # Default behavior: run inspect
        args.query = None
        cmd_inspect(args)


if __name__ == "__main__":
    main()
