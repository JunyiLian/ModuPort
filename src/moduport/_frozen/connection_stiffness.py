"""Backward-compatible connection-stiffness resolution.

This module is an interface adapter only.  It does not define connection
kinematics or alter the finite-port formulation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
import math


@dataclass(frozen=True)
class ResolvedConnectionStiffness:
    kind: str
    values: tuple[float, ...]
    source: str

    @property
    def active(self) -> tuple[bool, ...]:
        return tuple(value != 0.0 for value in self.values)

    def as_dict(self) -> dict[str, float]:
        names = ("kx", "ky", "kz", "kr1", "kr2", "kr3")[: len(self.values)]
        return dict(zip(names, self.values))


_H_ALIASES = (
    ("kx", "kx_N_mm", "kHx"),
    ("ky", "ky_N_mm", "kHy"),
    ("kz", "kz_N_mm", "kHz"),
    ("kr1", "kr1_N_mm_rad", "kHr1"),
    ("kr2", "kr2_N_mm_rad", "kHr2"),
    ("kr3", "kr3_N_mm_rad", "kHr3"),
)
_V_ALIASES = _H_ALIASES


def _get(mapping: Mapping[str, Any], aliases: tuple[str, ...]):
    present = [key for key in aliases if key in mapping]
    if len(present) > 1:
        values = [float(mapping[key]) for key in present]
        if any(value != values[0] for value in values[1:]):
            raise ValueError(f"conflicting aliases {present}")
    return (float(mapping[present[0]]), present[0]) if present else (None, None)


def _explicit(mapping: Mapping[str, Any], aliases):
    found = [_get(mapping, group) for group in aliases]
    count = sum(value is not None for value, _ in found)
    if count not in (0, len(aliases)):
        missing = [group[0] for group, (value, _) in zip(aliases, found) if value is None]
        raise ValueError("incomplete axis-specific connection stiffness: " + ", ".join(missing))
    return tuple(value for value, _ in found) if count else None


def _validate(values: tuple[float, ...], kind: str):
    if not all(math.isfinite(value) and value >= 0.0 for value in values):
        raise ValueError(f"{kind} stiffness values must be finite and non-negative")


def resolve_horizontal_connection(mapping: Mapping[str, Any]) -> ResolvedConnectionStiffness:
    explicit = _explicit(mapping, _H_ALIASES)
    scalar_present = any(key in mapping for key in ("k_trans_N_mm", "horizontal_k_link_N_mm", "k_rot_N_mm_rad", "krot_N_mm_rad"))
    if explicit is not None:
        if scalar_present:
            raise ValueError("horizontal scalar and axis-specific stiffness cannot be mixed")
        values = explicit
        source = "AXIS_SPECIFIC"
    else:
        kt, _ = _get(mapping, ("k_trans_N_mm", "horizontal_k_link_N_mm"))
        kr, _ = _get(mapping, ("k_rot_N_mm_rad", "krot_N_mm_rad"))
        if kt is None:
            raise ValueError("missing horizontal translational stiffness")
        kr = 0.0 if kr is None else kr
        values = (kt, kt, kt, kr, kr, kr)
        source = "LEGACY_SCALAR"
    _validate(values, "horizontal")
    return ResolvedConnectionStiffness("horizontal", values, source)


def resolve_vertical_connection(mapping: Mapping[str, Any]) -> ResolvedConnectionStiffness:
    explicit = _explicit(mapping, _V_ALIASES)
    scalar_present = any(key in mapping for key in (
        "k_trans_N_mm", "vertical_k_link_N_mm", "k_rot_N_mm_rad", "krot_N_mm_rad"
    ))
    if explicit is not None:
        if scalar_present:
            raise ValueError("vertical scalar and axis-specific stiffness cannot be mixed")
        values = explicit
        source = "AXIS_SPECIFIC"
    else:
        kt, _ = _get(mapping, ("k_trans_N_mm", "vertical_k_link_N_mm"))
        if kt is None:
            raise ValueError("missing vertical translational stiffness")
        kr, _ = _get(mapping, ("k_rot_N_mm_rad", "krot_N_mm_rad"))
        kr = 0.0 if kr is None else kr
        values = (kt, kt, kt, kr, kr, kr)
        source = "LEGACY_SCALAR"
    _validate(values, "vertical")
    return ResolvedConnectionStiffness("vertical", values, source)


def horizontal_sap_property(mapping: Mapping[str, Any]):
    resolved = resolve_horizontal_connection(mapping)
    return resolved.active, (False,) * 6, resolved.values


def vertical_sap_property(mapping: Mapping[str, Any]):
    resolved = resolve_vertical_connection(mapping)
    # SAP zero-length vertical Link local axes are (+Z,+X,+Y). ModuPort
    # stores physical components in global (+X,+Y,+Z,+RX,+RY,+RZ).
    kx, ky, kz, krx, kry, krz = resolved.values
    values = (kz, kx, ky, krz, krx, kry)
    active = resolved.active
    return (active[2],active[0],active[1],active[5],active[3],active[4]), (False,) * 6, values
