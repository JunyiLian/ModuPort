"""Configuration and public-API dispatch helpers for the Streamlit UI."""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Iterable, Mapping

from moduport import ModuPort

from .layout_editor import ModulePlacement, layout_expression


SECTION_NAMES = ("column", "floor_long", "floor_short", "ceiling_long", "ceiling_short")
LOAD_CASES = ("TH_UX", "TH_UY", "TH_RZ")


def synthetic_demo_config() -> dict[str, Any]:
    """Return synthetic software-demonstration data unrelated to research cases."""
    column = {"A_mm2": 12000.0, "Iy_mm4": 80000000.0, "Iz_mm4": 80000000.0, "J_mm4": 120000000.0}
    floor_beam = {"A_mm2": 5000.0, "Iy_mm4": 20000000.0, "Iz_mm4": 16000000.0, "J_mm4": 30000000.0}
    ceiling_beam = {"A_mm2": 4000.0, "Iy_mm4": 14000000.0, "Iz_mm4": 10000000.0, "J_mm4": 22000000.0}
    layout = "V(0,0)|H(0,1)|H(1,1)"
    return {
        "schema_version": "synthetic-ui-demo-1",
        "sample_id": "SYNTHETIC_SOFTWARE_DEMONSTRATION",
        "grid_rows": 2,
        "grid_cols": 3,
        "storey_count": 2,
        "storey_layouts": [layout, layout],
        "same_plan_layout_across_storeys": True,
        "coordinate_convention": "CELL_GRID_LOWER_LEFT_CANONICAL_V1",
        "units": {"force": "N", "length": "mm"},
        "reference_point": [4650.0, 3100.0],
        "module_geometry": {
            "long_outer_mm": 6100.0,
            "short_outer_mm": 3000.0,
            "long_centerline_mm": 5900.0,
            "short_centerline_mm": 2800.0,
            "clear_gap_mm": 100.0,
            "clear_storey_height_mm": 3000.0,
            "column_end_offset_mm": 100.0,
        },
        "material": {"E_N_mm2": 210000.0, "G_N_mm2": 80000.0, "density_kg_m3": 7800.0},
        "sections": {
            "column": column,
            "floor_long": floor_beam,
            "floor_short": {"A_mm2": 4800.0, "Iy_mm4": 18000000.0, "Iz_mm4": 15000000.0, "J_mm4": 28000000.0},
            "ceiling_long": ceiling_beam,
            "ceiling_short": {"A_mm2": 3800.0, "Iy_mm4": 12000000.0, "Iz_mm4": 9000000.0, "J_mm4": 20000000.0},
        },
        "reinforced_zone": {},
        "reinforced_zone_active": False,
        "arm": {"A_mm2": 3000.0, "Iy_mm4": 5000000.0, "Iz_mm4": 5000000.0, "J_mm4": 10000000.0},
        "horizontal_link": {"kx": 2000000.0, "ky": 2400000.0, "kz": 3000000.0, "kr1": 500000000.0, "kr2": 600000000.0, "kr3": 700000000.0},
        "vertical_link": {"kx": 5000000.0, "ky": 5500000.0, "kz": 6500000.0, "kr1": 200000000.0, "kr2": 250000000.0, "kr3": 300000000.0, "all_four_corners": True},
        "connection_kinematics_mode": "REFERENCE_PORT_DOF",
        "boundary": {"mode": "B0", "bot_corners_fixed": "U1/U2/U3", "bot_rotations": "released", "top_in_plane_rigid": True, "diaphragm": False},
        "loads": {"TH_UX": [1.0, 0.0, 0.0], "TH_UY": [0.0, 1.0, 0.0], "TH_RZ": [0.0, 0.0, 1.0]},
        "mass_model": "lumped",
    }


def assemble_config(values: Mapping[str, Any], placements: Iterable[ModulePlacement], sections: Mapping[str, Mapping[str, float]]) -> dict[str, Any]:
    layout = layout_expression(placements)
    storeys = int(values["storey_count"])
    return {
        "schema_version": str(values.get("schema_version", "ui-1")),
        "sample_id": str(values.get("sample_id", "USER_CONFIGURATION")),
        "grid_rows": int(values["grid_rows"]),
        "grid_cols": int(values["grid_cols"]),
        "storey_count": storeys,
        "storey_layouts": [layout] * storeys,
        "same_plan_layout_across_storeys": True,
        "coordinate_convention": "CELL_GRID_LOWER_LEFT_CANONICAL_V1",
        "units": {"force": "N", "length": "mm"},
        "reference_point": [float(values["reference_x_mm"]), float(values["reference_y_mm"])],
        "module_geometry": {
            "long_outer_mm": float(values["long_outer_mm"]),
            "short_outer_mm": float(values["short_outer_mm"]),
            "long_centerline_mm": float(values["long_centerline_mm"]),
            "short_centerline_mm": float(values["short_centerline_mm"]),
            "clear_gap_mm": float(values["clear_gap_mm"]),
            "clear_storey_height_mm": float(values["clear_storey_height_mm"]),
            "column_end_offset_mm": float(values["column_end_offset_mm"]),
        },
        "material": {
            "E_N_mm2": float(values["E_N_mm2"]),
            "G_N_mm2": float(values["G_N_mm2"]),
            "density_kg_m3": float(values["density_kg_m3"]),
        },
        "sections": {name: {key: float(value) for key, value in section.items()} for name, section in sections.items()},
        "reinforced_zone": {},
        "reinforced_zone_active": False,
        "arm": {key: float(values[f"arm_{key}"]) for key in ("A_mm2", "Iy_mm4", "Iz_mm4", "J_mm4")},
        "horizontal_link": {key: float(values[f"horizontal_{key}"]) for key in ("kx", "ky", "kz", "kr1", "kr2", "kr3")},
        "vertical_link": dict({key: float(values[f"vertical_{key}"]) for key in ("kx", "ky", "kz", "kr1", "kr2", "kr3")}, all_four_corners=True),
        "connection_kinematics_mode": "REFERENCE_PORT_DOF",
        "boundary": {"mode": "B0", "bot_corners_fixed": "U1/U2/U3", "bot_rotations": "released", "top_in_plane_rigid": True, "diaphragm": False},
        "loads": deepcopy(values.get("loads", {"TH_UX": [1.0, 0.0, 0.0], "TH_UY": [0.0, 1.0, 0.0], "TH_RZ": [0.0, 0.0, 1.0]})),
        "mass_model": "lumped",
    }


def config_to_json(config: Mapping[str, Any]) -> str:
    return json.dumps(config, indent=2, sort_keys=True, allow_nan=False)


def config_from_json(payload: str | bytes) -> dict[str, Any]:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("configuration JSON root must be an object")
    return value


def execute_analysis(config: Mapping[str, Any], analysis: str, static_cases: list[str], num_modes: int) -> dict[str, Any]:
    model = ModuPort(config)
    output: dict[str, Any] = {}
    if analysis in {"Static", "Both"}:
        output["static"] = model.solve_static(static_cases).to_dict()
    if analysis in {"Modal", "Both"}:
        output["modal"] = model.solve_modal(num_modes=num_modes).to_dict()
    return output


__all__ = [
    "SECTION_NAMES",
    "LOAD_CASES",
    "synthetic_demo_config",
    "assemble_config",
    "config_to_json",
    "config_from_json",
    "execute_analysis",
]
