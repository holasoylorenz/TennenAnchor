"""
Demo: Dynamic Circuit Synthesis and Autonomous Closed-Loop Execution in LTspice.
Generates an NMOS Common-Source Amplifier stage with gate bias divider, source bypass,
and AC coupling, then executes the full closed-loop recipe lifecycle.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parent.parent
if str(HARNESS_ROOT) not in sys.path:
    sys.path.insert(0, str(HARNESS_ROOT))

from core.circuit_builder import LTspiceSchematic
from core.app_ast import ProfileRegistry
from core.lifecycle import AppLifecycleBroker
from core.playbook_runner import PlaybookRunner
from perception.edge_parser import EdgeUIAParser

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("demo_custom_circuit")


def build_common_source_amp_schematic(
    vdd_v: float = 5.0,
    rd_kohm: float = 2.2,
    rs_ohm: float = 470.0,
    r1_kohm: float = 100.0,
    r2_kohm: float = 47.0,
    cin_uf: float = 1.0,
    cout_uf: float = 1.0,
    cs_uf: float = 10.0,
    rl_kohm: float = 10.0,
) -> LTspiceSchematic:
    """
    Synthesizes a complete NMOS Common-Source Amplifier with self-bias,
    source bypass, and AC coupling on a strict 16-pixel grid.
    """
    sch = LTspiceSchematic(sheet_width=1200, sheet_height=800)

    # 1. Power Supply Rails
    # VDD rail (Y=96)
    sch.add_wire(80, 96, 608, 96)
    sch.add_flag(80, 96, "VDD")

    # GND rail (Y=576)
    sch.add_wire(80, 576, 608, 576)
    sch.add_flag(80, 576, "0")

    # 2. DC Power Source V1 (X=80, Y=144)
    sch.add_symbol("voltage", 80, 144, "R0", inst_name="Vdd", value=str(vdd_v))
    sch.add_wire(80, 96, 80, 160)
    sch.add_wire(80, 240, 80, 576)

    # 3. AC Signal Generator Vin (X=144, Y=304)
    sch.add_symbol("voltage", 144, 304, "R0", inst_name="Vin", value="0", value2="AC 1")
    sch.add_wire(144, 256, 144, 320)
    sch.add_wire(144, 400, 144, 576)
    sch.add_flag(144, 256, "VIN")

    # 4. Input Coupling Capacitor Cin (Bridging VIN to Gate VG)
    # Origin at (144, 272), R270: Pin A (144, 256), Pin B (208, 256)
    sch.add_symbol("cap", 144, 272, "R270", inst_name="Cin", value=f"{cin_uf}u")
    sch.add_wire(208, 256, 272, 256)  # To Gate Node

    # 5. Gate Bias Network (R1 pull-up to VDD, R2 pull-down to GND)
    # R1: Origin at (256, 128), R0. Pin A (272, 144), Pin B (272, 224)
    sch.add_symbol("res", 256, 128, "R0", inst_name="R1", value=f"{r1_kohm}k")
    sch.add_wire(272, 96, 272, 144)   # VDD to R1
    sch.add_wire(272, 224, 272, 256)  # R1 to Gate Node (272, 256)

    # R2: Origin at (256, 288), R0. Pin A (272, 304), Pin B (272, 384)
    sch.add_symbol("res", 256, 288, "R0", inst_name="R2", value=f"{r2_kohm}k")
    sch.add_wire(272, 256, 272, 304)  # Gate Node to R2
    sch.add_wire(272, 384, 272, 576)  # R2 to GND

    sch.add_flag(272, 256, "VG")

    # 6. NMOS Transistor M1 (X=304, Y=224, R0)
    # Drain: (352, 224), Gate: (304, 304), Source: (352, 320)
    sch.add_symbol("nmos", 304, 224, "R0", inst_name="M1", value="NMOS_STAGE", value2="W=50u L=1u")
    sch.add_wire_path([(272, 256), (304, 256), (304, 304)])  # Gate connection

    # 7. Drain Resistor Rd (X=336, Y=112, R0)
    # Pin A (352, 128), Pin B (352, 208)
    sch.add_symbol("res", 336, 112, "R0", inst_name="Rd", value=f"{rd_kohm}k")
    sch.add_wire(352, 96, 352, 128)   # VDD to Rd
    sch.add_wire(352, 208, 352, 224)  # Rd to M1 Drain

    # 8. Source Degeneration & Bypass Network (From Source at 352, 320)
    sch.add_wire(352, 320, 352, 352)
    sch.add_wire(352, 352, 416, 352)  # Fork to Rs and Cs

    # Rs: Origin at (336, 368), R0. Pin A (352, 384), Pin B (352, 464)
    sch.add_symbol("res", 336, 368, "R0", inst_name="Rs", value=f"{rs_ohm}")
    sch.add_wire(352, 352, 352, 384)
    sch.add_wire(352, 464, 352, 576)

    # Cs (Source Bypass): Origin at (400, 368), R0. Pin A (416, 368), Pin B (416, 432)
    sch.add_symbol("cap", 400, 368, "R0", inst_name="Cs", value=f"{cs_uf}u")
    sch.add_wire(416, 352, 416, 368)
    sch.add_wire(416, 432, 416, 576)

    # 9. Output Coupling Capacitor Cout & Load Resistor RL
    # From M1 Drain (352, 224) to (432, 224)
    sch.add_wire(352, 224, 432, 224)

    # Cout: Origin at (432, 240), R270. Pin A (432, 224), Pin B (496, 224)
    sch.add_symbol("cap", 432, 240, "R270", inst_name="Cout", value=f"{cout_uf}u")
    sch.add_wire(496, 224, 560, 224)
    sch.add_flag(560, 224, "VOUT")

    # RL: Origin at (544, 256), R0. Pin A (560, 272), Pin B (560, 352)
    sch.add_symbol("res", 544, 256, "R0", inst_name="RL", value=f"{rl_kohm}k")
    sch.add_wire(560, 224, 560, 272)
    sch.add_wire(560, 352, 560, 576)

    # 10. Simulation Directives
    directives = [
        ";Discrete NMOS Common-Source Amplifier Stage",
        ".options ALLOW_AMBIGUOUS_MODELS",
        ".ac dec 50 10 100Meg",
        ".meas AC MidbandGain FIND mag(V(VOUT)) AT 10k",
        ".meas AC MidbandPhase FIND ph(V(VOUT)) AT 10k",
        ".model NMOS_STAGE NMOS(Level=1 Vto=0.8 Kp=200u Lambda=0.01)",
    ]
    sch.add_directive_block(start_x=80, start_y=624, lines=directives, line_height=36)

    return sch


def run_demo():
    output_asc = HARNESS_ROOT / "outputs" / "common_source_amp.asc"
    output_log = HARNESS_ROOT / "outputs" / "common_source_amp.log"
    
    # 1. Synthesize the new circuit
    logger.info("Synthesizing dynamic Common-Source Amplifier schematic...")
    sch = build_common_source_amp_schematic(
        vdd_v=5.0,
        rd_kohm=3.3,
        rs_ohm=330.0,
        r1_kohm=120.0,
        r2_kohm=47.0,
        cin_uf=2.2,
        cout_uf=2.2,
        cs_uf=22.0,
        rl_kohm=10.0,
    )
    sch.save(output_asc)
    logger.info("Saved new schematic to: %s", output_asc)

    # 2. Attach / Launch LTspice
    registry = ProfileRegistry()
    profile = registry.get("ltspice")
    if not profile:
        raise RuntimeError("LTspice profile not found.")

    broker = AppLifecycleBroker()
    hwnd = broker.ensure_running(profile, timeout_sec=12.0)
    logger.info("LTspice running (HWND: %s)", hwnd)
    time.sleep(0.5)

    # 3. Execute closed-loop recipes
    runner = PlaybookRunner(registry=registry)

    # Recipe 1: open_schematic
    logger.info("Executing recipe: open_schematic...")
    res_open = runner.execute(profile, "open_schematic", params={"path": str(output_asc.resolve())})
    logger.info("open_schematic result: %s", res_open.get("status"))

    # Recipe 2: run_simulation
    logger.info("Executing recipe: run_simulation...")
    res_sim = runner.execute(profile, "run_simulation")
    logger.info("run_simulation result: %s", res_sim.get("status"))
    time.sleep(2.0)

    # Recipe 3: plot_trace (V(vout))
    logger.info("Executing recipe: plot_trace (V(vout))...")
    res_plot = runner.execute(profile, "plot_trace", params={"trace": "V(vout)"})
    logger.info("plot_trace result: %s", res_plot.get("status"))

    # 4. Perception: Inspect GUI State
    parser = EdgeUIAParser()
    ui_state = parser.parse_active_window(query="V(vout)")
    logger.info("UI Perception: %d elements matching query 'V(vout)'", len(ui_state.get("elements", [])))

    # 5. Dual-Channel Verification: Check simulation output log
    import re
    if output_log.exists():
        log_text = output_log.read_text(encoding="utf-8", errors="ignore")
        print("\n=======================================================")
        print("          GROUNDPLANE DUAL-CHANNEL VERIFICATION        ")
        print("=======================================================")
        for line in log_text.splitlines():
            if "midband" in line.lower() or "gain" in line.lower() or "phase" in line.lower():
                print(f"  [MEAS] {line.strip()}")
        print("=======================================================\n")
    else:
        logger.warning("Log file %s not found on disk.", output_log)


if __name__ == "__main__":
    run_demo()
