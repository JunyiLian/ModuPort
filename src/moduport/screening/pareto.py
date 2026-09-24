"""Exact KX-KY Pareto and raw-stiffness balance helpers."""

from __future__ import annotations

import math
from typing import Any, Sequence


def _value(record: Any, public_name: str, attribute_name: str) -> Any:
    if isinstance(record, dict):
        return record.get(public_name)
    return getattr(record, attribute_name)


def _coordinates(record: Any) -> tuple[float, float]:
    kx = float(_value(record, "KX_N_per_mm", "kx_n_per_mm"))
    ky = float(_value(record, "KY_N_per_mm", "ky_n_per_mm"))
    if not math.isfinite(kx) or not math.isfinite(ky):
        raise ValueError("KX and KY must be finite")
    return kx, ky


def _identifier(record: Any) -> str:
    return str(_value(record, "layout_id", "layout_id"))


def _eligible(record: Any) -> bool:
    status = record.get("status", "success") if isinstance(record, dict) else getattr(record, "status", "success")
    if status != "success":
        return False
    try:
        _coordinates(record)
    except (TypeError, ValueError):
        return False
    return True


def pareto_flags(records: Sequence[Any]) -> tuple[bool, ...]:
    """Maximize-maximize Pareto flags with complete same-KX tie handling."""
    flags = [False] * len(records)
    eligible = [index for index, record in enumerate(records) if _eligible(record)]
    order = sorted(eligible, key=lambda index: (-_coordinates(records[index])[0], -_coordinates(records[index])[1], _identifier(records[index])))
    best_y_at_strictly_larger_x = -math.inf
    position = 0
    while position < len(order):
        x = _coordinates(records[order[position]])[0]
        end = position + 1
        while end < len(order) and _coordinates(records[order[end]])[0] == x:
            end += 1
        group = order[position:end]
        group_max_y = max(_coordinates(records[index])[1] for index in group)
        if group_max_y > best_y_at_strictly_larger_x:
            for index in group:
                if _coordinates(records[index])[1] == group_max_y:
                    flags[index] = True
        best_y_at_strictly_larger_x = max(best_y_at_strictly_larger_x, group_max_y)
        position = end
    return tuple(flags)


def normalized_scores(records: Sequence[Any]) -> list[dict[str, float | str]]:
    eligible = [record for record in records if _eligible(record)]
    if not eligible:
        return []
    max_x = max(_coordinates(record)[0] for record in eligible)
    max_y = max(_coordinates(record)[1] for record in eligible)
    if max_x <= 0.0 or max_y <= 0.0:
        raise ValueError("normalization requires positive maximum KX and KY")
    return [
        {
            "layout_id": _identifier(record),
            "SX": _coordinates(record)[0] / max_x,
            "SY": _coordinates(record)[1] / max_y,
            "normalized_min_score": min(_coordinates(record)[0] / max_x, _coordinates(record)[1] / max_y),
        }
        for record in eligible
    ]


def select_balanced_layout(records: Sequence[Any], *, pareto_only: bool = True) -> Any:
    """Apply the public criterion: maximize raw min(KX,KY) on the Pareto set.

    Ties are resolved by larger Kmin/Kmax, then lexicographically smaller
    layout_id, matching the final source correction.
    """
    flags = pareto_flags(records) if pareto_only else tuple(_eligible(record) for record in records)
    candidates = [record for record, keep in zip(records, flags) if keep]
    if not candidates:
        raise ValueError("no successful finite screening records are available")

    def key(record: Any) -> tuple[float, float, str]:
        kx, ky = _coordinates(record)
        minimum, maximum = min(kx, ky), max(kx, ky)
        return -minimum, -(minimum / maximum), _identifier(record)

    return min(candidates, key=key)


__all__ = ["pareto_flags", "normalized_scores", "select_balanced_layout"]
