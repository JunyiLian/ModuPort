"""Centralized presentation-layer internationalization for ModuPort."""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re
from string import Formatter
from typing import Any

import streamlit as st


DEFAULT_LOCALE = "en"
SUPPORTED_LOCALES = ("en", "zh-CN", "fr", "es", "ru", "ar")
NATIVE_LANGUAGE_NAMES = {
    "en": "English",
    "zh-CN": "中文",
    "fr": "Français",
    "es": "Español",
    "ru": "Русский",
    "ar": "العربية",
}
LOCALE_DIR = Path(__file__).with_name("locales")


@lru_cache(maxsize=None)
def load_catalog(locale: str) -> dict[str, str]:
    selected = locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE
    with (LOCALE_DIR / f"{selected}.json").open("r", encoding="utf-8") as handle:
        catalog = json.load(handle)
    if not isinstance(catalog, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in catalog.items()):
        raise ValueError(f"Malformed locale catalog: {selected}")
    if selected != DEFAULT_LOCALE:
        return {**load_catalog(DEFAULT_LOCALE), **catalog}
    return catalog


def current_locale() -> str:
    try:
        selected = st.session_state.get("locale", DEFAULT_LOCALE)
    except RuntimeError:
        selected = DEFAULT_LOCALE
    return selected if selected in SUPPORTED_LOCALES else DEFAULT_LOCALE


def translate(key: str, *, locale: str | None = None, **values: Any) -> str:
    selected = locale or current_locale()
    english = load_catalog(DEFAULT_LOCALE)
    template = load_catalog(selected).get(key, english.get(key, key))
    try:
        return template.format(**values)
    except (KeyError, ValueError):
        fallback = english.get(key, key)
        try:
            return fallback.format(**values)
        except (KeyError, ValueError):
            return fallback


def t(key: str, **values: Any) -> str:
    return translate(key, **values)


def is_rtl(locale: str | None = None) -> bool:
    return (locale or current_locale()) == "ar"


def localized_number_input(container, label: str, state_key: str, **kwargs):
    """Render a translated numeric widget while keeping locale-neutral model state."""
    value = st.session_state[state_key]
    widget_key = f"{state_key}__{current_locale()}"
    result = container.number_input(label, value=value, key=widget_key, **kwargs)
    st.session_state[state_key] = result
    return result


def localized_multiselect(container, label: str, options, state_key: str, **kwargs):
    """Render a translated multiselect without resetting its canonical value on locale changes."""
    widget_key = f"{state_key}__{current_locale()}"
    result = container.multiselect(label, options, default=list(st.session_state[state_key]), key=widget_key, **kwargs)
    st.session_state[state_key] = result
    return result


def placeholder_names(template: str) -> set[str]:
    return {field for _, field, _, _ in Formatter().parse(template) if field}


def catalog_audit() -> dict[str, list[str]]:
    required = set(load_catalog(DEFAULT_LOCALE))
    return {locale: sorted(required - set(load_catalog(locale))) for locale in SUPPORTED_LOCALES}


def localize_validation(message: str) -> str:
    """Translate known actionable validation messages without exposing implementation details."""
    exact = {
        "Select at least one occupied cell.": "validation.select_cell",
        "Occupied cells must be unique.": "validation.unique_cells",
        "Every occupied cell must lie inside the declared grid.": "validation.cells_in_bounds",
        "The occupied-cell count must be even for domino tiling.": "validation.even_cells",
        "Occupied cells must form one four-neighbour connected component.": "validation.connected_cells",
        "At least one module is required.": "validation.module_required",
        "Select at least one static load case.": "validation.static_case_required",
    }
    if message in exact:
        return t(exact[message])
    patterns = (
        (r"Module (\d+) extends outside the (\d+) × (\d+) footprint\.", "validation.module_outside", ("module", "rows", "columns")),
        (r"Modules (\d+) and (\d+) overlap at cell \((\d+), (\d+)\)\.", "validation.module_overlap", ("first", "second", "row", "column")),
        (r"Footprint is incomplete: (\d+) cell\(s\) are unoccupied\.", "validation.incomplete", ("count",)),
        (r"module (\d+): orientation must be H or V", "validation.orientation", ("module",)),
        (r"module (\d+): row and column must be integers", "validation.integer_coordinates", ("module",)),
        (r"invalid layout token: (.+)", "validation.layout_token", ("token",)),
    )
    for pattern, key, names in patterns:
        match = re.fullmatch(pattern, message)
        if match:
            return t(key, **dict(zip(names, match.groups())))
    return t("validation.generic")


__all__ = [
    "DEFAULT_LOCALE", "SUPPORTED_LOCALES", "NATIVE_LANGUAGE_NAMES", "load_catalog",
    "current_locale", "translate", "t", "is_rtl", "placeholder_names", "catalog_audit",
    "localize_validation", "localized_number_input", "localized_multiselect",
]
