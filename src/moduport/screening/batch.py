"""Public-API-only serial and multiprocessing layout screening."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
from copy import deepcopy
import csv
from dataclasses import dataclass
import math
import multiprocessing
import os
from pathlib import Path
import time
from typing import Any

from .enumeration import Layout
from .metrics import directional_stiffness


@dataclass(frozen=True)
class ScreeningRecord:
    layout: Layout
    kx_n_per_mm: float | None
    ky_n_per_mm: float | None
    runtime_s: float
    status: str
    error: str | None = None

    @property
    def layout_id(self) -> str:
        return self.layout.layout_id

    @property
    def success(self) -> bool:
        return self.status == "success"

    def to_dict(self) -> dict[str, Any]:
        return {
            "layout_id": self.layout_id,
            "layout_expression": self.layout.expression,
            "layout": self.layout.to_dict(),
            "N_H": self.layout.n_h,
            "N_V": self.layout.n_v,
            "KX_N_per_mm": self.kx_n_per_mm,
            "KY_N_per_mm": self.ky_n_per_mm,
            "runtime_s": self.runtime_s,
            "status": self.status,
            "error": self.error,
        }


class ScreeningResults(Sequence[ScreeningRecord]):
    def __init__(self, records: Sequence[ScreeningRecord]):
        self._records = tuple(records)

    def __len__(self) -> int:
        return len(self._records)

    def __getitem__(self, index: int | slice) -> ScreeningRecord | tuple[ScreeningRecord, ...]:
        return self._records[index]

    def __iter__(self) -> Iterator[ScreeningRecord]:
        return iter(self._records)

    def to_dicts(self) -> list[dict[str, Any]]:
        return [record.to_dict() for record in self]

    def to_dataframe(self):
        try:
            import pandas as pd
        except ImportError as error:
            raise ImportError("pandas is optional; install moduport[screening]") from error
        return pd.DataFrame(self.to_dicts())

    def to_csv(self, path: str | Path) -> None:
        rows = self.to_dicts()
        fields = [key for key in rows[0] if key != "layout"] if rows else [
            "layout_id", "layout_expression", "N_H", "N_V", "KX_N_per_mm", "KY_N_per_mm", "runtime_s", "status", "error"
        ]
        with Path(path).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)


@dataclass(frozen=True)
class BatchProgress:
    completed: int
    total: int
    succeeded: int
    failed: int
    latest_layout_id: str


ProgressCallback = Callable[[BatchProgress], None]


def _layout_domain_error(base_config: Mapping[str, Any], layout: Layout) -> str | None:
    if "occupied_cells" in base_config:
        try:
            configured = {
                (int(cell[0]), int(cell[1]))
                for cell in base_config["occupied_cells"]
                if isinstance(cell, (list, tuple)) and len(cell) == 2
            }
        except (TypeError, ValueError):
            return "base_config.occupied_cells is malformed"
        if configured != set(layout.footprint.cells):
            return "layout footprint does not match base_config.occupied_cells"
    return None


def _failure(layout: Layout, start: float, error: BaseException | str) -> ScreeningRecord:
    message = error if isinstance(error, str) else f"{type(error).__name__}: {error}"
    return ScreeningRecord(layout, None, None, time.perf_counter() - start, "failed", str(message))


def _screen_one(base_config: Mapping[str, Any], layout: Layout) -> ScreeningRecord:
    start = time.perf_counter()
    domain_error = _layout_domain_error(base_config, layout)
    if domain_error:
        return _failure(layout, start, domain_error)
    try:
        storeys = base_config["storey_count"]
        if isinstance(storeys, bool) or not isinstance(storeys, int) or storeys <= 0:
            raise ValueError("base_config.storey_count must be a positive integer")
        config = deepcopy(dict(base_config))
        config["grid_rows"] = layout.footprint.rows
        config["grid_cols"] = layout.footprint.columns
        config["storey_layouts"] = [layout.expression] * storeys
        if "occupied_cells" not in base_config:
            config["occupied_cells"] = [list(cell) for cell in sorted(layout.footprint.cells)]
        # A rectangular base configuration commonly carries its rectangle
        # centre.  When an irregular Layout supplies the footprint for the
        # first time, remove that unrelated default so the public validator
        # constructs the validated occupied-cell centroid.  An explicitly
        # footprint-aware base configuration keeps its supplied reference.
        if not layout.footprint.is_full_rectangle and "occupied_cells" not in base_config:
            config.pop("reference_point", None)

        # This is deliberately the public facade, never a frozen backend import.
        from moduport import ModuPort

        result = ModuPort(config).solve_static(["TH_UX", "TH_UY"])
        stiffness = directional_stiffness(result, config)
        return ScreeningRecord(
            layout,
            stiffness["KX_N_per_mm"],
            stiffness["KY_N_per_mm"],
            time.perf_counter() - start,
            "success",
            None,
        )
    except Exception as error:
        return _failure(layout, start, error)


_WORKER_CONFIG: Mapping[str, Any] | None = None


def _worker_init(base_config: Mapping[str, Any]) -> None:
    global _WORKER_CONFIG
    _WORKER_CONFIG = base_config
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[name] = "1"


def _worker_screen(index: int, layout: Layout) -> tuple[int, ScreeningRecord]:
    if _WORKER_CONFIG is None:
        raise RuntimeError("screening worker was not initialized")
    return index, _screen_one(_WORKER_CONFIG, layout)


@contextmanager
def _single_thread_child_environment() -> Iterator[None]:
    names = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")
    previous = {name: os.environ.get(name) for name in names}
    try:
        for name in names:
            os.environ[name] = "1"
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _notify(callback: ProgressCallback | None, completed: int, total: int, results: Sequence[ScreeningRecord | None], latest: str) -> None:
    if callback is None:
        return
    resolved = [record for record in results if record is not None]
    callback(BatchProgress(completed, total, sum(record.success for record in resolved), sum(not record.success for record in resolved), latest))


def screen_layouts(
    base_config: Mapping[str, Any],
    layouts: Sequence[Layout],
    *,
    workers: int = 1,
    progress: ProgressCallback | None = None,
) -> ScreeningResults:
    """Screen layouts through ``from moduport import ModuPort`` only.

    ``grid_rows``, ``grid_cols``, ``storey_layouts`` and ``occupied_cells`` are
    generated from each Layout.
    Material, member, connection, geometry, load and boundary values in
    ``base_config`` are preserved.  A newly introduced irregular footprint uses
    its occupied-cell centroid unless the base configuration already explicitly
    describes that same footprint and reference point.
    """
    if not isinstance(base_config, Mapping):
        raise TypeError("base_config must be a mapping")
    if isinstance(workers, bool) or not isinstance(workers, int) or workers <= 0:
        raise ValueError("workers must be a positive integer")
    ordered = tuple(layouts)
    if any(not isinstance(layout, Layout) for layout in ordered):
        raise TypeError("layouts must contain Layout objects")
    identifiers = [layout.layout_id for layout in ordered]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("layout_id values must be unique")
    total = len(ordered)
    if total == 0:
        return ScreeningResults(())

    slots: list[ScreeningRecord | None] = [None] * total
    if workers == 1:
        for index, layout in enumerate(ordered):
            slots[index] = _screen_one(base_config, layout)
            _notify(progress, index + 1, total, slots, layout.layout_id)
    else:
        with _single_thread_child_environment():
            context = multiprocessing.get_context("spawn")
            with ProcessPoolExecutor(max_workers=workers, mp_context=context, initializer=_worker_init, initargs=(deepcopy(dict(base_config)),)) as executor:
                futures = {executor.submit(_worker_screen, index, layout): (index, layout) for index, layout in enumerate(ordered)}
                completed = 0
                for future in as_completed(futures):
                    fallback_index, fallback_layout = futures[future]
                    try:
                        index, record = future.result()
                    except Exception as error:
                        index, record = fallback_index, _failure(fallback_layout, time.perf_counter(), error)
                    slots[index] = record
                    completed += 1
                    _notify(progress, completed, total, slots, record.layout_id)

    if any(record is None for record in slots):
        raise RuntimeError("internal batch result ordering failure")
    return ScreeningResults(tuple(record for record in slots if record is not None))


__all__ = ["ScreeningRecord", "ScreeningResults", "BatchProgress", "screen_layouts"]
