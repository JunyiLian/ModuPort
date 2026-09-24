"""Thin public facade over the frozen ModuPort mechanics solver."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from ._bootstrap import install
from .exceptions import ConfigurationError, UnsupportedConfigurationError
from .serialization import ModalResult, StaticResult
from .validation import STATIC_CASES, validate_config


class ModuPort:
    """Validated rectangular and occupied-cell-domain entry point."""

    def __init__(self, config: Mapping[str, Any]):
        data = validate_config(config)
        state = install()
        frozen_config_module = __import__("_moduport_frozen.config", fromlist=["ModelConfig"])
        frozen_solver_module = __import__("_moduport_frozen.solver", fromlist=["ModuPortSolver"])
        frozen_config = frozen_config_module.ModelConfig(
            source=Path("python_mapping"),
            data=data,
            config_version=str(data.get("config_version", data.get("schema_version", "1.0"))),
            layout=tuple(data["storey_layouts"]),
            storeys=int(data["storey_count"]),
            module_geometry=data["module_geometry"],
            material=data["material"],
            sections=data["sections"],
            horizontal_link=data["horizontal_link"],
            vertical_link=data["vertical_link"],
            boundary=data["boundary"],
            load_cases=data["loads"],
            mass_model=data["mass_model"],
            reinforced_zone=dict(data["reinforced_zone"], active=False),
            solver_options=data.get("solver_options", {"symmetry_tolerance": 1e-10, "residual_tolerance": 1e-8}),
        )
        self._data = data
        self._config = frozen_config
        self._solver = frozen_solver_module.ModuPortSolver(frozen_config, "finite_port_sparse")
        if self._solver.backend.__class__.__name__ != "SparseFinitePortOptionCBackend":
            raise RuntimeError("validated numerical backend was not resolved")
        self._bootstrap_state = state

    @classmethod
    def from_json(cls, path: str | Path) -> "ModuPort":
        source = Path(path)
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except Exception as error:
            raise ConfigurationError(f"cannot read configuration {source}: {error}") from error
        if not isinstance(data, dict):
            raise ConfigurationError("JSON configuration root must be an object")
        return cls(data)

    def to_config_dict(self) -> dict[str, Any]:
        """Return the normalized public configuration as plain JSON data."""
        return deepcopy(self._data)

    def to_json(self, path: str | Path | None = None) -> str:
        """Serialize the normalized public configuration, including its footprint."""
        payload = json.dumps(self._data, indent=2, sort_keys=True, allow_nan=False)
        if path is not None:
            Path(path).write_text(payload, encoding="utf-8")
        return payload

    def solve_static(self, load_cases: Sequence[str] | None = None) -> StaticResult:
        selected = list(self._config.load_cases) if load_cases is None else list(load_cases)
        if not selected:
            raise ConfigurationError("at least one static load case is required")
        unknown = sorted(set(selected) - STATIC_CASES)
        if unknown:
            raise UnsupportedConfigurationError("unsupported static load cases: " + ", ".join(unknown))
        return StaticResult(self._solver.solve_static(selected))

    def solve_modal(self, num_modes: int = 3) -> ModalResult:
        if isinstance(num_modes, bool) or not isinstance(num_modes, int) or num_modes <= 0:
            raise ConfigurationError("num_modes must be a positive integer")
        return ModalResult(self._solver.solve_modal(num_modes=num_modes, mass_model="lumped"))


__all__ = ["ModuPort"]
