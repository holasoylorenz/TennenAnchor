"""
Unit tests for eda/layout_solver.py:
Verifies constraint-based emergent layout synthesis, topological column allocation,
Manhattan channel routing, and design-rule verification with CircuitLinter.
"""

from pathlib import Path
import pytest

from eda.layout_solver import CircuitGraph, EmergentLayoutSolver
from eda.circuit_linter import CircuitLinter


def test_layout_solver_rc_filter(tmp_path):
    """Verifies synthesis of a clean low-pass RC filter from an abstract netlist."""
    g = CircuitGraph(name="rc_lowpass")

    # Components
    g.add_component("Vin", "voltage", value="0", value2="AC 1", role="source", rotation="R0")
    g.add_component("R1", "res", value="10k", role="input", rotation="R90")
    g.add_component("C1", "cap", value="100n", role="shunt_gnd", rotation="R0")

    # Connections
    g.connect("VIN", "Vin", "+")
    g.connect("0", "Vin", "-")
    g.connect("VIN", "R1", "A")
    g.connect("VOUT", "R1", "B")
    g.connect("VOUT", "C1", "A")
    g.connect("0", "C1", "B")

    g.add_directive("!.ac dec 50 1 100k")

    solver = EmergentLayoutSolver()
    sch = solver.solve(g)

    out_file = tmp_path / "rc_filter_solved.asc"
    sch.save(out_file)
    assert out_file.exists()

    # Lint the generated schematic
    linter = CircuitLinter()
    res = linter.lint_file(out_file)

    assert res["status"] == "ok"
    assert res["components_count"] == 3
    assert len(res["collisions"]) == 0
    assert len(res["unconnected_pins"]) == 0
    assert res["quality_score"] == 100
    assert res["is_clean"] is True


def test_layout_solver_bandpass_filter(tmp_path):
    """Verifies synthesis of an active Multiple-Feedback (MFB) Bandpass Filter."""
    g = CircuitGraph(name="bandpass_filter_emergent")

    g.add_component("Vin", "voltage", value="0", value2="AC 1", role="source", rotation="R0")
    g.add_component("R1", "res", value="10k", role="input", rotation="R90")
    g.add_component("R2", "res", value="1.5k", role="shunt_gnd", rotation="R0")
    g.add_component("C1", "cap", value="10n", role="input", rotation="R270")
    g.add_component("U1", "OpAmps/UniversalOpAmp2", role="core", rotation="R0")
    g.add_component("C2", "cap", value="10n", role="feedback", rotation="R270")
    g.add_component("R3", "res", value="47k", role="feedback", rotation="R90")

    g.connect("VIN", "Vin", "+")
    g.connect("0", "Vin", "-")
    g.connect("VIN", "R1", "B")
    g.connect("N_mid", "R1", "A")
    g.connect("N_mid", "R2", "A")
    g.connect("0", "R2", "B")
    g.connect("N_mid", "C1", "A")
    g.connect("IN_NEG", "C1", "B")
    g.connect("IN_NEG", "U1", "IN-")
    g.connect("0", "U1", "IN+")
    g.connect("VOUT", "U1", "OUT")
    g.connect("+15V", "U1", "V+")
    g.connect("-15V", "U1", "V-")
    g.connect("N_mid", "C2", "A")
    g.connect("VOUT", "C2", "B")
    g.connect("IN_NEG", "R3", "A")
    g.connect("VOUT", "R3", "B")

    g.add_directive(";MFB Active Bandpass Filter (f0 = 1.0 kHz, Q = 2.0)")
    g.add_directive("!.ac dec 50 10 100k")
    g.add_directive("!.meas AC f_center MAX mag(V(VOUT))")
    g.add_directive("!.meas AC gain_peak MAX mag(V(VOUT)/V(VIN))")

    solver = EmergentLayoutSolver()
    sch = solver.solve(g)

    out_file = tmp_path / "bandpass_solved.asc"
    sch.save(out_file)
    assert out_file.exists()

    linter = CircuitLinter()
    res = linter.lint_file(out_file)

    assert res["status"] == "ok"
    assert res["components_count"] == 7
    assert len(res["collisions"]) == 0
    assert len(res["unconnected_pins"]) == 0
    assert res["quality_score"] == 100
    assert res["is_clean"] is True
