"""External guard for the validated rectangular and irregular public domain."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import math
from typing import Any

from ._bootstrap import install
from .exceptions import ConfigurationError, UnsupportedConfigurationError


COORDINATE_CONVENTION = "CELL_GRID_LOWER_LEFT_CANONICAL_V1"
REQUIRED_FIELDS = {
    "grid_rows",
    "grid_cols",
    "storey_count",
    "storey_layouts",
    "coordinate_convention",
    "module_geometry",
    "material",
    "sections",
    "reinforced_zone",
    "arm",
    "horizontal_link",
    "vertical_link",
    "connection_kinematics_mode",
    "boundary",
    "loads",
    "mass_model",
    "reinforced_zone_active",
    "same_plan_layout_across_storeys",
}
SECTION_NAMES = {"column", "floor_long", "floor_short", "ceiling_long", "ceiling_short"}
STATIC_CASES = {"TH_UX", "TH_UY", "TH_RZ"}


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{name} must be a mapping")
    return dict(value)


def _finite_number(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ConfigurationError(f"{name} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ConfigurationError(f"{name} must be numeric") from error
    if not math.isfinite(number) or (positive and number <= 0.0):
        condition = "finite and positive" if positive else "finite"
        raise ConfigurationError(f"{name} must be {condition}")
    return number


def _require_numeric_keys(mapping: Mapping[str, Any], name: str, keys: set[str]) -> None:
    missing = sorted(keys - set(mapping))
    if missing:
        raise ConfigurationError(f"{name} missing required fields: {', '.join(missing)}")
    for key in keys:
        _finite_number(mapping[key], f"{name}.{key}", positive=True)


def _canonical_layout(layout: str) -> tuple[str, ...]:
    return tuple(sorted(token.strip() for token in layout.split("|") if token.strip()))


def _occupied_cells(value: Any, rows: int, columns: int) -> tuple[tuple[int, int], ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ConfigurationError("occupied_cells must be a non-empty list of (row, column) pairs")
    cells: list[tuple[int, int]] = []
    for index, cell in enumerate(value):
        if not isinstance(cell, (list, tuple)) or len(cell) != 2:
            raise ConfigurationError(f"occupied_cells[{index}] must be a (row, column) pair")
        row, column = cell
        if isinstance(row, bool) or isinstance(column, bool) or not isinstance(row, int) or not isinstance(column, int):
            raise ConfigurationError(f"occupied_cells[{index}] coordinates must be integers")
        if not (0 <= row < rows and 0 <= column < columns):
            raise UnsupportedConfigurationError(f"occupied_cells[{index}] is outside the declared grid")
        cells.append((row, column))
    if len(cells) != len(set(cells)):
        raise ConfigurationError("occupied_cells must not contain duplicate cells")
    if len(cells) % 2:
        raise UnsupportedConfigurationError("occupied_cells must contain an even number of cells")

    domain = set(cells)
    visited = {next(iter(domain))}
    frontier = list(visited)
    while frontier:
        row, column = frontier.pop()
        for neighbor in ((row - 1, column), (row + 1, column), (row, column - 1), (row, column + 1)):
            if neighbor in domain and neighbor not in visited:
                visited.add(neighbor)
                frontier.append(neighbor)
    if visited != domain:
        raise UnsupportedConfigurationError("occupied_cells must form one four-neighbour connected component")
    return tuple(sorted(domain))


def _validate_footprint_layout(layout: Any, occupied: tuple[tuple[int, int], ...], rows: int, columns: int) -> None:
    domain = set(occupied)
    covered: list[tuple[int, int]] = []
    for placement in layout:
        cells = tuple(placement.cells)
        if len(cells) != 2:
            raise UnsupportedConfigurationError("each module must occupy exactly two cells")
        if any(not (0 <= row < rows and 0 <= column < columns) for row, column in cells):
            raise UnsupportedConfigurationError("module cell is outside the declared grid")
        delta_row = abs(cells[0][0] - cells[1][0])
        delta_column = abs(cells[0][1] - cells[1][1])
        expected = "H" if delta_row == 0 and delta_column == 1 else "V" if delta_row == 1 and delta_column == 0 else None
        if expected is None or placement.orientation != expected:
            raise UnsupportedConfigurationError("modules must be orthogonal 1x2 or 2x1 dominoes with matching H/V orientation")
        if any(cell not in domain for cell in cells):
            raise UnsupportedConfigurationError("module occupies a void cell outside occupied_cells")
        covered.extend(cells)
    if len(covered) != len(set(covered)):
        raise UnsupportedConfigurationError("storey layout contains overlapping modules")
    if set(covered) != domain:
        raise UnsupportedConfigurationError("storey layout does not exactly cover occupied_cells")


def _occupied_centroid(occupied: tuple[tuple[int, int], ...], geometry: Mapping[str, Any]) -> list[float]:
    pitch = float(geometry["short_outer_mm"]) + float(geometry["clear_gap_mm"])
    return [
        sum((column + 0.5) * pitch for row, column in occupied) / len(occupied),
        sum((row + 0.5) * pitch for row, column in occupied) / len(occupied),
    ]


def validate_config(config: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(config, Mapping):
        raise ConfigurationError("config must be a Python mapping")
    data = deepcopy(dict(config))
    missing = sorted(REQUIRED_FIELDS - set(data))
    if "occupied_cells" not in data and "reference_point" not in data:
        missing.append("reference_point")
    if missing:
        raise ConfigurationError("missing required fields: " + ", ".join(missing))

    if isinstance(data["grid_rows"], bool) or not isinstance(data["grid_rows"], int) or data["grid_rows"] <= 0:
        raise ConfigurationError("grid_rows must be a positive integer")
    if isinstance(data["grid_cols"], bool) or not isinstance(data["grid_cols"], int) or data["grid_cols"] <= 0:
        raise ConfigurationError("grid_cols must be a positive integer")
    if isinstance(data["storey_count"], bool) or not isinstance(data["storey_count"], int) or data["storey_count"] <= 0:
        raise ConfigurationError("storey_count must be a positive integer")

    layouts = data["storey_layouts"]
    if not isinstance(layouts, list) or not layouts or any(not isinstance(item, str) or not item.strip() for item in layouts):
        raise ConfigurationError("storey_layouts must be a non-empty list of strings")
    if len(layouts) != data["storey_count"]:
        raise UnsupportedConfigurationError("storey_count must equal the number of storey_layouts")
    signatures = [_canonical_layout(layout) for layout in layouts]
    if any(signature != signatures[0] for signature in signatures[1:]):
        raise UnsupportedConfigurationError("all storey layouts must be exactly identical in the validated public domain")
    if data["same_plan_layout_across_storeys"] is not True:
        raise UnsupportedConfigurationError("same_plan_layout_across_storeys must be true")

    occupied = None
    if "occupied_cells" in data:
        occupied = _occupied_cells(data["occupied_cells"], data["grid_rows"], data["grid_cols"])
        data["occupied_cells"] = [list(cell) for cell in occupied]

    state = install()
    parser = __import__("mscsolver._layout_parser_legacy", fromlist=["parse_layout", "validate_layout"])
    try:
        parsed = parser.parse_layout(layouts[0])
        if occupied is None:
            legal, reason = parser.validate_layout(parsed, data["grid_rows"], data["grid_cols"])
        else:
            _validate_footprint_layout(parsed, occupied, data["grid_rows"], data["grid_cols"])
            legal, reason = True, ""
    except (ConfigurationError, UnsupportedConfigurationError):
        raise
    except Exception as error:
        raise ConfigurationError(f"invalid storey layout syntax: {error}") from error
    if not legal:
        raise UnsupportedConfigurationError(f"storey layout is not an exact domino covering: {reason}")

    if data["coordinate_convention"] != COORDINATE_CONVENTION:
        raise UnsupportedConfigurationError(f"coordinate_convention must be {COORDINATE_CONVENTION}")
    units = data.get("units", {"force": "N", "length": "mm"})
    if units not in ({"force": "N", "length": "mm"}, {"length": "mm", "force": "N"}):
        raise UnsupportedConfigurationError("only the N-mm unit convention is supported")
    if data["mass_model"] != "lumped":
        raise UnsupportedConfigurationError("only the validated lumped mass formulation is supported")
    if data.get("analysis_type", "linear_elastic") != "linear_elastic":
        raise UnsupportedConfigurationError("only linear_elastic analysis is supported")
    if data["connection_kinematics_mode"] != "REFERENCE_PORT_DOF":
        raise UnsupportedConfigurationError("connection_kinematics_mode must be REFERENCE_PORT_DOF")
    if data["reinforced_zone_active"] is not False:
        raise UnsupportedConfigurationError("reinforced zones are outside the validated public domain")
    if "backend" in data:
        raise UnsupportedConfigurationError("backend selection is not public; the validated numerical backend is fixed")

    boundary = _mapping(data["boundary"], "boundary")
    expected_boundary = {
        "mode": "B0",
        "bot_corners_fixed": "U1/U2/U3",
        "bot_rotations": "released",
        "top_in_plane_rigid": True,
        "diaphragm": False,
    }
    for key, expected in expected_boundary.items():
        if boundary.get(key) != expected:
            raise UnsupportedConfigurationError(f"boundary.{key} must be {expected!r}")

    geometry = _mapping(data["module_geometry"], "module_geometry")
    _require_numeric_keys(
        geometry,
        "module_geometry",
        {"long_outer_mm", "short_outer_mm", "long_centerline_mm", "short_centerline_mm", "clear_gap_mm", "clear_storey_height_mm", "column_end_offset_mm"},
    )
    reference = data.get("reference_point")
    if reference is None and occupied is not None:
        data["reference_point"] = _occupied_centroid(occupied, geometry)
        reference = data["reference_point"]
    if not isinstance(reference, (list, tuple)) or len(reference) != 2:
        raise ConfigurationError("reference_point must contain two coordinates")
    for index, value in enumerate(reference):
        _finite_number(value, f"reference_point[{index}]")
    material = _mapping(data["material"], "material")
    _require_numeric_keys(material, "material", {"E_N_mm2", "G_N_mm2", "density_kg_m3"})
    sections = _mapping(data["sections"], "sections")
    if set(sections) != SECTION_NAMES:
        raise ConfigurationError("sections must contain exactly: " + ", ".join(sorted(SECTION_NAMES)))
    for section_name, section in sections.items():
        _require_numeric_keys(_mapping(section, f"sections.{section_name}"), f"sections.{section_name}", {"A_mm2", "Iy_mm4", "Iz_mm4", "J_mm4"})
    _mapping(data["reinforced_zone"], "reinforced_zone")
    _require_numeric_keys(_mapping(data["arm"], "arm"), "arm", {"A_mm2", "Iy_mm4", "Iz_mm4", "J_mm4"})

    connection_module = __import__("_moduport_frozen.connection_stiffness", fromlist=["resolve_horizontal_connection", "resolve_vertical_connection"])
    try:
        connection_module.resolve_horizontal_connection(_mapping(data["horizontal_link"], "horizontal_link"))
        connection_module.resolve_vertical_connection(_mapping(data["vertical_link"], "vertical_link"))
    except (TypeError, ValueError) as error:
        raise ConfigurationError(f"invalid connection stiffness: {error}") from error
    if _mapping(data["vertical_link"], "vertical_link").get("all_four_corners") is not True:
        raise UnsupportedConfigurationError("vertical_link.all_four_corners must be true")

    loads = _mapping(data["loads"], "loads")
    if set(loads) != STATIC_CASES:
        raise UnsupportedConfigurationError("loads must contain exactly TH_UX, TH_UY, and TH_RZ")
    for name, vector in loads.items():
        if not isinstance(vector, (list, tuple)) or len(vector) != 3:
            raise ConfigurationError(f"loads.{name} must contain three components")
        for index, value in enumerate(vector):
            _finite_number(value, f"loads.{name}[{index}]")

    solver_options = data.get("solver_options", {"symmetry_tolerance": 1e-10, "residual_tolerance": 1e-8})
    if solver_options != {"symmetry_tolerance": 1e-10, "residual_tolerance": 1e-8}:
        raise UnsupportedConfigurationError("custom solver_options are outside the validated public domain")
    return data


__all__ = ["validate_config"]
