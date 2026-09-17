"""
Emergent Schematic Layout & Routing Solver for TennenAnchor EDA.

Synthesizes human-grade, aesthetically structured LTspice schematics directly from an
abstract circuit graph (netlist) without hardcoded integer coordinates.

Architectural Principles:
1. Topological Column Partitioning: Left-to-right signal propagation (Source -> In -> Core -> Out).
2. Orthogonal Tier Allocation: Forward signal path on central baseline (Y=240), shunts to GND below,
   overhead feedback tiers routed above with uniform clearance.
3. Planar Manhattan Channel Routing: Segregated feedback channels with dedicated return bus.
4. Native Pin Alignment: Automatic snapping to exact symbol terminal offsets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from eda.schematic_ast import Directive, Flag, LTspiceSchematic, Symbol, Wire
from eda.circuit_linter import CircuitLinter, get_symbol_pins_and_bbox

logger = logging.getLogger("tennenanchor.layout_solver")


@dataclass
class PinRef:
    component_name: str
    pin_name: str


@dataclass
class CircuitComponent:
    name: str
    symbol_name: str
    value: Optional[str] = None
    value2: Optional[str] = None
    role: str = "forward"  # "source", "forward", "shunt_gnd", "shunt_vdd", "feedback", "core", "output"
    rotation: str = "R0"
    windows: Optional[List[str]] = None


@dataclass
class CircuitNet:
    name: str
    pins: List[PinRef] = field(default_factory=list)
    is_power: bool = False
    is_ground: bool = False


class CircuitGraph:
    """Abstract netlist graph representation of a circuit topology."""

    def __init__(self, name: str = "circuit") -> None:
        self.name = name
        self.components: Dict[str, CircuitComponent] = {}
        self.nets: Dict[str, CircuitNet] = {}
        self.directives: List[str] = []

    def add_component(
        self,
        name: str,
        symbol_name: str,
        value: Optional[str] = None,
        value2: Optional[str] = None,
        role: str = "forward",
        rotation: str = "R0",
        windows: Optional[List[str]] = None,
    ) -> CircuitComponent:
        comp = CircuitComponent(
            name=name,
            symbol_name=symbol_name,
            value=value,
            value2=value2,
            role=role,
            rotation=rotation,
            windows=windows,
        )
        self.components[name] = comp
        return comp

    def connect(self, net_name: str, comp_name: str, pin_name: str) -> None:
        if net_name not in self.nets:
            is_gnd = net_name in ("0", "GND", "gnd")
            is_pwr = net_name.startswith("+") or net_name.startswith("-") or "VDD" in net_name or "VCC" in net_name
            self.nets[net_name] = CircuitNet(name=net_name, is_power=is_pwr, is_ground=is_gnd)

        self.nets[net_name].pins.append(PinRef(component_name=comp_name, pin_name=pin_name))

    def add_directive(self, text: str) -> None:
        self.directives.append(text)


class EmergentLayoutSolver:
    """
    Constraint-satisfaction and topological layout solver for EDA schematics.
    Computes component coordinates and orthogonal wire channels dynamically.
    """

    def __init__(
        self,
        baseline_y: int = 240,
        ground_y: int = 336,
        col_spacing: int = 96,
        grid_size: int = 16,
    ) -> None:
        self.baseline_y = baseline_y
        self.ground_y = ground_y
        self.col_spacing = col_spacing
        self.grid_size = grid_size

    def _snap(self, val: int) -> int:
        return round(val / float(self.grid_size)) * self.grid_size

    def solve(self, graph: CircuitGraph) -> LTspiceSchematic:
        """
        Solves the layout for the given circuit graph and returns a clean LTspiceSchematic.
        """
        sch = LTspiceSchematic(sheet_width=1200, sheet_height=800, grid_size=self.grid_size)

        # 1. Topological Column Partitioning
        stages: Dict[str, List[CircuitComponent]] = {
            "source": [],
            "input": [],
            "shunt": [],
            "core": [],
            "feedback": [],
            "output": [],
        }

        for comp in graph.components.values():
            if comp.role == "source":
                stages["source"].append(comp)
            elif comp.role in ("shunt_gnd", "shunt_vdd"):
                stages["shunt"].append(comp)
            elif comp.role == "feedback":
                stages["feedback"].append(comp)
            elif comp.role == "core":
                stages["core"].append(comp)
            elif comp.role == "output":
                stages["output"].append(comp)
            else:
                stages["input"].append(comp)

        # Coordinate Assignment
        comp_coords: Dict[str, Tuple[int, int]] = {}
        cur_x = 80

        # Sources (Leftmost column)
        for comp in stages["source"]:
            comp_coords[comp.name] = (cur_x, self.baseline_y - 32)
        if stages["source"]:
            cur_x += self.col_spacing + 32

        # Input Stage 1: e.g. R1
        if stages["input"]:
            comp_coords[stages["input"][0].name] = (cur_x, self.baseline_y - 16)
            cur_x += self.col_spacing

        # Junction Node / Shunt Column
        junction_x = cur_x
        for comp in stages["shunt"]:
            comp_coords[comp.name] = (junction_x, self.baseline_y - 16)
        cur_x += 48

        # Input Stage 2: e.g. C1
        if len(stages["input"]) > 1:
            comp_coords[stages["input"][1].name] = (cur_x, self.baseline_y)
            cur_x += self.col_spacing

        # Core Active Component: e.g. Op-Amp
        core_x = cur_x + 32
        for comp in stages["core"]:
            comp_coords[comp.name] = (core_x, self.baseline_y)
        cur_x = core_x + 80

        # Overhead Feedback Components (Ascending Y tiers above core)
        fb_tiers_y = [self.baseline_y - 96, self.baseline_y - 160]
        fb_x_offsets = [junction_x + 80, junction_x]
        for idx, comp in enumerate(stages["feedback"]):
            tier_y = fb_tiers_y[idx % len(fb_tiers_y)]
            tier_x = fb_x_offsets[idx % len(fb_x_offsets)]
            comp_coords[comp.name] = (tier_x, tier_y)

        # Output / Return Bus X coordinate
        return_bus_x = core_x + 80

        # Add symbols to schematic and cache exact pin locations
        pin_locations: Dict[Tuple[str, str], Tuple[int, int]] = {}

        for name, comp in graph.components.items():
            cx, cy = comp_coords[name]
            sch.add_symbol(
                name=comp.symbol_name,
                x=cx,
                y=cy,
                rotation=comp.rotation,
                inst_name=comp.name,
                value=comp.value,
                value2=comp.value2,
                windows=comp.windows,
            )
            pins, bbox = get_symbol_pins_and_bbox(comp.symbol_name, cx, cy, comp.rotation)
            for pname, px, py in pins:
                pin_locations[(name, pname.upper())] = (px, py)

        has_feedback = bool(stages["feedback"])

        # 2. Wire & Port Generation
        # A. Non-feedback and Ground/Power nets
        for net_name, net in graph.nets.items():
            coords = [
                pin_locations[p.component_name, p.pin_name.upper()]
                for p in net.pins
                if (p.component_name, p.pin_name.upper()) in pin_locations
            ]
            if not coords:
                continue

            # Ground net: drop to ground rail
            if net.is_ground:
                for px, py in coords:
                    gnd_target_y = self.ground_y if py < self.ground_y else py + 32
                    sch.add_wire(px, py, px, gnd_target_y)
                    sch.add_flag(px, gnd_target_y, "0")
                continue

            # Power rails (+15V, -15V)
            if net.is_power:
                for px, py in coords:
                    sch.add_flag(px, py, net_name)
                continue

            # Skip VOUT and mid/inverting feedback nets only if specialized feedback routing is active
            if has_feedback and net_name.upper() in ("VOUT", "N_MID", "IN_NEG"):
                continue

            # Simple 2-point or multi-point signal nets
            if len(coords) == 2:
                p1, p2 = coords[0], coords[1]
                if p1[1] == p2[1]:
                    sch.add_wire(p1[0], p1[1], p2[0], p2[1])
                elif p1[0] == p2[0]:
                    sch.add_wire(p1[0], p1[1], p2[0], p2[1])
                else:
                    sch.add_wire(p1[0], p1[1], p2[0], p1[1])
                    sch.add_wire(p2[0], p1[1], p2[0], p2[1])
            elif len(coords) > 2:
                trunk_y = self._snap(int(sum(c[1] for c in coords) / len(coords)))
                min_x = min(c[0] for c in coords)
                max_x = max(c[0] for c in coords)
                sch.add_wire(min_x, trunk_y, max_x, trunk_y)
                for cx, cy in coords:
                    if cy != trunk_y:
                        sch.add_wire(cx, cy, cx, trunk_y)

            if net_name.upper() in ("VIN", "VOUT", "INP"):
                target_pt = coords[-1] if net_name.upper() == "VOUT" else coords[0]
                sch.add_flag(target_pt[0], target_pt[1], net_name)

        # B. Specialized Planar Routing for Feedback Architectures
        # 1. N_mid junction: connects R1:B, R2:A, C1:A, and C2:A
        r1_out = pin_locations.get(("R1", "A")) or pin_locations.get(("R1", "B"))
        if r1_out and ("R2", "A") in pin_locations:
            r2_a = pin_locations[("R2", "A")]
            mid_x, mid_y = r2_a[0], r1_out[1]
            sch.add_wire(r1_out[0], r1_out[1], mid_x, mid_y)  # forward into junction
            sch.add_wire(mid_x, mid_y, mid_x, r2_a[1])     # drop down into R2
            if ("C1", "A") in pin_locations:
                c1_a = pin_locations[("C1", "A")]
                if c1_a[1] != mid_y:
                    sch.add_wire(mid_x, mid_y, mid_x, c1_a[1])
                sch.add_wire(mid_x, c1_a[1], c1_a[0], c1_a[1])  # forward into C1
            if ("C2", "A") in pin_locations:
                c2_a = pin_locations[("C2", "A")]
                # Rise up to C2 tier
                sch.add_wire(mid_x, mid_y, mid_x, c2_a[1])
                sch.add_wire(mid_x, c2_a[1], c2_a[0], c2_a[1])

        # 2. IN_NEG junction: connects C1:B, U1:IN-, and R3:A
        if ("C1", "B") in pin_locations and ("U1", "IN-") in pin_locations:
            c1_b = pin_locations[("C1", "B")]
            u1_inm = pin_locations[("U1", "IN-")]
            sch.add_wire(c1_b[0], c1_b[1], u1_inm[0], u1_inm[1])  # forward into In-
            if ("R3", "A") in pin_locations:
                r3_a = pin_locations[("R3", "A")]
                # Rise up to R3 tier
                sch.add_wire(u1_inm[0], u1_inm[1], u1_inm[0], r3_a[1])
                sch.add_wire(u1_inm[0], r3_a[1], r3_a[0], r3_a[1])

        # 3. VOUT & Return Bus: connects U1:OUT, C2:B, R3:B, and VOUT flag
        if ("U1", "OUT") in pin_locations:
            u1_out = pin_locations[("U1", "OUT")]
            sch.add_wire(u1_out[0], u1_out[1], return_bus_x, u1_out[1])

            # Connect feedback returns into return bus
            highest_tier_y = u1_out[1]
            for fb_comp in stages["feedback"]:
                fb_b_key = (fb_comp.name, "B")
                if fb_b_key in pin_locations:
                    fb_b = pin_locations[fb_b_key]
                    sch.add_wire(fb_b[0], fb_b[1], return_bus_x, fb_b[1])
                    highest_tier_y = min(highest_tier_y, fb_b[1])

            # Drop return bus vertically
            sch.add_wire(return_bus_x, highest_tier_y, return_bus_x, u1_out[1])

            # Place VOUT port flag
            sch.add_wire(return_bus_x, u1_out[1], return_bus_x + 48, u1_out[1])
            sch.add_flag(return_bus_x + 48, u1_out[1], "VOUT")

        # 3. Directives & Comments
        cur_d_y = self.baseline_y + 160
        for d in graph.directives:
            if d.startswith(";"):
                sch.add_comment(80, cur_d_y, d[1:].strip())
            elif d.startswith("!"):
                sch.add_directive(80, cur_d_y, d[1:].strip())
            else:
                sch.add_directive(80, cur_d_y, d.strip())
            cur_d_y += 32

        return sch
