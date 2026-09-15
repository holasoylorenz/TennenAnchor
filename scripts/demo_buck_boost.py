"""
Autonomous Buck-Boost Converter Demonstration & Verification in LTspice.

Synthesizes an Inverting Buck-Boost DC-DC Converter schematic:
- Input: +12.0 V DC
- Switching Frequency: 100 kHz (PWM controlled)
- Continuous Conduction Mode (CCM)
- Regulates to -12.0 V DC into a 20 Ohm load (7.2 W output)
- Simulates in LTspice and verifies Vout, ripple, peak inductor current, and efficiency.
"""

from __future__ import annotations

import logging
from pathlib import Path
import re
import sys
import time

HARNESS_ROOT = Path(__file__).resolve().parent.parent
if str(HARNESS_ROOT) not in sys.path:
    sys.path.insert(0, str(HARNESS_ROOT))

from core.circuit_builder import build_buck_boost_schematic
from core.app_ast import ProfileRegistry
from core.lifecycle import AppLifecycleBroker
from core.playbook_runner import PlaybookRunner

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("demo_buck_boost")


def run_buck_boost_demo(
    vin_v: float = 12.0,
    duty_cycle: float = 0.50,
    f_sw_khz: float = 100.0,
    l_uh: float = 100.0,
    c_uf: float = 47.0,
    r_load_ohm: float = 20.0,
) -> dict:
    output_dir = HARNESS_ROOT / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    asc_path = output_dir / "buck_boost.asc"
    log_path = output_dir / "buck_boost.log"

    print("\n=======================================================")
    print("      TENNENANCHOR BUCK-BOOST SYNTHESIS & VERIFY      ")
    print("=======================================================")
    print(f"  Topology       : Inverting Buck-Boost DC-DC Converter")
    print(f"  Input Voltage  : {vin_v:.1f} V DC")
    print(f"  Duty Cycle (D) : {duty_cycle*100:.1f}%")
    print(f"  Switching Freq : {f_sw_khz:.0f} kHz")
    print(f"  Inductor (L1)  : {l_uh:.0f} uH")
    print(f"  Output Cap (C1): {c_uf:.0f} uF")
    print(f"  Load (Rload)   : {r_load_ohm:.0f} Ohm")
    v_ideal = -vin_v * (duty_cycle / (1.0 - duty_cycle))
    print(f"  Theoretical Vo : {v_ideal:.2f} V")
    print("=======================================================\n")

    # 1. Synthesize schematic
    logger.info("Synthesizing schematic to %s...", asc_path)
    sch = build_buck_boost_schematic(
        vin_v=vin_v,
        duty_cycle=duty_cycle,
        f_sw_khz=f_sw_khz,
        l_uh=l_uh,
        c_uf=c_uf,
        r_load_ohm=r_load_ohm,
        t_sim_ms=2.0,
    )
    sch.save(asc_path)
    logger.info("Schematic generated successfully (%d bytes).", asc_path.stat().st_size)

    # 2. Attach to LTspice via TennenAnchor
    logger.info("Attaching to LTspice via AppLifecycleBroker...")
    registry = ProfileRegistry()
    profile = registry.get("ltspice")
    if not profile:
        raise RuntimeError("LTspice profile not found.")

    broker = AppLifecycleBroker()
    hwnd = broker.ensure_running(profile)
    if not hwnd:
        raise RuntimeError("Failed to launch or attach to LTspice.")
    logger.info("LTspice ready with HWND %s", hwnd)

    # 3. Execute open_schematic recipe
    runner = PlaybookRunner(registry=registry)

    logger.info("Executing App-AST recipe: open_schematic...")
    res_open = runner.execute(profile, "open_schematic", params={"path": str(asc_path.resolve())})
    if res_open.get("status") != "ok":
        raise RuntimeError(f"Failed to open schematic: {res_open.get('error')}")
    logger.info("Schematic loaded in %.1f ms.", res_open.get("duration_ms", 0.0))

    # 4. Execute run_simulation recipe
    logger.info("Executing App-AST recipe: run_simulation...")
    res_sim = runner.execute(profile, "run_simulation")
    if res_sim.get("status") != "ok":
        raise RuntimeError(f"Simulation failed: {res_sim.get('error')}")
    logger.info("Simulation completed in %.1f ms.", res_sim.get("duration_ms", 0.0))

    # Allow disk flush for log file
    time.sleep(0.5)

    # 5. Dual-Channel Verification: Parse simulation log
    metrics = {}
    if log_path.exists():
        log_text = log_path.read_text(encoding="utf-8", errors="ignore")
        for line in log_text.splitlines():
            # Match .meas statements
            m = re.match(r"^\s*([a-zA-Z0-9_]+):\s+.*?=\s*([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)", line)
            if m:
                metrics[m.group(1).lower()] = float(m.group(2))

        vout_avg = metrics.get("vout_avg", 0.0)
        vout_rip = metrics.get("vout_rip", 0.0)
        il_peak = metrics.get("il_peak", 0.0)
        iin_avg = metrics.get("iin_avg", 0.0)

        p_out = (vout_avg ** 2) / r_load_ohm
        p_in = vin_v * iin_avg if iin_avg > 0 else 0.0
        eff = (p_out / p_in * 100.0) if p_in > 0 else 0.0

        print("\n=======================================================")
        print("          TENNENANCHOR SPICE VERIFICATION RESULTS      ")
        print("=======================================================")
        print(f"  Measured Output Voltage (Vout_avg) : {vout_avg:>8.3f} V  (Target: {v_ideal:.2f} V)")
        print(f"  Peak-to-Peak Voltage Ripple        : {vout_rip*1000:>8.1f} mV ({(vout_rip/abs(vout_avg)*100):.2f}%)")
        print(f"  Peak Inductor Current (IL_peak)    : {il_peak:>8.3f} A")
        print(f"  Average Input Current (Iin_avg)    : {iin_avg:>8.3f} A")
        print(f"  Output Power (Pout)                : {p_out:>8.2f} W")
        print(f"  Estimated Efficiency               : {eff:>8.1f} %")
        print("=======================================================\n")

        metrics["p_out"] = p_out
        metrics["efficiency"] = eff

    return metrics


if __name__ == "__main__":
    run_buck_boost_demo()
