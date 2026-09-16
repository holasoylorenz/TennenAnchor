"""
Circuit Schematic Linter and Geometric Topology Validator for TennenAnchor.
Validates LTspice (.asc) schematics against physical design rules:
- Pin connectivity (identifies floating / unconnected component pins)
- Symbol bounding box collisions (detects overlapping components)
- Wire-to-pin alignment
- Layout cleanliness score (0 to 100)
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class BoundingBox:
    x1: int
    y1: int
    x2: int
    y2: int

    def intersects(self, other: BoundingBox, margin: int = 4) -> bool:
        """Checks if two AABBs overlap, accounting for a tolerance margin."""
        return not (
            self.x2 - margin <= other.x1 or
            self.x1 + margin >= other.x2 or
            self.y2 - margin <= other.y1 or
            self.y1 + margin >= other.y2
        )


def parse_asy_pins(
    asy_path: Path, x: int, y: int, rot: str
) -> Tuple[List[Tuple[str, int, int]], BoundingBox]:
    """Parses pin coordinates directly from an LTspice symbol file (.asy)."""
    raw_pins: List[Tuple[str, int, int]] = []
    min_x, min_y, max_x, max_y = 0, 0, 32, 32
    if asy_path.exists():
        lines = asy_path.read_text(encoding="utf-8", errors="replace").splitlines()
        cur_pin_coord: Optional[Tuple[int, int]] = None
        for l in lines:
            parts = l.strip().split()
            if not parts:
                continue
            if parts[0].upper() == "PIN" and len(parts) >= 3:
                try:
                    px, py = int(parts[1]), int(parts[2])
                    cur_pin_coord = (px, py)
                except ValueError:
                    pass
            elif parts[0].upper() == "PINATTR" and len(parts) >= 3 and cur_pin_coord:
                if parts[1].upper() == "PINNAME":
                    pname = parts[2]
                    raw_pins.append((pname, cur_pin_coord[0], cur_pin_coord[1]))
                    cur_pin_coord = None
            elif parts[0].upper() == "RECTANGLE" and len(parts) >= 5:
                try:
                    rx1, ry1, rx2, ry2 = int(parts[2]), int(parts[3]), int(parts[4]), int(parts[5])
                    min_x = min(rx1, rx2)
                    min_y = min(ry1, ry2)
                    max_x = max(rx1, rx2)
                    max_y = max(ry1, ry2)
                except ValueError:
                    pass

    # Transform relative coords to screen coords based on rotation
    def rotate_point(px: int, py: int, rotation: str) -> Tuple[int, int]:
        r = rotation.upper()
        if r == "R0":
            return px, py
        elif r == "R90":
            return -py, px
        elif r == "R180":
            return -px, -py
        elif r == "R270":
            return py, -px
        elif r == "M0":
            return -px, py
        elif r == "M90":
            return -py, -px
        elif r == "M180":
            return px, -py
        elif r == "M270":
            return py, px
        return px, py

    transformed_pins = []
    for pname, px, py in raw_pins:
        dx, dy = rotate_point(px, py, rot)
        transformed_pins.append((pname, x + dx, y + dy))

    # Bounding box
    c1x, c1y = rotate_point(min_x, min_y, rot)
    c2x, c2y = rotate_point(max_x, max_y, rot)
    bbox = BoundingBox(x + min(c1x, c2x), y + min(c1y, c2y), x + max(c1x, c2x), y + max(c1y, c2y))
    return transformed_pins, bbox


def get_symbol_pins_and_bbox(
    name: str, x: int, y: int, rot: str = "R0", parent_dir: Optional[Path] = None
) -> Tuple[List[Tuple[str, int, int]], BoundingBox]:
    """
    Computes exact terminal pin coordinates and bounding box for standard LTspice symbols.
    Geometry extracted directly from native LTspice .asy library.
    """
    norm_name = name.lower().replace(".asy", "").split("\\")[-1]
    rot = rot.upper()
    pins: List[Tuple[str, int, int]] = []
    bbox = BoundingBox(x, y, x + 32, y + 32)

    # Check for local custom .asy first
    if parent_dir:
        asy_candidate = parent_dir / f"{norm_name}.asy"
        if not asy_candidate.exists():
            asy_candidate = parent_dir / f"{name}.asy"
        if asy_candidate.exists():
            return parse_asy_pins(asy_candidate, x, y, rot)

    if norm_name in ("voltage", "vsource", "bv"):
        if rot == "R0":
            pins = [("+", x, y + 16), ("-", x, y + 96)]
            bbox = BoundingBox(x - 32, y + 16, x + 32, y + 96)
        elif rot == "R90":
            pins = [("+", x - 16, y), ("-", x - 96, y)]
            bbox = BoundingBox(x - 96, y - 32, x - 16, y + 32)
        else:
            pins = [("+", x, y + 16), ("-", x, y + 96)]
            bbox = BoundingBox(x - 32, y, x + 32, y + 96)

    elif norm_name == "res":
        if rot == "R0":
            pins = [("A", x + 16, y + 16), ("B", x + 16, y + 96)]
            bbox = BoundingBox(x, y + 16, x + 32, y + 96)
        elif rot == "R90":
            pins = [("B", x - 96, y + 16), ("A", x - 16, y + 16)]
            bbox = BoundingBox(x - 96, y, x - 16, y + 32)
        elif rot == "R270":
            pins = [("A", x + 96, y - 16), ("B", x + 16, y - 16)]
            bbox = BoundingBox(x + 16, y - 32, x + 96, y)
        else:
            pins = [("A", x + 16, y + 16), ("B", x + 16, y + 96)]
            bbox = BoundingBox(x, y, x + 32, y + 96)

    elif norm_name in ("cap", "polcap"):
        if rot == "R0":
            pins = [("A", x + 16, y), ("B", x + 16, y + 64)]
            bbox = BoundingBox(x, y, x + 32, y + 64)
        elif rot == "R90":
            pins = [("A", x, y + 16), ("B", x - 64, y + 16)]
            bbox = BoundingBox(x - 64, y, x, y + 32)
        elif rot == "R270":
            pins = [("A", x, y - 16), ("B", x + 64, y - 16)]
            bbox = BoundingBox(x, y - 32, x + 64, y)
        else:
            pins = [("A", x + 16, y), ("B", x + 16, y + 64)]
            bbox = BoundingBox(x, y, x + 32, y + 64)

    elif norm_name in ("ind", "inductor"):
        if rot == "R0":
            pins = [("A", x + 16, y + 16), ("B", x + 16, y + 96)]
            bbox = BoundingBox(x, y + 16, x + 32, y + 96)
        elif rot == "R90":
            pins = [("A", x - 16, y + 16), ("B", x - 96, y + 16)]
            bbox = BoundingBox(x - 96, y, x - 16, y + 32)
        else:
            pins = [("A", x + 16, y + 16), ("B", x + 16, y + 96)]
            bbox = BoundingBox(x, y, x + 32, y + 96)

    elif norm_name in ("diode", "schottky"):
        if rot == "R0":
            pins = [("A", x, y), ("K", x, y + 64)]
            bbox = BoundingBox(x - 16, y, x + 16, y + 64)
        elif rot == "R90":
            pins = [("A", x, y), ("K", x - 64, y)]
            bbox = BoundingBox(x - 64, y - 16, x, y + 16)
        else:
            pins = [("A", x, y), ("K", x, y + 64)]
            bbox = BoundingBox(x - 16, y, x + 16, y + 64)

    elif norm_name in ("nmos", "pmos"):
        if rot == "R0":
            pins = [("D", x + 48, y), ("G", x, y + 80), ("S", x + 48, y + 96)]
            bbox = BoundingBox(x, y, x + 48, y + 96)
        elif rot in ("M180", "R180"):
            pins = [("S", x + 48, y - 96), ("G", x, y - 80), ("D", x + 48, y)]
            bbox = BoundingBox(x, y - 96, x + 48, y)
        else:
            pins = [("D", x + 48, y), ("G", x, y + 80), ("S", x + 48, y + 96)]
            bbox = BoundingBox(x, y, x + 48, y + 96)

    elif norm_name in ("npn", "bjt"):
        pins = [("C", x + 32, y), ("B", x, y + 48), ("E", x + 32, y + 96)]
        bbox = BoundingBox(x, y, x + 32, y + 96)

    elif norm_name == "pnp":
        pins = [("E", x + 32, y), ("B", x, y + 48), ("C", x + 32, y + 96)]
        bbox = BoundingBox(x, y, x + 32, y + 96)

    elif norm_name in ("current", "isource", "bi", "bi2"):
        pins = [("+", x, y + 16), ("-", x, y + 96)]
        bbox = BoundingBox(x - 32, y + 16, x + 32, y + 96)

    elif norm_name in ("g", "e"):
        # Voltage-controlled sources
        if rot == "R180":
            pins = [("Out+", x, y - 96), ("Out-", x, y - 16), ("NC+", x + 48, y - 32), ("NC-", x + 48, y - 80)]
        else:
            pins = [("Out+", x, y + 16), ("Out-", x, y + 96), ("NC+", x - 48, y + 80), ("NC-", x - 48, y + 32)]
        bbox = BoundingBox(x - 48, y, x + 48, y + 96)

    elif norm_name in ("sw", "switch"):
        pins = [("P1", x, y + 16), ("P2", x, y + 96), ("C1", x + 64, y + 16), ("C2", x + 64, y + 96)]
        bbox = BoundingBox(x, y + 16, x + 64, y + 96)

    elif "opamp" in norm_name:
        # Standard LTspice Op-Amp (UniversalOpAmp2, opamp2)
        pins = [
            ("IN+", x - 32, y + 16),
            ("IN-", x - 32, y - 16),
            ("V+", x, y - 32),
            ("V-", x, y + 32),
            ("OUT", x + 32, y),
        ]
        bbox = BoundingBox(x - 32, y - 32, x + 32, y + 32)

    else:
        # Generic block / IC symbol
        pins = [("P1", x, y), ("P2", x + 32, y + 32)]
        bbox = BoundingBox(x, y, x + 48, y + 48)

    return pins, bbox


def is_point_on_wire(px: int, py: int, x1: int, y1: int, x2: int, y2: int) -> bool:
    """Checks if point (px, py) lies on orthogonal wire segment (x1, y1) -> (x2, y2)."""
    if x1 == x2:  # Vertical wire
        if px == x1 and min(y1, y2) <= py <= max(y1, y2):
            return True
    elif y1 == y2:  # Horizontal wire
        if py == y1 and min(x1, x2) <= px <= max(x1, x2):
            return True
    return False


class CircuitLinter:
    """Evaluates schematic files (.asc) for electrical and geometric design rule violations."""

    def lint_file(self, asc_path: Union[Path, str]) -> Dict[str, Any]:
        p = Path(asc_path).resolve()
        if not p.exists():
            return {"status": "error", "error": f"File not found: {p}"}

        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()

        symbols: List[Dict[str, Any]] = []
        wires: List[Tuple[int, int, int, int]] = []
        flags: List[Tuple[int, int, str]] = []
        directives: List[str] = []

        current_sym: Optional[Dict[str, Any]] = None

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            parts = line_str.split()
            cmd = parts[0].upper()

            if cmd == "SYMBOL":
                if current_sym:
                    symbols.append(current_sym)
                name = parts[1]
                sx, sy = int(parts[2]), int(parts[3])
                rot = parts[4] if len(parts) > 4 else "R0"
                pins, bbox = get_symbol_pins_and_bbox(name, sx, sy, rot, parent_dir=p.parent)
                current_sym = {
                    "name": name,
                    "x": sx,
                    "y": sy,
                    "rotation": rot,
                    "inst_name": None,
                    "value": None,
                    "pins": pins,
                    "bbox": bbox,
                }
            elif cmd == "SYMATTR" and current_sym:
                if len(parts) >= 3:
                    attr_name = parts[1]
                    attr_val = " ".join(parts[2:])
                    if attr_name == "InstName":
                        current_sym["inst_name"] = attr_val
                    elif attr_name == "Value":
                        current_sym["value"] = attr_val
            elif cmd == "WIRE" and len(parts) >= 5:
                if current_sym:
                    symbols.append(current_sym)
                    current_sym = None
                wires.append((int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])))
            elif cmd == "FLAG" and len(parts) >= 4:
                if current_sym:
                    symbols.append(current_sym)
                    current_sym = None
                flags.append((int(parts[1]), int(parts[2]), parts[3]))
            elif cmd == "TEXT":
                if current_sym:
                    symbols.append(current_sym)
                    current_sym = None
                directives.append(line_str)

        if current_sym:
            symbols.append(current_sym)

        # 1. Connectivity Verification
        unconnected_pins: List[Dict[str, Any]] = []
        for sym in symbols:
            inst = sym["inst_name"] or sym["name"]
            for pin_name, px, py in sym["pins"]:
                # Check if this pin touches any wire segment
                connected = False
                for wx1, wy1, wx2, wy2 in wires:
                    if is_point_on_wire(px, py, wx1, wy1, wx2, wy2):
                        connected = True
                        break
                if not connected:
                    # Check if directly attached to a flag
                    for fx, fy, _ in flags:
                        if px == fx and py == fy:
                            connected = True
                            break

                if not connected:
                    unconnected_pins.append({
                        "component": inst,
                        "pin": pin_name,
                        "location": (px, py),
                    })

        # 2. Collision Detection (AABB bounding box intersections)
        collisions: List[Dict[str, Any]] = []
        for i in range(len(symbols)):
            for j in range(i + 1, len(symbols)):
                s1 = symbols[i]
                s2 = symbols[j]
                if s1["bbox"].intersects(s2["bbox"]):
                    collisions.append({
                        "component1": s1["inst_name"] or s1["name"],
                        "component2": s2["inst_name"] or s2["name"],
                        "bbox1": (s1["bbox"].x1, s1["bbox"].y1, s1["bbox"].x2, s1["bbox"].y2),
                        "bbox2": (s2["bbox"].x1, s2["bbox"].y1, s2["bbox"].x2, s2["bbox"].y2),
                    })

        # 3. Scoring
        total_pins = sum(len(s["pins"]) for s in symbols)
        pin_penalty = len(unconnected_pins) * 20
        collision_penalty = len(collisions) * 25
        score = max(0, 100 - pin_penalty - collision_penalty)
        is_clean = (len(unconnected_pins) == 0 and len(collisions) == 0)

        return {
            "status": "ok",
            "file": str(p),
            "is_clean": is_clean,
            "quality_score": score,
            "components_count": len(symbols),
            "wires_count": len(wires),
            "flags_count": len(flags),
            "total_pins": total_pins,
            "unconnected_pins": unconnected_pins,
            "collisions": collisions,
            "directives_count": len(directives),
        }
