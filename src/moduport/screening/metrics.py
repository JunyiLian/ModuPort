"""Directional stiffness definitions for public layout screening."""

from __future__ import annotations

import math
from typing import Any, Mapping


def _pure_directional_load(config: Mapping[str, Any], case: str, component: int) -> float:
    try:
        vector = config["loads"][case]
    except (KeyError, TypeError) as error:
        raise ValueError(f"base_config must define loads.{case}") from error
    if not isinstance(vector, (list, tuple)) or len(vector) != 3:
        raise ValueError(f"loads.{case} must contain three components")
    values = [float(value) for value in vector]
    if not all(math.isfinite(value) for value in values):
        raise ValueError(f"loads.{case} must be finite")
    if values[component] == 0.0 or any(value != 0.0 for index, value in enumerate(values) if index != component):
        direction = "X" if component == 0 else "Y"
        raise ValueError(f"loads.{case} must be a nonzero pure {direction}-direction generalized load")
    return values[component]


def directional_stiffness(static_result: Any, config: Mapping[str, Any]) -> dict[str, float]:
    """Return KX=FX/ux_bar(top) and KY=FY/uy_bar(top).

    With the public unit-load convention FX=FY=1 N, these reduce exactly to
    KX=1/ux_bar and KY=1/uy_bar in N/mm.
    """
    response = static_result.storey_response
    ux = float(response["TH_UX"][-1]["ux_bar"])
    uy = float(response["TH_UY"][-1]["uy_bar"])
    fx = _pure_directional_load(config, "TH_UX", 0)
    fy = _pure_directional_load(config, "TH_UY", 1)
    if not math.isfinite(ux) or ux == 0.0 or not math.isfinite(uy) or uy == 0.0:
        raise ValueError("top-storey directional displacement must be finite and nonzero")
    kx, ky = fx / ux, fy / uy
    if not math.isfinite(kx) or not math.isfinite(ky) or kx <= 0.0 or ky <= 0.0:
        raise ValueError("directional stiffness must be finite and positive")
    return {
        "applied_FX_N": fx,
        "applied_FY_N": fy,
        "top_ux_bar_mm": ux,
        "top_uy_bar_mm": uy,
        "KX_N_per_mm": kx,
        "KY_N_per_mm": ky,
    }


__all__ = ["directional_stiffness"]
