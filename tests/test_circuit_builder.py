"""
Unit tests for core/circuit_builder.py:
Verifies LTspice schematic layout engine, grid-snapping invariants,
symbol orientations, and circuit topology synthesis.
"""

import pytest
from pathlib import Path
from core.circuit_builder import (
    LTspiceSchematic,
    build_cmos_miller_ota_schematic,
    build_small_signal_miller_schematic,
)


def test_schematic_grid_snapping():
    """Ensures all wire coordinates and symbol locations snap to the 16-pixel grid."""
    sch = LTspiceSchematic()
    # Add non-snapped coordinates (e.g. 15 -> 16, 33 -> 32)
    sch.add_wire(15, 33, 47, 65)
    assert len(sch.wires) == 1
    w = sch.wires[0]
    assert w.x1 % 16 == 0
    assert w.y1 % 16 == 0
    assert w.x2 % 16 == 0
    assert w.y2 % 16 == 0
    assert (w.x1, w.y1, w.x2, w.y2) == (16, 32, 48, 64)


def test_zero_length_wire_suppression():
    """Ensures zero-length wires (after snapping) are pruned."""
    sch = LTspiceSchematic()
    sch.add_wire(16, 32, 16, 32)
    assert len(sch.wires) == 0


def test_symbol_serialization():
    """Verifies symbol formatting conforms to LTspice Version 4 syntax."""
    sch = LTspiceSchematic()
    sch.add_symbol("pmos", 96, 208, rotation="M180", inst_name="M1", value="PMOS", value2="W=25u L=1u")
    content = sch.build()
    assert "SYMBOL pmos 96 208 M180" in content
    assert "SYMATTR InstName M1" in content
    assert "SYMATTR Value PMOS" in content
    assert "SYMATTR Value2 W=25u L=1u" in content


def test_cmos_miller_ota_synthesis():
    """
    Verifies the synthesized Two-Stage CMOS Miller OTA has:
    - Orthogonal VDD and GND rails
    - Complete transistor suite (M1 to M8) with real symbols
    - Both PMOS and NMOS components
    - Parametric Cc and CL values
    - Collision-free simulation directive block
    """
    sch = build_cmos_miller_ota_schematic(cc_pf=3.5, target_gbw_mhz=20.0, cl_pf=4.0)
    asc_text = sch.build()

    # Check Rails
    assert "FLAG 112 96 VDD" in asc_text
    assert "FLAG 112 640 0" in asc_text

    # Check Transistors
    for inst in ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8"]:
        assert f"SYMATTR InstName {inst}" in asc_text

    # PMOS loads should use M180 for vertical supply orientation
    assert "SYMBOL pmos 224 208 M180" in asc_text
    assert "SYMBOL pmos 336 208 M180" in asc_text
    assert "SYMBOL pmos 496 208 M180" in asc_text

    # Check Capacitors
    assert "SYMATTR InstName Cc" in asc_text
    assert "SYMATTR Value 3.5p" in asc_text
    assert "SYMATTR InstName CL" in asc_text
    assert "SYMATTR Value 4.0p" in asc_text

    # Check Directives
    assert "!.ac dec 50 10 1G" in asc_text
    assert "!.meas AC A0" in asc_text
    assert "!.meas AC GBW" in asc_text
    assert "!.model NMOS" in asc_text
    assert "!.model PMOS" in asc_text


def test_small_signal_miller_synthesis():
    """
    Verifies small-signal schematic synthesis:
    - Models the user's nodal equations directly
    - Voltage controlled current sources (G1, G2)
    - Equivalent resistors (R1, R2) and caps (C1, CL, Cc)
    """
    sch = build_small_signal_miller_schematic(
        gm1_mho=1.5e-3,
        r1_ohm=80e3,
        c1_pf=0.4,
        cc_pf=2.5,
        gm2_mho=3.0e-3,
        r2_ohm=40e3,
        cl_pf=5.0,
    )
    asc_text = sch.build()

    # Check Dependent Current Sources (R180 orientation for downward current pull)
    assert "SYMBOL g 224 272 R180" in asc_text
    assert "SYMATTR InstName G1" in asc_text
    assert "SYMATTR Value 0.0015" in asc_text

    assert "SYMBOL g 544 272 R180" in asc_text
    assert "SYMATTR InstName G2" in asc_text
    assert "SYMATTR Value 0.003" in asc_text

    # Check Passives
    assert "SYMATTR InstName R1" in asc_text
    assert "SYMATTR Value 80.0k" in asc_text
    assert "SYMATTR InstName C1" in asc_text
    assert "SYMATTR Value 0.4p" in asc_text
    assert "SYMATTR InstName Cc" in asc_text
    assert "SYMATTR Value 2.5p" in asc_text
    assert "SYMATTR InstName R2" in asc_text
    assert "SYMATTR Value 40.0k" in asc_text
    assert "SYMATTR InstName CL" in asc_text
    assert "SYMATTR Value 5.0p" in asc_text

    # Check Flags
    assert "FLAG 112 176 VIN" in asc_text
    assert "FLAG 304 176 V1" in asc_text
    assert "FLAG 672 176 VOUT" in asc_text
    assert "FLAG 80 512 0" in asc_text

    # Check Nodal equation comment header
    assert "Node 1: gm1*vin + v1/R1 + s*C1*v1 + s*Cc*(v1 - vout) = 0" in asc_text
    assert "Node 2: gm2*v1 + vout/R2 + s*CL*vout + s*Cc*(vout - v1) = 0" in asc_text


def _transform_pin(x0: int, y0: int, px: int, py: int, rotation: str) -> tuple[int, int]:
    """Applies LTspice symbol rotation/mirroring matrix to pin offset."""
    match rotation:
        case "R0":
            return (x0 + px, y0 + py)
        case "R90":
            return (x0 - py, y0 + px)
        case "R180":
            return (x0 - px, y0 - py)
        case "R270":
            return (x0 + py, y0 - px)
        case "M0":
            return (x0 - px, y0 + py)
        case "M90":
            return (x0 - py, y0 - px)
        case "M180":
            return (x0 + px, y0 - py)
        case "M270":
            return (x0 + py, y0 + px)
        case _:
            raise ValueError(f"Unknown rotation {rotation}")


def _point_intersects_schematic(x: int, y: int, sch: LTspiceSchematic) -> bool:
    """Checks if a point (pin location) lies on a wire segment or flag."""
    for w in sch.wires:
        if w.x1 == w.x2 == x and min(w.y1, w.y2) <= y <= max(w.y1, w.y2):
            return True
        if w.y1 == w.y2 == y and min(w.x1, w.x2) <= x <= max(w.x1, w.x2):
            return True
    for f in sch.flags:
        if f.x == x and f.y == y:
            return True
    return False


def test_cmos_and_small_signal_pin_connectivity():
    """
    Rigorously verifies electrical connectivity:
    Every pin of every transistor, passive, and source in both schematics
    must intersect at least one wire segment or net flag. Zero floating pins.
    """
    # Pin definitions in local symbol space (px, py)
    KNOWN_PINS = {
        "nmos": [(48, 0), (0, 80), (48, 96)],      # Drain, Gate, Source
        "pmos": [(48, 96), (0, 80), (48, 0)],      # Source (at Y-96 in M180), Gate, Drain
        "cap": [(16, 0), (16, 64)],
        "res": [(16, 16), (16, 96)],
        "voltage": [(0, 16), (0, 96)],
        "current": [(0, 0), (0, 80)],
        "g": [(0, 96), (0, 16), (-48, 32), (-48, 80)],  # Out+, Out-, NC+, NC-
    }

    schematics = [
        ("CMOS Miller OTA", build_cmos_miller_ota_schematic()),
        ("Small-Signal Miller OTA", build_small_signal_miller_schematic()),
    ]

    for sch_name, sch in schematics:
        for sym in sch.symbols:
            pins = KNOWN_PINS.get(sym.name)
            assert pins is not None, f"Untracked symbol type {sym.name} in {sch_name}"
            for px, py in pins:
                abs_x, abs_y = _transform_pin(sym.x, sym.y, px, py, sym.rotation)
                connected = _point_intersects_schematic(abs_x, abs_y, sch)
                assert connected, (
                    f"Floating pin detected in {sch_name}: {sym.inst_name} ({sym.name}) "
                    f"at absolute ({abs_x}, {abs_y}) [offset ({px}, {py}), rot {sym.rotation}]"
                )
