"""Browser-side footprint sketcher wrapper and source-only JSON helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

import streamlit.components.v1 as components


_COMPONENT_PATH = Path(__file__).with_name("footprint_component")
_sketcher_component = components.declare_component("moduport_footprint_sketcher", path=str(_COMPONENT_PATH))


def normalize_occupied_cells(rows: int, columns: int, cells: Sequence[Sequence[Any]]) -> list[tuple[int, int]]:
    """Return unique, sorted integer cells that lie inside the declared grid."""
    output: set[tuple[int, int]] = set()
    for cell in cells:
        if not isinstance(cell, (list, tuple)) or len(cell) != 2:
            continue
        row, column = cell
        if isinstance(row, bool) or isinstance(column, bool) or not isinstance(row, int) or not isinstance(column, int):
            continue
        if 0 <= row < rows and 0 <= column < columns:
            output.add((row, column))
    return sorted(output)


def footprint_data_json(rows: int, columns: int, cells: Sequence[Sequence[Any]]) -> str:
    payload = {
        "grid_rows": int(rows),
        "grid_cols": int(columns),
        "occupied_cells": [list(cell) for cell in normalize_occupied_cells(rows, columns, cells)],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def parse_footprint_data(payload: str | bytes) -> tuple[int, int, list[tuple[int, int]]]:
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("Footprint JSON must contain an object.")
    try:
        rows, columns = data["grid_rows"], data["grid_cols"]
        raw_cells = data["occupied_cells"]
    except KeyError as error:
        raise ValueError(f"Footprint JSON is missing {error.args[0]!r}.") from error
    if isinstance(rows, bool) or not isinstance(rows, int) or rows <= 0 or isinstance(columns, bool) or not isinstance(columns, int) or columns <= 0:
        raise ValueError("grid_rows and grid_cols must be positive integers.")
    if not isinstance(raw_cells, list):
        raise ValueError("occupied_cells must be a list of [row, column] pairs.")
    cells = normalize_occupied_cells(rows, columns, raw_cells)
    if len(cells) != len(raw_cells):
        raise ValueError("occupied_cells must contain unique in-bounds integer [row, column] pairs.")
    return rows, columns, cells


def render_footprint_sketcher(
    rows: int,
    columns: int,
    occupied_cells: Sequence[Sequence[Any]],
    *,
    key: str = "footprint_sketcher",
    revision: int | str = 0,
    strings: dict[str, str] | None = None,
    rtl: bool = False,
    height: int = 720,
) -> list[tuple[int, int]]:
    current = normalize_occupied_cells(rows, columns, occupied_cells)
    value = _sketcher_component(
        rows=rows,
        columns=columns,
        occupied_cells=[list(cell) for cell in current],
        footprint_key=str(revision),
        strings=strings or {},
        rtl=bool(rtl),
        default={"occupied_cells": [list(cell) for cell in current]},
        key=f"{key}_{revision}",
        height=height,
    )
    if not isinstance(value, dict):
        return current
    return normalize_occupied_cells(rows, columns, value.get("occupied_cells", current))


__all__ = [
    "render_footprint_sketcher",
    "normalize_occupied_cells",
    "footprint_data_json",
    "parse_footprint_data",
]
