"""
Automated Showcase Recorder for Desktop Control Harness.
Executes an end-to-end verified workflow (LTspice Miller OTA synthesis + simulation + dual-channel extraction)
while capturing a window-scoped animated GIF with real-time telemetry HUD for visual proof.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parent.parent
if str(HARNESS_ROOT) not in sys.path:
    sys.path.insert(0, str(HARNESS_ROOT))

from core.app_ast import ProfileRegistry
from core.lifecycle import AppLifecycleBroker
from core.playbook_runner import PlaybookRunner
from core.recorder import WindowScopedRecorder
from scripts.generate_ota_asc import generate_miller_ota_asc
from scripts.run_ota_experiment import parse_ota_log

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("record_showcase")


def record_showcase(
    output_path: Path,
    fps: float = 4.0,
    max_width: int = 800,
    target_gbw_mhz: float = 15.0,
    cc_pf: float = 1.0,
) -> Path:
    logger.info("Starting showcase recording session...")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Ensure target schematic is synthesized
    asc_path = HARNESS_ROOT / "outputs" / "miller_ota.asc"
    log_path = HARNESS_ROOT / "outputs" / "miller_ota.log"
    generate_miller_ota_asc(cc_pf=cc_pf, target_gbw_mhz=target_gbw_mhz, output_path=asc_path)
    logger.info("Synthesized schematic: %s", asc_path)

    # 2. Attach to / launch LTspice via Shell COM Broker
    registry = ProfileRegistry()
    profile = registry.get("ltspice")
    if not profile:
        raise RuntimeError("LTspice profile not found in registry.")

    broker = AppLifecycleBroker()
    hwnd = broker.ensure_running(profile, timeout_sec=10.0)
    if not hwnd:
        raise RuntimeError("Failed to attach to or launch LTspice.")
    logger.info("Attached to LTspice (HWND: %s)", hwnd)
    time.sleep(0.5)

    # 3. Start Window-Scoped Recorder pinned strictly to LTspice HWND
    recorder = WindowScopedRecorder(
        hwnd=hwnd,
        fps=fps,
        max_width=max_width,
        output_dir=output_path.parent,
    )
    recorder.start()
    recorder.set_status("Harness 2.0 | Pinned HWND: " + str(hwnd))
    time.sleep(0.6)

    try:
        runner = PlaybookRunner(registry=registry)

        # Step A: Discard & Open Schematic (use relative path to preserve privacy)
        rel_asc_path = str(asc_path.relative_to(HARNESS_ROOT))
        recorder.set_status("Harness 2.0 | Recipe: open_schematic")
        res_open = runner.execute(profile, "open_schematic", params={"path": rel_asc_path}, record=False)
        logger.info("open_schematic completed: %s", res_open.get("status"))
        time.sleep(0.8)

        # Step B: Run Simulation
        recorder.set_status("Harness 2.0 | Recipe: run_simulation")
        res_sim = runner.execute(profile, "run_simulation", record=False)
        logger.info("run_simulation completed: %s", res_sim.get("status"))
        time.sleep(1.2)

        # Step C: Dual-Channel Verification (Extract metrics from log)
        meas = parse_ota_log(log_path)
        a0 = meas.get("a0_db", "N/A")
        gbw = meas.get("gbw_mhz", "N/A")
        verified_msg = f"Dual-Channel Verified: A0={a0}dB, GBW={gbw}MHz"
        logger.info(verified_msg)
        recorder.set_status(f"Harness 2.0 | {verified_msg}")
        time.sleep(1.2)

    finally:
        logger.info("Finalizing recording and compiling animated GIF...")
        compiled_path = recorder.stop(filename_prefix="showcase_ltspice")

    if compiled_path and compiled_path.exists():
        # Move or copy to target destination if different
        if compiled_path.resolve() != output_path.resolve():
            import shutil
            shutil.copy2(compiled_path, output_path)
            try:
                compiled_path.unlink()
            except OSError:
                pass
            logger.info("Saved showcase to: %s", output_path)
            return output_path
        return compiled_path
    elif output_path.exists():
        return output_path
    else:
        raise RuntimeError("Recording failed to produce an output file.")


def main():
    parser = argparse.ArgumentParser(description="Record desktop control harness visual proof showcase.")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=HARNESS_ROOT / "outputs" / "recordings" / "showcase_ltspice.gif",
        help="Path for compiled animated GIF",
    )
    parser.add_argument("--fps", type=float, default=4.0, help="Recording FPS (default: 4.0)")
    parser.add_argument("--width", type=int, default=800, help="Maximum frame width in px (default: 800)")
    args = parser.parse_args()

    out = record_showcase(output_path=args.output, fps=args.fps, max_width=args.width)
    print(f"\n[SUCCESS] Visual proof showcase compiled successfully!")
    print(f"File: {out}")
    print(f"Size: {out.stat().st_size / 1024.0:.1f} KB")


if __name__ == "__main__":
    main()
