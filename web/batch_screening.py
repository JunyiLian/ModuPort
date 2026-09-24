"""Pure helpers for the Streamlit batch-screening presentation layer."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from copy import deepcopy
import csv
import hashlib
import io
import json
from typing import Any

from moduport import ModuPort, pareto_flags, select_balanced_layout

from .layout_editor import ModulePlacement


def validate_footprint_cells(rows: int, columns: int, cells: Sequence[tuple[int, int]]) -> list[str]:
    errors: list[str] = []
    if isinstance(rows, bool) or not isinstance(rows, int) or rows <= 0 or isinstance(columns, bool) or not isinstance(columns, int) or columns <= 0:
        return ["Grid rows and columns must be positive integers."]
    values = list(cells)
    if not values:
        return ["Select at least one occupied cell."]
    if len(values) != len(set(values)):
        errors.append("Occupied cells must be unique.")
    if any(not (0 <= row < rows and 0 <= column < columns) for row, column in values):
        errors.append("Every occupied cell must lie inside the declared grid.")
    if len(values) % 2:
        errors.append("The occupied-cell count must be even for domino tiling.")
    domain = set(values)
    visited = {next(iter(domain))}
    frontier = list(visited)
    while frontier:
        row, column = frontier.pop()
        for neighbor in ((row - 1, column), (row + 1, column), (row, column - 1), (row, column + 1)):
            if neighbor in domain and neighbor not in visited:
                visited.add(neighbor)
                frontier.append(neighbor)
    if visited != domain:
        errors.append("Occupied cells must form one four-neighbour connected component.")
    return errors


def footprint_signature(rows: int, columns: int, cells: Sequence[tuple[int, int]]) -> str:
    payload = [int(rows), int(columns), [list(cell) for cell in sorted(set(cells))]]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode("utf-8")).hexdigest()


def structural_signature(config: Mapping[str, Any], custom_reference: bool) -> str:
    data = deepcopy(dict(config))
    for key in ("storey_layouts", "occupied_cells", "sample_id", "grid_rows", "grid_cols"):
        data.pop(key, None)
    if not custom_reference:
        data.pop("reference_point", None)
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def invalidate_footprint_state(state: MutableMapping[str, Any], signature: str) -> bool:
    previous = state.get("batch_footprint_signature")
    state["batch_footprint_signature"] = signature
    if previous is None or previous == signature:
        return False
    for key in (
        "batch_layouts", "batch_enumeration_runtime_s", "batch_screening_results", "batch_screening_runtime_s",
        "batch_screening_structural_signature", "batch_results_stale", "batch_selected_layout_id", "batch_browse_layout_id",
    ):
        state.pop(key, None)
    return True


def update_stale_state(state: MutableMapping[str, Any], current_structural_signature: str) -> bool:
    stale = bool(
        state.get("batch_screening_results") is not None
        and state.get("batch_screening_structural_signature") != current_structural_signature
    )
    state["batch_results_stale"] = stale
    return stale


def placements_from_layout(layout: Any) -> list[ModulePlacement]:
    return [
        ModulePlacement(index, domino.orientation, domino.row, domino.column)
        for index, domino in enumerate(layout.dominoes, 1)
    ]


def candidate_config(base_config: Mapping[str, Any], layout: Any) -> dict[str, Any]:
    config = deepcopy(dict(base_config))
    config["grid_rows"] = layout.footprint.rows
    config["grid_cols"] = layout.footprint.columns
    config["occupied_cells"] = [list(cell) for cell in sorted(layout.footprint.cells)]
    config["storey_layouts"] = [layout.expression] * int(config["storey_count"])
    return ModuPort(config).to_config_dict()


def resolved_reference_point(base_config: Mapping[str, Any], layout: Any) -> tuple[float, float]:
    normalized = candidate_config(base_config, layout)
    return tuple(map(float, normalized["reference_point"]))


def result_display_rows(results: Sequence[Any]) -> tuple[list[dict[str, Any]], tuple[bool, ...], str | None]:
    flags = pareto_flags(results)
    successful = [record for record in results if record.success]
    balanced = select_balanced_layout(results) if successful else None
    balanced_id = None if balanced is None else balanced.layout_id
    rows = []
    for record, pareto in zip(results, flags):
        rows.append({
            "layout_id": record.layout_id,
            "H_count": record.layout.n_h,
            "V_count": record.layout.n_v,
            "KX_N_per_mm": record.kx_n_per_mm,
            "KY_N_per_mm": record.ky_n_per_mm,
            "Pareto": bool(pareto),
            "Balanced": record.layout_id == balanced_id,
            "runtime_s": record.runtime_s,
            "status": record.status,
            "error": record.error,
        })
    return rows, flags, balanced_id


def design_space_rows(results: Sequence[Any]) -> list[dict[str, Any]]:
    rows, _, _ = result_display_rows(results)
    output = []
    for row in rows:
        if row["status"] != "success":
            continue
        category = "Balanced" if row["Balanced"] else "Pareto" if row["Pareto"] else "Ordinary"
        output.append(dict(row, Category=category))
    return output


def results_csv(results: Sequence[Any]) -> str:
    rows, _, _ = result_display_rows(results)
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else [
        "layout_id", "H_count", "V_count", "KX_N_per_mm", "KY_N_per_mm", "Pareto", "Balanced", "runtime_s", "status", "error"
    ])
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def selected_layout_json(record: Any, *, pareto: bool, balanced: bool) -> str:
    payload = {
        "layout": record.layout.to_dict(),
        "result": {
            "KX_N_per_mm": record.kx_n_per_mm,
            "KY_N_per_mm": record.ky_n_per_mm,
            "runtime_s": record.runtime_s,
            "status": record.status,
            "error": record.error,
            "Pareto": bool(pareto),
            "Balanced": bool(balanced),
        },
    }
    return json.dumps(payload, indent=2, allow_nan=False)


def footprint_config_json(base_config: Mapping[str, Any], layout: Any) -> str:
    return json.dumps(candidate_config(base_config, layout), indent=2, sort_keys=True, allow_nan=False)


__all__ = [
    "validate_footprint_cells", "footprint_signature", "structural_signature", "invalidate_footprint_state", "update_stale_state",
    "placements_from_layout", "candidate_config", "resolved_reference_point", "result_display_rows", "design_space_rows",
    "results_csv", "selected_layout_json", "footprint_config_json",
]
