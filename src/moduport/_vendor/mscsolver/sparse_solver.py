"""Typed public API around the audited v3 sparse numerical kernel."""
from __future__ import annotations
from typing import Any
from . import _kernel_v3_sparse as _v3

FREE_BARE_FRAME = _v3.FREE_BARE_FRAME
SparseModel = _v3.SparseModel

def build_model(case: dict, config: Any = None, boundary_mode: str | None = None) -> SparseModel:
    """Assemble a complete multi-module, multi-storey sparse bare-frame model."""
    return _v3.build_model(case, config, boundary_mode)

def load_vectors(model: SparseModel, case: dict) -> tuple[Any, Any]:
    """Create the balanced TH_UX, TH_UY and TH_RZ nodal load vectors."""
    return _v3.load_vectors(model, case)

def solve_case(case: dict, config: Any = None) -> dict:
    """Solve all three static load cases and return fields, projections, Links and QA."""
    return _v3.solve_case(case, config)

def run_bare_frame_batch(cases: list[dict], output_directory: str, resume: bool = True) -> tuple[list, list]:
    """Solve a case list with optional result-file checkpoint reuse."""
    return _v3.run_bare_frame_batch(cases, output_directory, resume)
