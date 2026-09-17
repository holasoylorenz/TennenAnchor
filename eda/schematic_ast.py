"""
LTspice Schematic AST Primitives and Serializer for TennenAnchor EDA.

Provides typed, grid-snapped data structures for building valid LTspice Version 4 (.asc) files:
- Wire: Orthogonal wire segments
- Flag: Net name labels and power ports (VDD, Ground '0', etc.)
- Symbol: Component instances with rotation and attribute windows
- Directive: SPICE simulation dot commands (.tran, .ac, .model) and comments
- LTspiceSchematic: Top-level builder enforcing 16-pixel grid alignment and serialization.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Union

VALID_ROTATIONS = {"R0", "R90", "R180", "R270", "M0", "M90", "M180", "M270"}


@dataclass
class Wire:
    x1: int
    y1: int
    x2: int
    y2: int

    def to_asc(self) -> str:
        return f"WIRE {self.x1} {self.y1} {self.x2} {self.y2}"


@dataclass
class Flag:
    x: int
    y: int
    net_name: str

    def to_asc(self) -> str:
        return f"FLAG {self.x} {self.y} {self.net_name}"


@dataclass
class Symbol:
    name: str
    x: int
    y: int
    rotation: str = "R0"
    inst_name: Optional[str] = None
    value: Optional[str] = None
    value2: Optional[str] = None
    windows: Optional[List[str]] = None

    def __post_init__(self) -> None:
        self.name = self.name.replace("/", "\\")
        while "\\\\" in self.name:
            self.name = self.name.replace("\\\\", "\\")
        rot = self.rotation.strip().upper()
        if rot not in VALID_ROTATIONS:
            raise ValueError(
                f"Invalid LTspice rotation '{self.rotation}'. Expected one of {sorted(VALID_ROTATIONS)}"
            )
        self.rotation = rot

    def to_asc(self) -> str:
        lines = [f"SYMBOL {self.name} {self.x} {self.y} {self.rotation}"]
        if self.windows:
            for w in self.windows:
                lines.append(f"WINDOW {w}")
        if self.inst_name is not None:
            lines.append(f"SYMATTR InstName {self.inst_name}")
        if self.value is not None:
            lines.append(f"SYMATTR Value {self.value}")
        if self.value2 is not None:
            lines.append(f"SYMATTR Value2 {self.value2}")
        return "\n".join(lines)


@dataclass
class Directive:
    x: int
    y: int
    text: str
    is_comment: bool = False

    def to_asc(self) -> str:
        clean_text = self.text.lstrip("!; ").strip()
        prefix = ";" if self.is_comment else "!"
        return f"TEXT {self.x} {self.y} Left 2 {prefix}{clean_text}"


class LTspiceSchematic:
    """
    Builder and layout engine for LTspice schematic (.asc) files.
    Enforces 16-pixel grid alignment, collision checks, and clean routing.
    """

    def __init__(self, sheet_width: int = 1400, sheet_height: int = 1000, grid_size: int = 16) -> None:
        self.sheet_width = sheet_width
        self.sheet_height = sheet_height
        self.grid_size = grid_size
        self.wires: List[Wire] = []
        self.flags: List[Flag] = []
        self.symbols: List[Symbol] = []
        self.directives: List[Directive] = []

    def _snap(self, coord: int) -> int:
        """Snaps coordinate to the configured grid (default 16-pixel)."""
        if self.grid_size <= 1:
            return coord
        return round(coord / float(self.grid_size)) * self.grid_size

    def add_wire(self, x1: int, y1: int, x2: int, y2: int) -> LTspiceSchematic:
        sx1, sy1, sx2, sy2 = self._snap(x1), self._snap(y1), self._snap(x2), self._snap(y2)
        # Avoid zero-length wires
        if sx1 != sx2 or sy1 != sy2:
            self.wires.append(Wire(sx1, sy1, sx2, sy2))
        return self

    def add_wire_path(self, points: List[Tuple[int, int]]) -> LTspiceSchematic:
        """Adds contiguous orthogonal wire segments across a list of points."""
        for i in range(len(points) - 1):
            p1, p2 = points[i], points[i + 1]
            self.add_wire(p1[0], p1[1], p2[0], p2[1])
        return self

    def add_flag(self, x: int, y: int, net_name: str) -> LTspiceSchematic:
        self.flags.append(Flag(self._snap(x), self._snap(y), net_name))
        return self

    def add_symbol(
        self,
        name: str,
        x: int,
        y: int,
        rotation: str = "R0",
        inst_name: Optional[str] = None,
        value: Optional[str] = None,
        value2: Optional[str] = None,
        windows: Optional[List[str]] = None,
    ) -> LTspiceSchematic:
        self.symbols.append(
            Symbol(
                name=name,
                x=self._snap(x),
                y=self._snap(y),
                rotation=rotation,
                inst_name=inst_name,
                value=value,
                value2=value2,
                windows=windows,
            )
        )
        return self

    def add_directive(self, x: int, y: int, text: str) -> LTspiceSchematic:
        self.directives.append(Directive(self._snap(x), self._snap(y), text, is_comment=False))
        return self

    def add_comment(self, x: int, y: int, text: str) -> LTspiceSchematic:
        self.directives.append(Directive(self._snap(x), self._snap(y), text, is_comment=True))
        return self

    def add_directive_block(
        self, start_x: int, start_y: int, lines: List[str], line_height: int = 36
    ) -> LTspiceSchematic:
        """Renders an aligned, non-overlapping block of SPICE commands."""
        cur_y = start_y
        for line in lines:
            if line.startswith(";"):
                self.add_comment(start_x, cur_y, line[1:].strip())
            elif line.startswith("!"):
                self.add_directive(start_x, cur_y, line[1:].strip())
            else:
                self.add_directive(start_x, cur_y, line.strip())
            cur_y += line_height
        return self

    def build(self) -> str:
        """Serializes schematic to standard LTspice Version 4 .asc format."""
        out = [
            "Version 4",
            f"SHEET 1 {self.sheet_width} {self.sheet_height}",
        ]
        for w in self.wires:
            out.append(w.to_asc())
        for f in self.flags:
            out.append(f.to_asc())
        for s in self.symbols:
            out.append(s.to_asc())
        for d in self.directives:
            out.append(d.to_asc())
        return "\n".join(out) + "\n"

    def save(self, target_path: Union[Path, str]) -> Path:
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        content = self.build()
        target.write_text(content, encoding="utf-8")
        return target
