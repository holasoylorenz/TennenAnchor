"""
Miller OTA Schematic Generator for LTspice.
Synthesizes a 2-stage CMOS Miller Operational Transconductance Amplifier
and Small-Signal equivalent models with parametric compensation capacitor Cc.
"""

from __future__ import annotations

import sys
from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parent.parent
if str(HARNESS_ROOT) not in sys.path:
    sys.path.insert(0, str(HARNESS_ROOT))

from core.circuit_builder import (
    build_cmos_miller_ota_schematic,
    build_small_signal_miller_schematic,
    LTspiceSchematic,
)


def generate_miller_ota_asc(
    cc_pf: float,
    target_gbw_mhz: float,
    output_path: Path,
    cl_pf: float = 5.0,
    ibias_ua: float = 50.0,
    vdd_v: float = 3.3,
) -> str:
    """
    Synthesizes a clean, human-readable Two-Stage CMOS Miller OTA schematic
    with native PMOS and NMOS transistor symbols, orthogonal rails, straight
    vertical currents, and collision-free directive placement.
    """
    sch = build_cmos_miller_ota_schematic(
        cc_pf=cc_pf,
        target_gbw_mhz=target_gbw_mhz,
        cl_pf=cl_pf,
        ibias_ua=ibias_ua,
        vdd_v=vdd_v,
    )
    sch.save(output_path)
    return sch.build()


def generate_small_signal_ota_asc(
    output_path: Path,
    gm1_mho: float = 1.0e-3,
    r1_ohm: float = 100.0e3,
    c1_pf: float = 0.5,
    cc_pf: float = 7.0,
    gm2_mho: float = 2.0e-3,
    r2_ohm: float = 50.0e3,
    cl_pf: float = 5.0,
) -> str:
    """
    Synthesizes the small-signal equivalent schematic directly visualizing
    the two nodal equations:
    Node 1: gm1*vin + v1/R1 + s*C1*v1 + s*Cc*(v1 - vout) = 0
    Node 2: gm2*v1 + vout/R2 + s*CL*vout + s*Cc*(vout - v1) = 0
    """
    sch = build_small_signal_miller_schematic(
        gm1_mho=gm1_mho,
        r1_ohm=r1_ohm,
        c1_pf=c1_pf,
        cc_pf=cc_pf,
        gm2_mho=gm2_mho,
        r2_ohm=r2_ohm,
        cl_pf=cl_pf,
    )
    sch.save(output_path)
    return sch.build()


if __name__ == "__main__":
    out_dir = HARNESS_ROOT / "outputs"
    cmos_p = out_dir / "miller_ota.asc"
    generate_miller_ota_asc(cc_pf=7.0, target_gbw_mhz=10.0, output_path=cmos_p)
    print(f"Generated CMOS Miller OTA schematic at {cmos_p}")

    ss_p = out_dir / "small_signal_ota.asc"
    generate_small_signal_ota_asc(output_path=ss_p, cc_pf=7.0)
    print(f"Generated Small-Signal OTA schematic at {ss_p}")
