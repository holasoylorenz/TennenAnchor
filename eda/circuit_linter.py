"""
Circuit Schematic Linter and Geometric Topology Validator for TennenAnchor EDA.
Provides design-rule checking for pin connectivity, AABB bounding box collision, and routing cleanliness.
"""

from core.circuit_linter import (
    BoundingBox,
    CircuitLinter,
    parse_asy_pins,
    get_symbol_pins_and_bbox,
)

__all__ = [
    "BoundingBox",
    "CircuitLinter",
    "parse_asy_pins",
    "get_symbol_pins_and_bbox",
]
