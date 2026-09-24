"""Lossless thin views and plain-Python serialization for solver results."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np


def to_plain(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: to_plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {key: to_plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [to_plain(item) for item in value]
    if isinstance(value, list):
        return [to_plain(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


class _ResultView:
    __slots__ = ("_raw",)

    def __init__(self, raw: Any):
        self._raw = raw

    def __getattr__(self, name: str) -> Any:
        return getattr(self._raw, name)

    def to_dict(self) -> dict[str, Any]:
        value = to_plain(self._raw)
        if not isinstance(value, dict):
            raise TypeError("frozen solver result is not a dataclass or mapping")
        return value


class StaticResult(_ResultView):
    """Public view of an unchanged frozen static result."""


class ModalResult(_ResultView):
    """Public view of an unchanged frozen modal result."""


__all__ = ["StaticResult", "ModalResult"]
