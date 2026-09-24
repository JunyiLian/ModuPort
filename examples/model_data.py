"""Small synthetic configuration used by the public examples.

The values exercise the software only. They are not a research validation case.
"""

from __future__ import annotations

from copy import deepcopy


MIXED_LAYOUT = "V(0,0)|H(0,1)|H(1,1)"


def synthetic_config(*, storeys: int = 1) -> dict:
    if storeys < 1:
        raise ValueError("storeys must be positive")

    column = {"A_mm2": 12000.0, "Iy_mm4": 80000000.0, "Iz_mm4": 80000000.0, "J_mm4": 120000000.0}
    floor_long = {"A_mm2": 5000.0, "Iy_mm4": 20000000.0, "Iz_mm4": 16000000.0, "J_mm4": 30000000.0}
    ceiling_long = {"A_mm2": 4000.0, "Iy_mm4": 14000000.0, "Iz_mm4": 10000000.0, "J_mm4": 22000000.0}
    config = {
        "schema_version": "public-example-1",
        "sample_id": "SYNTHETIC_PUBLIC_EXAMPLE",
        "grid_rows": 2,
        "grid_cols": 3,
        "storey_count": storeys,
        "storey_layouts": [MIXED_LAYOUT] * storeys,
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
            "floor_long": floor_long,
            "floor_short": {"A_mm2": 4800.0, "Iy_mm4": 18000000.0, "Iz_mm4": 15000000.0, "J_mm4": 28000000.0},
            "ceiling_long": ceiling_long,
            "ceiling_short": {"A_mm2": 3800.0, "Iy_mm4": 12000000.0, "Iz_mm4": 9000000.0, "J_mm4": 20000000.0},
        },
        "reinforced_zone": {},
        "reinforced_zone_active": False,
        "arm": {"A_mm2": 3000.0, "Iy_mm4": 5000000.0, "Iz_mm4": 5000000.0, "J_mm4": 10000000.0},
        "horizontal_link": {
            "kx": 2000000.0, "ky": 2400000.0, "kz": 3000000.0,
            "kr1": 500000000.0, "kr2": 600000000.0, "kr3": 700000000.0,
        },
        "vertical_link": {
            "kx": 5000000.0, "ky": 5500000.0, "kz": 6500000.0,
            "kr1": 200000000.0, "kr2": 250000000.0, "kr3": 300000000.0,
            "all_four_corners": True,
        },
        "connection_kinematics_mode": "REFERENCE_PORT_DOF",
        "boundary": {
            "mode": "B0",
            "bot_corners_fixed": "U1/U2/U3",
            "bot_rotations": "released",
            "top_in_plane_rigid": True,
            "diaphragm": False,
        },
        "loads": {
            "TH_UX": [1250.0, 0.0, 0.0],
            "TH_UY": [0.0, 1750.0, 0.0],
            "TH_RZ": [0.0, 0.0, 2500000.0],
        },
        "mass_model": "lumped",
    }
    return deepcopy(config)


__all__ = ["MIXED_LAYOUT", "synthetic_config"]

