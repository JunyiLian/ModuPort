"""Pure layout-editing helpers; no numerical mechanics are implemented here."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class ModulePlacement:
    module_id: int
    orientation: str
    row: int
    column: int

    @property
    def cells(self) -> tuple[tuple[int, int], tuple[int, int]]:
        if self.orientation == "H":
            return ((self.row, self.column), (self.row, self.column + 1))
        return ((self.row, self.column), (self.row + 1, self.column))


def placements_from_records(records: Iterable[Mapping]) -> list[ModulePlacement]:
    placements = []
    for index, record in enumerate(records, 1):
        orientation = str(record.get("Orientation", "")).strip().upper()
        if not orientation and record.get("Row") in (None, "") and record.get("Column") in (None, ""):
            continue
        if orientation not in {"H", "V"}:
            raise ValueError(f"module {index}: orientation must be H or V")
        try:
            row_value = float(record.get("Row"))
            column_value = float(record.get("Column"))
        except (TypeError, ValueError) as error:
            raise ValueError(f"module {index}: row and column must be integers") from error
        if not row_value.is_integer() or not column_value.is_integer():
            raise ValueError(f"module {index}: row and column must be integers")
        placements.append(ModulePlacement(index, orientation, int(row_value), int(column_value)))
    return placements


def records_from_layout(layout: str) -> list[dict[str, object]]:
    records = []
    for index, raw in enumerate(token.strip() for token in layout.split("|") if token.strip()):
        try:
            orientation = raw[0].upper()
            row, column = (int(value.strip()) for value in raw[raw.index("(") + 1 : raw.index(")")].split(","))
        except Exception as error:
            raise ValueError(f"invalid layout token: {raw}") from error
        records.append({"Module": index + 1, "Orientation": orientation, "Row": row, "Column": column})
    return records


def layout_expression(placements: Iterable[ModulePlacement]) -> str:
    return "|".join(f"{item.orientation}({item.row},{item.column})" for item in placements)


def validate_placements(rows: int, columns: int, placements: Iterable[ModulePlacement], require_full: bool = True) -> list[str]:
    errors: list[str] = []
    owner: dict[tuple[int, int], int] = {}
    items = list(placements)
    if not items:
        return ["At least one module is required."]
    for item in items:
        for cell in item.cells:
            row, column = cell
            if not (0 <= row < rows and 0 <= column < columns):
                errors.append(f"Module {item.module_id} extends outside the {rows} × {columns} footprint.")
            elif cell in owner:
                errors.append(f"Modules {owner[cell]} and {item.module_id} overlap at cell ({row}, {column}).")
            else:
                owner[cell] = item.module_id
    if require_full:
        missing = [(row, column) for row in range(rows) for column in range(columns) if (row, column) not in owner]
        if missing:
            errors.append(f"Footprint is incomplete: {len(missing)} cell(s) are unoccupied.")
    return list(dict.fromkeys(errors))


def simple_domino_tiling(rows: int, columns: int) -> list[ModulePlacement]:
    placements: list[ModulePlacement] = []
    if columns % 2 == 0:
        for row in range(rows):
            for column in range(0, columns, 2):
                placements.append(ModulePlacement(len(placements) + 1, "H", row, column))
    elif rows % 2 == 0:
        for column in range(columns):
            for row in range(0, rows, 2):
                placements.append(ModulePlacement(len(placements) + 1, "V", row, column))
    return placements


def identified_interfaces(placements: Iterable[ModulePlacement]) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    owner = {cell: item.module_id for item in placements for cell in item.cells}
    interfaces = []
    for (row, column), module_id in owner.items():
        right = (row, column + 1)
        below = (row + 1, column)
        if right in owner and owner[right] != module_id:
            interfaces.append(((column + 1.0, row), (column + 1.0, row + 1.0)))
        if below in owner and owner[below] != module_id:
            interfaces.append(((column, row + 1.0), (column + 1.0, row + 1.0)))
    return interfaces


__all__ = [
    "ModulePlacement",
    "placements_from_records",
    "records_from_layout",
    "layout_expression",
    "validate_placements",
    "simple_domino_tiling",
    "identified_interfaces",
]
