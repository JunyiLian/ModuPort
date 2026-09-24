"""Supported occupied-cell footprints for domino layout generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


Cell = tuple[int, int]


def _cell(value: object) -> Cell:
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise TypeError("each footprint cell must be a (row, column) pair")
    row, column = value
    if isinstance(row, bool) or isinstance(column, bool) or not isinstance(row, int) or not isinstance(column, int):
        raise TypeError("footprint row and column indices must be integers")
    if row < 0 or column < 0:
        raise ValueError("footprint row and column indices must be non-negative")
    return row, column


@dataclass(frozen=True)
class Footprint:
    """An immutable set of occupied logical-grid cells."""

    cells: frozenset[Cell]

    def __post_init__(self) -> None:
        normalized = frozenset(_cell(value) for value in self.cells)
        if not normalized:
            raise ValueError("footprint must contain at least one occupied cell")
        object.__setattr__(self, "cells", normalized)

    @classmethod
    def from_cells(cls, cells: Iterable[Cell]) -> "Footprint":
        return cls(frozenset(cells))

    @classmethod
    def rectangle(cls, rows: int, columns: int) -> "Footprint":
        if isinstance(rows, bool) or isinstance(columns, bool) or not isinstance(rows, int) or not isinstance(columns, int):
            raise TypeError("rows and columns must be integers")
        if rows <= 0 or columns <= 0:
            raise ValueError("rows and columns must be positive")
        return cls.from_cells((row, column) for row in range(rows) for column in range(columns))

    @classmethod
    def from_mask(cls, mask: Sequence[Sequence[object]]) -> "Footprint":
        if not mask or not mask[0]:
            raise ValueError("mask must be a non-empty rectangular matrix")
        columns = len(mask[0])
        if any(len(row) != columns for row in mask):
            raise ValueError("mask must be rectangular")
        return cls.from_cells(
            (row_index, column_index)
            for row_index, row in enumerate(mask)
            for column_index, occupied in enumerate(row)
            if bool(occupied)
        )

    @property
    def rows(self) -> int:
        return max(row for row, _ in self.cells) + 1

    @property
    def columns(self) -> int:
        return max(column for _, column in self.cells) + 1

    @property
    def occupied_cell_count(self) -> int:
        return len(self.cells)

    @property
    def is_full_rectangle(self) -> bool:
        return len(self.cells) == self.rows * self.columns

    def to_mask(self) -> tuple[tuple[bool, ...], ...]:
        return tuple(
            tuple((row, column) in self.cells for column in range(self.columns))
            for row in range(self.rows)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "rows": self.rows,
            "columns": self.columns,
            "occupied_cells": [list(cell) for cell in sorted(self.cells)],
        }


def as_footprint(value: Footprint | Iterable[Cell]) -> Footprint:
    return value if isinstance(value, Footprint) else Footprint.from_cells(value)


__all__ = ["Cell", "Footprint", "as_footprint"]
