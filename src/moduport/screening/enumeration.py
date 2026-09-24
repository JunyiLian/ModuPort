"""Deterministic exhaustive domino enumeration for supported occupied-cell footprints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator

from .footprint import Cell, Footprint, as_footprint


@dataclass(frozen=True, order=True)
class Domino:
    orientation: str
    row: int
    column: int

    def __post_init__(self) -> None:
        orientation = self.orientation.upper()
        if orientation not in {"H", "V"}:
            raise ValueError("domino orientation must be H or V")
        if isinstance(self.row, bool) or isinstance(self.column, bool) or not isinstance(self.row, int) or not isinstance(self.column, int):
            raise TypeError("domino row and column must be integers")
        if self.row < 0 or self.column < 0:
            raise ValueError("domino row and column must be non-negative")
        object.__setattr__(self, "orientation", orientation)

    @property
    def cells(self) -> tuple[Cell, Cell]:
        if self.orientation == "H":
            return (self.row, self.column), (self.row, self.column + 1)
        return (self.row, self.column), (self.row + 1, self.column)

    def to_dict(self) -> dict[str, object]:
        return {"orientation": self.orientation, "row": self.row, "column": self.column}


@dataclass(frozen=True)
class Layout:
    layout_id: str
    footprint: Footprint
    dominoes: tuple[Domino, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.layout_id, str) or not self.layout_id:
            raise ValueError("layout_id must be a non-empty string")
        dominoes = tuple(self.dominoes)
        covered: list[Cell] = [cell for domino in dominoes for cell in domino.cells]
        if len(covered) != len(set(covered)):
            raise ValueError("layout contains overlapping dominoes")
        if set(covered) != set(self.footprint.cells):
            raise ValueError("layout is not an exact covering of its footprint")
        object.__setattr__(self, "dominoes", dominoes)

    @property
    def expression(self) -> str:
        return "|".join(f"{item.orientation}({item.row},{item.column})" for item in self.dominoes)

    @property
    def n_h(self) -> int:
        return sum(item.orientation == "H" for item in self.dominoes)

    @property
    def n_v(self) -> int:
        return sum(item.orientation == "V" for item in self.dominoes)

    @property
    def signature(self) -> tuple[tuple[str, int, int], ...]:
        return tuple((item.orientation, item.row, item.column) for item in self.dominoes)

    def to_dict(self) -> dict[str, object]:
        return {
            "layout_id": self.layout_id,
            "expression": self.expression,
            "N_H": self.n_h,
            "N_V": self.n_v,
            "dominoes": [item.to_dict() for item in self.dominoes],
            "footprint": self.footprint.to_dict(),
        }


def iter_layouts(
    footprint: Footprint | Iterable[Cell],
    *,
    id_prefix: str = "L",
    start_index: int = 1,
) -> Iterator[Layout]:
    """Yield every exact covering; the first uncovered cell and H-before-V order are fixed."""
    domain = as_footprint(footprint)
    if not isinstance(id_prefix, str):
        raise TypeError("id_prefix must be a string")
    if isinstance(start_index, bool) or not isinstance(start_index, int) or start_index < 0:
        raise ValueError("start_index must be a non-negative integer")
    if domain.occupied_cell_count % 2:
        return

    def recurse(uncovered: frozenset[Cell], placed: tuple[Domino, ...]) -> Iterator[tuple[Domino, ...]]:
        if not uncovered:
            yield placed
            return
        row, column = min(uncovered)
        for orientation, other in (("H", (row, column + 1)), ("V", (row + 1, column))):
            if other in uncovered:
                removed = {(row, column), other}
                yield from recurse(uncovered.difference(removed), placed + (Domino(orientation, row, column),))

    for offset, dominoes in enumerate(recurse(domain.cells, ())):
        yield Layout(f"{id_prefix}{start_index + offset:06d}", domain, dominoes)


def enumerate_layouts(
    footprint: Footprint | Iterable[Cell],
    *,
    id_prefix: str = "L",
    start_index: int = 1,
) -> list[Layout]:
    return list(iter_layouts(footprint, id_prefix=id_prefix, start_index=start_index))


__all__ = ["Domino", "Layout", "iter_layouts", "enumerate_layouts"]
