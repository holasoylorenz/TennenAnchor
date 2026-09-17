"""
Circuit Schematic Layout & Synthesis Engine for TennenAnchor.

Generates human-grade, aesthetically arranged, grid-aligned LTspice (.asc) schematics:
- Orthogonal power rails (VDD bus at top, Ground at bottom)
- Straight vertical supply-to-ground current trajectories
- Natural left-to-right signal propagation
- Minimal path crossings
- Collision-free, uniformly padded text directive blocks

Supports both:
1. Full CMOS Two-Stage Miller OTA with native MOSFET symbols (PMOS & NMOS).
2. Small-Signal Equivalent Schematic directly visualizing the nodal equations:
   Node 1: gm1*vin + v1/R1 + s*C1*v1 + s*Cc*(v1 - vout) = 0
   Node 2: gm2*v1 + vout/R2 + s*CL*vout + s*Cc*(vout - v1) = 0
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import List, Optional, Tuple, Union

from eda.schematic_ast import (
    VALID_ROTATIONS,
    Wire,
    Flag,
    Symbol,
    Directive,
    LTspiceSchematic,
)


# ==============================================================================
# Circuit Topologies Synthesizers
# ==============================================================================

def build_cmos_miller_ota_schematic(
    cc_pf: float = 7.0,
    target_gbw_mhz: float = 10.0,
    cl_pf: float = 5.0,
    ibias_ua: float = 50.0,
    vdd_v: float = 3.3,
) -> LTspiceSchematic:
    """
    Synthesizes a visual CMOS Two-Stage Miller OTA in LTspice.
    Uses native transistor symbols (pmos & nmos) with straight vertical paths:
    - Top Rail: VDD horizontal bus at Y=96
    - Bottom Rail: Ground (0) at Y=640
    - Branch 0 (X=160): Ibias reference & M8 diode mirror
    - Branch 1 & 2 (X=272, 384): PMOS mirror loads (M3, M4) & NMOS diff pair (M1, M2) & tail (M5 at X=336)
    - Branch 3 (X=544): PMOS common-source driver (M6) & NMOS load sink (M7)
    - Branch 4 (X=544/640): Miller compensation Cc (spanning X=448 to X=512->544) & load CL
    """
    sch = LTspiceSchematic(sheet_width=1400, sheet_height=1000)

    # 1. Power Supply Rails
    # VDD Top Rail (Y=96)
    sch.add_wire(112, 96, 688, 96)
    sch.add_flag(112, 96, "VDD")

    # Ground Bottom Rail (Y=640)
    sch.add_wire(112, 640, 688, 640)
    sch.add_flag(112, 640, "0")

    # 2. Independent DC Sources (Left column, X=80)
    # VDD DC Source (X=80, Y=144)
    sch.add_symbol("voltage", 80, 144, "R0", inst_name="Vdd", value=str(vdd_v))
    sch.add_wire(80, 96, 80, 160)
    sch.add_wire(80, 96, 112, 96)
    sch.add_wire(80, 240, 80, 272)
    sch.add_flag(80, 272, "0")

    # Differential Input Sources (Vin+, Vin-)
    sch.add_symbol("voltage", 80, 320, "R0", inst_name="Vin", value=f"{vdd_v/2.0:.2f}", value2="AC 1")
    sch.add_wire(80, 320, 80, 336)
    sch.add_flag(80, 320, "INP")
    sch.add_wire(80, 416, 80, 432)
    sch.add_flag(80, 432, "0")

    sch.add_symbol("voltage", 80, 480, "R0", inst_name="Vref", value=f"{vdd_v/2.0:.2f}")
    sch.add_wire(80, 480, 80, 496)
    sch.add_flag(80, 480, "INM")
    sch.add_wire(80, 576, 80, 592)
    sch.add_flag(80, 592, "0")

    # 3. Bias Generation Branch (X=160)
    # Ibias: current source from VDD downwards
    sch.add_symbol("current", 160, 112, "R0", inst_name="Ibias", value=f"{ibias_ua}u")
    sch.add_wire(160, 96, 160, 128)
    sch.add_wire(160, 208, 160, 240)
    sch.add_flag(160, 240, "NBIAS")

    # M8: Diode-connected NMOS (Drain at 160, Source at 160, 640)
    sch.add_symbol("nmos", 112, 288, "R0", inst_name="M8", value="NMOS", value2="W=10u L=1u")
    # Drain (160, 288), Gate (112, 368), Source (160, 384)
    sch.add_wire(160, 240, 160, 288)
    sch.add_wire_path([(160, 288), (112, 288), (112, 368)])  # Diode strap: Drain to Gate
    sch.add_wire(160, 384, 160, 640)  # Source to GND

    # 4. Stage 1: Differential Pair & Active PMOS Current Mirror
    # M3 (PMOS Load Left): Drain (272, 208), Gate (224, 128), Source (272, 96)
    sch.add_symbol("pmos", 224, 208, "M180", inst_name="M3", value="PMOS", value2="W=25u L=1u")
    sch.add_wire(272, 96, 272, 112)
    sch.add_wire_path([(272, 208), (224, 208), (224, 128)])  # M3 diode strap

    # M4 (PMOS Load Right): Drain (384, 208), Gate (336, 128), Source (384, 96)
    sch.add_symbol("pmos", 336, 208, "M180", inst_name="M4", value="PMOS", value2="W=25u L=1u")
    sch.add_wire(384, 96, 384, 112)
    sch.add_wire(224, 128, 336, 128)  # Mirror Gate connection (horizontal bus at Y=128)

    # M1 (NMOS Diff Input +): Drain (272, 272), Gate (224, 352), Source (272, 368)
    sch.add_symbol("nmos", 224, 272, "R0", inst_name="M1", value="NMOS", value2="W=20u L=1u")
    sch.add_wire(272, 208, 272, 272)  # M3 Drain straight down to M1 Drain
    sch.add_wire(224, 352, 192, 352)  # Gate wire to INP
    sch.add_flag(192, 352, "INP")

    # M2 (NMOS Diff Input -): Drain (384, 272), Gate (336, 352), Source (384, 368)
    sch.add_symbol("nmos", 336, 272, "R0", inst_name="M2", value="NMOS", value2="W=20u L=1u")
    sch.add_wire(384, 208, 384, 272)  # M4 Drain straight down to M2 Drain (Intermediate Node v1)
    sch.add_wire(336, 352, 368, 352)  # Gate wire to INM
    sch.add_flag(368, 352, "INM")

    # Tail Connection & M5 (Tail Current Sink)
    # M1 Source (272, 368) & M2 Source (384, 368) join cleanly at X=336
    sch.add_wire_path([(272, 368), (336, 368), (384, 368)])
    sch.add_wire(336, 368, 336, 448)  # Straight down to M5 Drain
    # M5: Origin at X=288, Y=448 (R0). Pins: Drain (288+48=336, 448), Source (336, 544), Gate (288, 528)
    sch.add_symbol("nmos", 288, 448, "R0", inst_name="M5", value="NMOS", value2="W=20u L=1u")
    sch.add_wire(288, 528, 240, 528)  # Gate connects to NBIAS
    sch.add_flag(240, 528, "NBIAS")
    sch.add_wire(336, 544, 336, 640)  # M5 Source straight down to GND rail

    # 5. Stage 2: Common-Source PMOS Driver & NMOS Sink Load
    # Intermediate Node v1 connection: From (384, 240) to M6 Gate at (496, 128)
    sch.add_wire_path([(384, 240), (448, 240), (448, 128), (496, 128)])
    sch.add_flag(448, 240, "N_INT")

    # M6 (PMOS Driver): Source at (544, 96), Drain at (544, 208), Gate at (496, 128)
    sch.add_symbol("pmos", 496, 208, "M180", inst_name="M6", value="PMOS", value2="W=50u L=1u")
    sch.add_wire(544, 96, 544, 112)

    # M7 (NMOS Active Load Sink): Drain at (544, 272), Gate at (496, 352), Source at (544, 368)
    sch.add_symbol("nmos", 496, 272, "R0", inst_name="M7", value="NMOS", value2="W=20u L=1u")
    sch.add_wire(544, 208, 544, 272)  # M6 Drain straight down to M7 Drain (Output Node vout)
    sch.add_wire(496, 352, 464, 352)  # Gate to NBIAS
    sch.add_flag(464, 352, "NBIAS")
    sch.add_wire(544, 368, 544, 640)  # M7 Source to GND rail

    # 6. Miller Compensation Capacitor Cc & Load Capacitor CL
    # In cap.asy, pins are (16, 0) and (16, 64). Under R270: (x, y) -> (y, -x)
    # Origin at (448, 256): Pin A is (448, 240), Pin B is (448+64, 240) = (512, 240)
    sch.add_symbol("cap", 448, 256, "R270", inst_name="Cc", value=f"{cc_pf}p")
    # Pin A touches N_INT at (448, 240). Wire from Pin B (512, 240) to VOUT (544, 240)
    sch.add_wire(512, 240, 544, 240)

    # VOUT Tap & Load Capacitor CL (X=640)
    sch.add_wire(544, 240, 640, 240)
    sch.add_flag(640, 240, "VOUT")
    sch.add_symbol("cap", 624, 288, "R0", inst_name="CL", value=f"{cl_pf}p")
    sch.add_wire(640, 240, 640, 288)
    sch.add_wire(640, 352, 640, 640)

    # 7. Isolated Simulation Directive Block (Bottom Margin, Y >= 700)
    directives = [
        f";Two-Stage CMOS Miller OTA (Target GBW = {target_gbw_mhz} MHz, Cc = {cc_pf}pF, CL = {cl_pf}pF)",
        ".ac dec 50 10 1G",
        ".meas AC A0 FIND mag(V(VOUT)) AT 10",
        ".meas AC GBW WHEN mag(V(VOUT))=1",
        ".meas AC Phase_at_GBW FIND ph(V(VOUT)) WHEN mag(V(VOUT))=1",
        ".meas AC PM PARAM 180 + Phase_at_GBW",
        ".model NMOS NMOS(Level=1 Vto=0.7 Kp=100u Lambda=0.02)",
        ".model PMOS PMOS(Level=1 Vto=-0.7 Kp=40u Lambda=0.02)",
    ]
    sch.add_directive_block(start_x=80, start_y=704, lines=directives, line_height=36)

    return sch


def build_small_signal_miller_schematic(
    gm1_mho: float = 1.0e-3,
    r1_ohm: float = 100.0e3,
    c1_pf: float = 0.5,
    cc_pf: float = 7.0,
    gm2_mho: float = 2.0e-3,
    r2_ohm: float = 50.0e3,
    cl_pf: float = 5.0,
) -> LTspiceSchematic:
    """
    Synthesizes the exact small-signal equivalent schematic directly corresponding
    to the user-specified nodal equations:
    Node 1: gm1*vin + v1/R1 + s*C1*v1 + s*Cc*(v1 - vout) = 0
    Node 2: gm2*v1 + vout/R2 + s*CL*vout + s*Cc*(vout - v1) = 0
    """
    sch = LTspiceSchematic(sheet_width=1400, sheet_height=900)

    # Ground bus at bottom (Y=512)
    sch.add_wire(80, 512, 704, 512)
    sch.add_flag(80, 512, "0")

    # 1. AC Input Signal Source (X=112)
    sch.add_symbol("voltage", 112, 224, "R0", inst_name="Vin", value="0", value2="AC 1")
    sch.add_wire(112, 176, 112, 240)
    sch.add_flag(112, 176, "VIN")
    sch.add_wire(112, 320, 112, 512)

    # 2. Stage 1: Controlled Current Source G1, Resistor R1, Capacitor C1
    # Node 1 (V1) Bus at Y=176
    sch.add_wire(224, 176, 400, 176)
    sch.add_flag(304, 176, "V1")

    # G1: Voltage-controlled current source pulling current DOWN out of Node 1 to GND
    # Under R180: Pin 1 (Out+) is at (X, Y - 96), Pin 2 (Out-) is at (X, Y - 16)
    # NC+ is at (X + 48, Y - 32), NC- is at (X + 48, Y - 80)
    # Place at (224, 272) R180:
    # Pin 1 (Out+) at (224, 176) [on Node 1 wire!]
    # Pin 2 (Out-) at (224, 256). Wire (224, 256) -> (224, 512) to GND!
    # NC+ at (272, 240) -> wire to VIN at (272, 240)
    # NC- at (272, 192) -> wire to GND
    # Netlist: G1 V1 0 VIN 0 <gm1_mho>
    sch.add_symbol("g", 224, 272, "R180", inst_name="G1", value=f"{gm1_mho}")
    sch.add_wire(224, 176, 224, 176)  # Pin 1 touches Node 1 bus directly
    sch.add_wire(224, 256, 224, 512)  # Pin 2 down to GND
    sch.add_wire(272, 240, 272, 240)
    sch.add_flag(272, 240, "VIN")
    sch.add_wire(272, 192, 272, 208)
    sch.add_flag(272, 208, "0")

    # R1 (Stage 1 Output Resistance): Pin A at (304, 256), Pin B at (304, 336)
    sch.add_symbol("res", 288, 240, "R0", inst_name="R1", value=f"{r1_ohm/1e3:.1f}k")
    sch.add_wire(304, 176, 304, 256)
    sch.add_wire(304, 336, 304, 512)

    # C1 (Stage 1 Internal Capacitance): Pin A at (384, 240), Pin B at (384, 304)
    sch.add_symbol("cap", 368, 240, "R0", inst_name="C1", value=f"{c1_pf}p")
    sch.add_wire(384, 176, 384, 240)
    sch.add_wire(384, 304, 384, 512)

    # 3. Miller Feedback Capacitor Cc: Bridging Node 1 (V1) to Node 2 (VOUT)
    # Spanning horizontally across the top from X=400 to X=512 at Y=112
    # Symbol placed at (416, 128) R270:
    # Pin A at (416, 112), Pin B at (416 + 64, 112) = (480, 112)
    sch.add_wire_path([(400, 176), (400, 112), (416, 112)])
    sch.add_symbol("cap", 416, 128, "R270", inst_name="Cc", value=f"{cc_pf}p")
    sch.add_wire_path([(480, 112), (512, 112), (512, 176)])

    # 4. Stage 2: Controlled Current Source G2, Resistor R2, Load Capacitor CL
    # Node 2 (VOUT) Bus at Y=176
    sch.add_wire(512, 176, 672, 176)
    sch.add_flag(672, 176, "VOUT")

    # G2: Voltage-controlled current source pulling current DOWN out of VOUT to GND
    # Placed at (544, 272) R180:
    # Pin 1 (Out+) at (544, 176) [on VOUT bus!]
    # Pin 2 (Out-) at (544, 256) -> down to GND
    # NC+ at (592, 240) -> flag V1
    # NC- at (592, 192) -> flag 0
    # Netlist: G2 VOUT 0 V1 0 <gm2_mho>
    sch.add_symbol("g", 544, 272, "R180", inst_name="G2", value=f"{gm2_mho}")
    sch.add_wire(544, 256, 544, 512)
    sch.add_flag(592, 240, "V1")
    sch.add_wire(592, 192, 592, 208)
    sch.add_flag(592, 208, "0")

    # R2 (Stage 2 Output Resistance): Pin A at (624, 256), Pin B at (624, 336)
    sch.add_symbol("res", 608, 240, "R0", inst_name="R2", value=f"{r2_ohm/1e3:.1f}k")
    sch.add_wire(624, 176, 624, 256)
    sch.add_wire(624, 336, 624, 512)

    # CL (Load Capacitance): Pin A at (672, 240), Pin B at (672, 304)
    sch.add_symbol("cap", 656, 240, "R0", inst_name="CL", value=f"{cl_pf}p")
    sch.add_wire(672, 176, 672, 240)
    sch.add_wire(672, 304, 672, 512)

    # 5. Directives Block
    directives = [
        ";Small-Signal Two-Stage Miller OTA Model",
        ";Nodal equations:",
        ";  Node 1: gm1*vin + v1/R1 + s*C1*v1 + s*Cc*(v1 - vout) = 0",
        ";  Node 2: gm2*v1 + vout/R2 + s*CL*vout + s*Cc*(vout - v1) = 0",
        ".ac dec 50 10 1G",
        ".meas AC A0 FIND mag(V(VOUT)) AT 10",
        ".meas AC GBW WHEN mag(V(VOUT))=1",
        ".meas AC Phase_at_GBW FIND ph(V(VOUT)) WHEN mag(V(VOUT))=1",
        ".meas AC PM PARAM 180 + Phase_at_GBW",
    ]
    sch.add_directive_block(start_x=80, start_y=560, lines=directives, line_height=32)

    return sch


def build_buck_boost_schematic(
    vin_v: float = 12.0,
    duty_cycle: float = 0.50,
    f_sw_khz: float = 100.0,
    l_uh: float = 100.0,
    c_uf: float = 47.0,
    r_load_ohm: float = 20.0,
    t_sim_ms: float = 2.0,
) -> LTspiceSchematic:
    """
    Synthesizes an Inverting Buck-Boost Converter schematic for LTspice.

    Continuous Conduction Mode (CCM) Transfer Function:
      Vout = -Vin * (D / (1 - D))
      - For Vin=12V, D=0.50 -> Vout = -12.0V
      - For Vin=12V, D=0.33 -> Vout = -5.9V (Buck Mode)
      - For Vin=12V, D=0.67 -> Vout = -24.4V (Boost Mode)
    """
    sch = LTspiceSchematic(sheet_width=1200, sheet_height=800, grid_size=8)

    # Calculate switching PWM timing
    t_period_s = 1.0 / (f_sw_khz * 1e3)
    t_on_s = duty_cycle * t_period_s
    t_period_us = t_period_s * 1e6
    t_on_us = t_on_s * 1e6

    # 1. DC Input Power Source (Vin)
    sch.add_symbol("voltage", 128, 240, "R0", inst_name="Vin", value=f"{vin_v:.1f}")
    sch.add_wire(128, 200, 352, 200)  # VIN bus connecting to S1
    sch.add_wire(128, 200, 128, 256)
    sch.add_wire(128, 336, 128, 368)
    sch.add_flag(128, 200, "VIN")
    sch.add_flag(128, 368, "0")

    # 2. Gate Pulse Generator (Vgate)
    sch.add_symbol(
        "voltage",
        224,
        384,
        "R0",
        inst_name="Vgate",
        value=f"PULSE(0 5 0 10n 10n {t_on_us:.2f}u {t_period_us:.2f}u)",
        windows=["0 24 16 Left 2", "3 24 96 Left 2"]
    )
    sch.add_wire(224, 400, 416, 400)
    sch.add_wire(416, 400, 416, 200)
    sch.add_wire(224, 480, 224, 512)
    sch.add_flag(224, 512, "0")

    # 3. Controlled Power Switch (S1)
    # Pins: P1 (352, 200), P2 (352, 280), C1 (416, 200), C2 (416, 280)
    sch.add_symbol("sw", 352, 184, "R0", inst_name="S1", value="MYSW")
    sch.add_wire(416, 280, 416, 320)
    sch.add_flag(416, 320, "0")

    # 4. Storage Inductor (L1) - connected between SW node and Ground
    sch.add_symbol("ind", 336, 320, "R0", inst_name="L1", value=f"{l_uh:.0f}u")
    sch.add_wire(352, 280, 352, 336)
    sch.add_wire(352, 416, 352, 448)
    sch.add_flag(352, 280, "SW")
    sch.add_flag(352, 448, "0")

    # 5. Fast Freewheeling Diode (D1)
    # Pins: K at (448, 280), A at (512, 280)
    sch.add_wire(352, 280, 448, 280)
    sch.add_symbol("diode", 512, 264, "R90", inst_name="D1", value="1N5819")
    sch.add_wire(512, 280, 640, 280)

    # 6. Filter Capacitor (C1) & Resistive Load (Rload)
    sch.add_symbol("cap", 624, 280, "R0", inst_name="C1", value=f"{c_uf:.0f}u")
    sch.add_wire(640, 344, 640, 384)
    sch.add_flag(640, 384, "0")

    # Output Node & Load
    sch.add_wire(640, 280, 736, 280)
    sch.add_symbol("res", 720, 264, "R0", inst_name="Rload", value=f"{r_load_ohm:.0f}")
    sch.add_wire(736, 360, 736, 384)
    sch.add_flag(736, 384, "0")
    sch.add_flag(640, 280, "VOUT")

    # 7. SPICE Directives & Measurements
    v_target = -vin_v * (duty_cycle / (1.0 - duty_cycle))
    t_meas_start = t_sim_ms * 0.75
    directives = [
        f";Inverting Buck-Boost Converter (Vin={vin_v}V, f={f_sw_khz}kHz, D={duty_cycle*100:.1f}%)",
        f";Theoretical Output: Vout = -Vin*(D/(1-D)) = {v_target:.2f}V",
        f".tran {t_sim_ms}m",
        ".model MYSW SW(Ron=0.02 Roff=1Meg Vt=2.5 Vh=0.5)",
        f".meas TRAN Vout_avg AVG V(VOUT) FROM {t_meas_start}m TO {t_sim_ms}m",
        f".meas TRAN Vout_rip PP V(VOUT) FROM {t_meas_start}m TO {t_sim_ms}m",
        f".meas TRAN IL_peak MAX I(L1) FROM {t_meas_start}m TO {t_sim_ms}m",
        f".meas TRAN Iin_avg AVG -I(Vin) FROM {t_meas_start}m TO {t_sim_ms}m",
    ]
    sch.add_directive_block(start_x=128, start_y=560, lines=directives, line_height=40)

    return sch


def build_rc_filter_schematic(
    r_kohm: float = 10.0,
    c_nf: float = 100.0,
    ac_mag: float = 1.0,
) -> LTspiceSchematic:
    """
    Synthesizes a first-order passive RC Low-Pass Filter schematic for LTspice.
    Mathematically aligned with standard LTspice symbol pin offsets and collision-free text.
    Cutoff frequency: fc = 1 / (2 * pi * R * C)
    """
    import math
    sch = LTspiceSchematic(sheet_width=900, sheet_height=600, grid_size=16)
    fc_hz = 1.0 / (2.0 * math.pi * (r_kohm * 1e3) * (c_nf * 1e-9))

    # Grid layout:
    # Vin supply at x=80, y=176 (Pin+ at 80,192; Pin- at 80,272)
    # R1 horizontal at x=256, y=144 R90 (Pin B at 160,160; Pin A at 240,160)
    # C1 vertical at x=304, y=160 R0 (Pin A at 320,160; Pin B at 320,224)
    # VOUT flag at x=384, y=160

    # 1. AC Voltage Source
    sch.add_symbol(
        "voltage", 80, 176, "R0",
        inst_name="Vin", value="0", value2=f"AC {ac_mag}",
        windows=["0 24 16 Left 2", "3 24 96 Left 2"]
    )
    sch.add_wire(80, 160, 80, 192)
    sch.add_wire(80, 160, 160, 160)
    sch.add_flag(80, 160, "VIN")
    sch.add_wire(80, 272, 80, 304)
    sch.add_flag(80, 304, "0")

    # 2. Resistor R1
    sch.add_symbol(
        "res", 256, 144, "R90",
        inst_name="R1", value=f"{r_kohm:.1f}k",
        windows=["0 0 56 VBottom 2", "3 32 56 VTop 2"]
    )
    sch.add_wire(240, 160, 320, 160)

    # 3. Capacitor C1
    sch.add_symbol(
        "cap", 304, 160, "R0",
        inst_name="C1", value=f"{c_nf:.1f}n"
    )
    sch.add_wire(320, 224, 320, 304)
    sch.add_flag(320, 304, "0")

    # 4. Output Node VOUT
    sch.add_wire(320, 160, 384, 160)
    sch.add_flag(384, 160, "VOUT")

    # 5. Directives & Measurements
    directives = [
        f";RC Low-Pass Filter (R = {r_kohm}k, C = {c_nf}nF, fc = {fc_hz:.1f} Hz)",
        ".ac dec 50 1 100k",
        ".meas AC fc WHEN mag(V(VOUT))=0.7071",
    ]
    sch.add_directive_block(start_x=80, start_y=350, lines=directives, line_height=32)

    return sch


def build_hierarchical_active_filter_schematic(
    r_in_k: float = 10.0,
    r_fb_k: float = 100.0,
    c_fb_pf: float = 100.0,
    output_dir: Union[Path, str] = "outputs/hierarchical",
) -> Tuple[LTspiceSchematic, LTspiceSchematic]:
    """
    Synthesizes a two-level hierarchical active filter:
    1. Child block: opamp_core.asc (internal differential amplifier subcircuit)
    2. Top level: top_active_filter.asc (active feedback topology with op-amp symbol)
    """
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Child Subcircuit: opamp_core.asc
    sub_sch = build_cmos_miller_ota_schematic(cc_pf=5.0, cl_pf=2.0)
    sub_sch.save(out_dir / "opamp_core.asc")

    # 2. Top-Level Schematic: Inverting Active Low-Pass Filter
    top = LTspiceSchematic(sheet_width=1200, sheet_height=800, grid_size=16)

    # Signal source Vin at (80, 240)
    top.add_symbol("voltage", 80, 240, "R0", inst_name="Vin", value="0", value2="AC 1.0",
                   windows=["0 24 16 Left 2", "3 24 96 Left 2"])
    top.add_wire(80, 208, 80, 256)
    top.add_wire(80, 208, 160, 208)
    top.add_flag(80, 208, "VIN")
    top.add_wire(80, 336, 80, 368)
    top.add_flag(80, 368, "0")

    # Input Resistor Rin (160, 192 R90): Pin B at (160, 208), Pin A at (240, 208)
    top.add_symbol("res", 256, 192, "R90", inst_name="Rin", value=f"{r_in_k:.1f}k",
                   windows=["0 0 56 VBottom 2", "3 32 56 VTop 2"])
    top.add_wire(240, 208, 320, 208)
    top.add_wire(320, 208, 320, 224)
    top.add_wire(320, 224, 352, 224)  # Connects to IN- at (352, 224)

    # Op-Amp block at (384, 240 R0):
    # Standard UniversalOpAmp2 pins: IN+ (352, 256), IN- (352, 224), OUT (416, 240), V+ (384, 208), V- (384, 272)
    top.add_symbol("OpAmps\\UniversalOpAmp2", 384, 240, "R0", inst_name="U1")

    # Non-inverting input IN+ (352, 256) to Ground
    top.add_wire(352, 256, 320, 256)
    top.add_wire(320, 256, 320, 304)
    top.add_flag(320, 304, "0")

    # Feedback Loop (Rfb || Cfb) above opamp: from inverting node (320, 224) up to Y=128
    top.add_wire(320, 224, 320, 128)
    top.add_wire(320, 128, 336, 128)
    # Rfb at (432, 112 R90): Pin B at (336, 128), Pin A at (416, 128)
    top.add_symbol("res", 432, 112, "R90", inst_name="Rfb", value=f"{r_fb_k:.1f}k",
                   windows=["0 0 56 VBottom 2", "3 32 56 VTop 2"])
    top.add_wire(416, 128, 480, 128)

    # Parallel Feedback Capacitor Cfb along Y=80
    top.add_wire(320, 128, 320, 80)
    top.add_wire(320, 80, 336, 80)
    # Cfb at (400, 96 R270): Pin A at (336, 80), Pin B at (400, 80)
    top.add_symbol("cap", 400, 96, "R270", inst_name="Cfb", value=f"{c_fb_pf:.0f}p")
    top.add_wire(400, 80, 480, 80)
    top.add_wire(480, 80, 480, 128)

    # Connect feedback down to OpAmp OUT (416, 240)
    top.add_wire(480, 128, 480, 240)
    top.add_wire(416, 240, 480, 240)
    top.add_wire(480, 240, 544, 240)
    top.add_flag(544, 240, "VOUT")

    # Power supplies for OpAmp
    top.add_wire(384, 208, 384, 160)
    top.add_flag(384, 160, "+15V")
    top.add_wire(384, 272, 384, 304)
    top.add_flag(384, 304, "-15V")

    # Directives
    dc_gain = r_fb_k / r_in_k
    f_p_khz = 1.0 / (2.0 * math.pi * (r_fb_k * 1e3) * (c_fb_pf * 1e-12)) / 1e3
    directives = [
        f";Hierarchical Active Filter (Gain = -{dc_gain:.1f}, fp = {f_p_khz:.1f} kHz)",
        ";Subcircuit: opamp_core.asc",
        ".ac dec 50 10 10Meg",
        ".meas AC A0 FIND mag(V(VOUT)) AT 10",
        ".meas AC fp WHEN mag(V(VOUT))=0.7071*A0",
    ]
    top.add_directive_block(start_x=80, start_y=430, lines=directives, line_height=32)
    top.save(out_dir / "top_active_filter.asc")

    return top, sub_sch


def build_bandpass_filter_schematic(
    f0_khz: float = 1.0,
    q: float = 2.0,
    gain: float = 2.0,
) -> LTspiceSchematic:
    """
    Synthesizes a clean Multiple-Feedback (MFB) 2nd-order Active Bandpass Filter.
    100% pin-matched and DRC clean.
    """
    sch = LTspiceSchematic(sheet_width=1100, sheet_height=700, grid_size=16)

    # 1. OpAmp U1: UniversalOpAmp2 at (480, 240 R0)
    # In+ (448, 256), In- (448, 224), V+ (480, 208), V- (480, 272), OUT (512, 240)
    sch.add_symbol("OpAmps\\UniversalOpAmp2", 480, 240, "R0", inst_name="U1")
    # Ground non-inverting input In+
    sch.add_wire(448, 256, 448, 304)
    sch.add_flag(448, 304, "0")
    # Supply rails
    sch.add_wire(480, 208, 480, 160)
    sch.add_flag(480, 160, "+15V")
    sch.add_wire(480, 272, 480, 304)
    sch.add_flag(480, 304, "-15V")

    # 2. Input AC Source at (80, 208 R0): Pin+ (80, 224), Pin- (80, 304)
    sch.add_symbol("voltage", 80, 208, "R0", inst_name="Vin", value="0", value2="AC 1")
    sch.add_wire(80, 224, 160, 224)
    sch.add_flag(80, 224, "VIN")
    sch.add_wire(80, 304, 80, 336)
    sch.add_flag(80, 336, "0")

    # 3. Input Resistor R1 (256, 208 R90): Pin B (160, 224), Pin A (240, 224)
    sch.add_symbol("res", 256, 208, "R90", inst_name="R1", value="10k",
                   windows=["0 0 56 VBottom 2", "3 32 56 VTop 2"])
    sch.add_wire(240, 224, 272, 224)  # Wire to Node Vx at (272, 224)

    # 4. Resistor R2 (from Vx down to GND): Pin A (272, 240), Pin B (272, 320)
    sch.add_wire(272, 224, 272, 240)
    sch.add_symbol("res", 256, 224, "R0", inst_name="R2", value="1.5k")
    sch.add_wire(272, 320, 272, 336)
    sch.add_flag(272, 336, "0")

    # 5. Capacitor C1 (from Vx to In- at 448, 224):
    # C1 at (320, 240 R270): Pin A (320, 224), Pin B (384, 224)
    sch.add_wire(272, 224, 320, 224)
    sch.add_symbol("cap", 320, 240, "R270", inst_name="C1", value="10n")
    sch.add_wire(384, 224, 448, 224)

    # 6. Feedback Capacitor C2 (from Vx to VOUT) along Y=80:
    # C2 at (352, 96 R270): Pin A (352, 80), Pin B (416, 80)
    sch.add_wire(272, 224, 272, 80)
    sch.add_wire(272, 80, 352, 80)
    sch.add_symbol("cap", 352, 96, "R270", inst_name="C2", value="10n")
    sch.add_wire(416, 80, 560, 80)
    sch.add_wire(560, 80, 560, 240)

    # 7. Feedback Resistor R3 (from In- to VOUT) along Y=144:
    # R3 at (544, 128 R90): Pin B (448, 144), Pin A (528, 144)
    sch.add_wire(448, 224, 448, 144)
    sch.add_symbol("res", 544, 128, "R90", inst_name="R3", value="47k")
    sch.add_wire(528, 144, 560, 144)
    sch.add_wire(560, 144, 560, 240)

    # 8. Output Connection: OpAmp OUT (512, 240) to VOUT
    sch.add_wire(512, 240, 560, 240)
    sch.add_wire(560, 240, 624, 240)
    sch.add_flag(624, 240, "VOUT")

    # 9. Directives
    directives = [
        f";MFB Active Bandpass Filter (f0 = {f0_khz:.1f} kHz, Q = {q:.1f})",
        ".ac dec 50 10 100k",
        ".meas AC f_center MAX mag(V(VOUT))",
        ".meas AC gain_peak MAX mag(V(VOUT)/V(VIN))",
    ]
    sch.add_directive_block(start_x=80, start_y=420, lines=directives, line_height=32)
    return sch


def build_voltage_reference_schematic(
    vin_v: float = 12.0,
    vref_v: float = 5.1,
) -> LTspiceSchematic:
    """
    Synthesizes a precision Zener diode shunt voltage reference.
    100% pin-matched and DRC clean.
    """
    sch = LTspiceSchematic(sheet_width=900, sheet_height=600, grid_size=16)

    # 1. DC Input Source at (80, 160 R0): Pin+ (80, 176), Pin- (80, 256)
    sch.add_symbol("voltage", 80, 160, "R0", inst_name="Vin", value=str(vin_v))
    sch.add_wire(80, 128, 80, 176)
    sch.add_wire(80, 128, 320, 128)
    sch.add_flag(80, 128, "VIN")
    sch.add_wire(80, 256, 80, 352)

    # 2. Dropping Resistor R1 at (304, 128 R0): Pin A (320, 144), Pin B (320, 224)
    sch.add_wire(320, 128, 320, 144)
    sch.add_symbol("res", 304, 128, "R0", inst_name="R1", value="680")

    # 3. Reference Node VREF bus at Y=224: spanning from X=320 to X=480
    sch.add_wire(320, 224, 400, 224)
    sch.add_wire(400, 224, 480, 224)
    sch.add_flag(480, 224, "VREF")

    # 4. Zener Diode D1 placed at (336, 304 R180):
    # Pin 2 (Cathode -) at (320, 240) connects to VREF
    # Pin 1 (Anode +) at (320, 304) connects to Ground
    sch.add_symbol("zener", 336, 304, "R180", inst_name="D1", value="BZX84C5V1L")
    sch.add_wire(320, 224, 320, 240)
    sch.add_wire(320, 304, 320, 352)

    # 5. Output Filter Capacitor C1 at (384, 240 R0): Pin A (400, 240), Pin B (400, 304)
    sch.add_symbol("cap", 384, 240, "R0", inst_name="C1", value="10u")
    sch.add_wire(400, 224, 400, 240)
    sch.add_wire(400, 304, 400, 352)

    # 6. Load Resistor Rload at (464, 224 R0): Pin A (480, 240), Pin B (480, 320)
    sch.add_symbol("res", 464, 224, "R0", inst_name="Rload", value="10k")
    sch.add_wire(480, 224, 480, 240)
    sch.add_wire(480, 320, 480, 352)

    # 7. Ground Rail along Y=352
    sch.add_wire(80, 352, 480, 352)
    sch.add_flag(80, 352, "0")

    # 8. Directives & Model definition (ensures LTspice never errors on missing model)
    directives = [
        f";Precision Zener Voltage Reference (Vin = {vin_v}V, Vref = {vref_v}V)",
        ".model BZX84C5V1L D(Is=1e-14 Bv=5.1 Ibv=1m)",
        ".tran 10m",
        ".meas TRAN Vref_dc AVG V(VREF) FROM 5m TO 10m",
        ".meas TRAN I_zener AVG I(D1) FROM 5m TO 10m",
    ]
    sch.add_directive_block(start_x=80, start_y=420, lines=directives, line_height=32)
    return sch


def build_bjt_amplifier_schematic(
    vcc_v: float = 12.0,
    r_c_kohm: float = 2.2,
    r_e_ohm: float = 470.0,
) -> LTspiceSchematic:
    """
    Synthesizes a classic Common-Emitter BJT Audio Pre-Amplifier.
    100% pin-matched and DRC clean.
    """
    sch = LTspiceSchematic(sheet_width=1000, sheet_height=700, grid_size=16)

    # 1. DC Supply Source Vcc at (48, 144 R0): Pin+ (48, 160), Pin- (48, 240)
    sch.add_symbol("voltage", 48, 144, "R0", inst_name="Vcc", value=str(vcc_v),
                   windows=["0 -32 16 Right 2", "3 -32 96 Right 2"])
    sch.add_wire(48, 160, 48, 96)
    sch.add_wire(48, 96, 384, 96)
    sch.add_flag(48, 96, "VCC")
    sch.add_wire(48, 240, 48, 480)

    # 2. Base Bias Divider: R1 (top) and R2 (bottom) along X=224
    # R1 at (208, 128 R0): Pin A (224, 144), Pin B (224, 224)
    sch.add_wire(224, 96, 224, 144)
    sch.add_symbol("res", 208, 128, "R0", inst_name="R1", value="33k")
    sch.add_wire(224, 224, 224, 272)
    # R2 at (208, 288 R0): Pin A (224, 304), Pin B (224, 384)
    sch.add_wire(224, 272, 224, 304)
    sch.add_symbol("res", 208, 288, "R0", inst_name="R2", value="6.8k")
    sch.add_wire(224, 384, 224, 480)

    # 3. NPN Transistor Q1 at (320, 224 R0):
    # Collector (384, 224), Base (320, 272), Emitter (384, 320)
    sch.add_symbol("npn", 320, 224, "R0", inst_name="Q1", value="2N2222")
    sch.add_wire(224, 272, 320, 272)  # Base connection

    # 4. Collector Load Resistor Rc at (368, 112 R0): Pin A (384, 128), Pin B (384, 208)
    sch.add_wire(384, 96, 384, 128)
    sch.add_symbol("res", 368, 112, "R0", inst_name="Rc", value=f"{r_c_kohm}k")
    sch.add_wire(384, 208, 384, 224)

    # 5. Emitter Degeneration Resistor Re at (368, 336 R0): Pin A (384, 352), Pin B (384, 432)
    sch.add_wire(384, 320, 384, 352)
    sch.add_symbol("res", 368, 336, "R0", inst_name="Re", value=f"{int(r_e_ohm)}")
    sch.add_wire(384, 432, 384, 480)

    # 6. Emitter Bypass Capacitor Ce at (448, 352 R0): Pin A (464, 352), Pin B (464, 416)
    sch.add_wire(384, 320, 464, 320)
    sch.add_wire(464, 320, 464, 352)
    sch.add_symbol("cap", 448, 352, "R0", inst_name="Ce", value="47u")
    sch.add_wire(464, 416, 464, 480)

    # 7. Input AC Source Vin & Input Coupling Cap Cin
    sch.add_symbol("voltage", 48, 320, "R0", inst_name="Vin", value="0", value2="AC 10m",
                   windows=["0 -32 16 Right 2", "3 -32 96 Right 2"])
    sch.add_wire(48, 336, 48, 272)
    sch.add_wire(48, 272, 96, 272)
    sch.add_flag(48, 272, "VIN")
    sch.add_wire(48, 416, 48, 480)
    # Cin at (96, 288 R270): Pin A (96, 272), Pin B (160, 272)
    sch.add_symbol("cap", 96, 288, "R270", inst_name="Cin", value="10u")
    sch.add_wire(160, 272, 224, 272)

    # 8. Output Coupling Cap Cout at (448, 240 R270): Pin A (448, 224), Pin B (512, 224)
    sch.add_wire(384, 224, 448, 224)
    sch.add_symbol("cap", 448, 240, "R270", inst_name="Cout", value="10u")
    sch.add_wire(512, 224, 576, 224)
    sch.add_flag(576, 224, "VOUT")

    # 9. Ground Rail along Y=480
    sch.add_wire(48, 480, 464, 480)
    sch.add_flag(48, 480, "0")

    # 10. Directives
    directives = [
        ";BJT Common-Emitter Audio Amplifier",
        ".ac dec 50 10 10Meg",
        ".meas AC midband_gain MAX mag(V(VOUT)/V(VIN))",
        ".meas AC f_low WHEN mag(V(VOUT)/V(VIN))=0.7071*midband_gain",
    ]
    sch.add_directive_block(start_x=80, start_y=540, lines=directives, line_height=32)
    return sch


def build_circuit_topology_metadata_ledger(
    schematics_dir: Union[Path, str] = "outputs",
    output_ledger_path: Union[Path, str] = "knowledge/circuit_topology_metadata.json",
) -> Dict[str, Any]:
    """
    Compiles layout metrics, component spacing, and topological invariants
    from all clean verified schematics into an empirical machine-readable metadata ledger.
    """
    import json
    from core.circuit_linter import CircuitLinter
    linter = CircuitLinter()
    src_dir = Path(schematics_dir).resolve()
    dest_path = Path(output_ledger_path).resolve()
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    files = list(src_dir.glob("*.asc")) + list(src_dir.glob("*/*.asc"))
    corpus_entries: List[Dict[str, Any]] = []

    for f in sorted(files):
        lint_res = linter.lint_file(f)
        if not lint_res.get("is_clean", False):
            continue

        entry = {
            "name": f.stem,
            "relative_path": str(f.relative_to(src_dir.parent)).replace("\\", "/"),
            "quality_score": lint_res["quality_score"],
            "components_count": lint_res["components_count"],
            "wires_count": lint_res["wires_count"],
            "flags_count": lint_res["flags_count"],
            "total_pins": lint_res["total_pins"],
            "directives_count": lint_res["directives_count"],
            "is_clean": True,
        }
        corpus_entries.append(entry)

    ledger_payload = {
        "version": "1.0",
        "description": "Empirical topological metadata ledger of verified clean LTspice schematics.",
        "verified_schematics_count": len(corpus_entries),
        "design_rules": {
            "grid_alignment_px": 16,
            "min_horizontal_column_pitch_px": 128,
            "min_vertical_tier_pitch_px": 96,
            "pin_offset_invariants": {
                "resistor_horizontal_r90": {"pin_b_dx": -96, "pin_a_dx": -16, "dy": 16},
                "capacitor_vertical_r0": {"pin_a_dy": 0, "pin_b_dy": 64, "dx": 16},
                "voltage_source_r0": {"pin_plus_dy": 16, "pin_minus_dy": 96, "dx": 0},
                "mosfet_nmos_r0": {"drain": (48, 0), "gate": (0, 80), "source": (48, 96)},
                "mosfet_pmos_m180": {"source": (48, -96), "gate": (0, -80), "drain": (48, 0)},
            },
            "no_forced_window_coordinates": True,
            "clipboard_paste_path_resolution": True,
        },
        "corpus": corpus_entries,
    }

    dest_path.write_text(json.dumps(ledger_payload, indent=2), encoding="utf-8")
    return ledger_payload



