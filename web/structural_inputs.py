"""Shared Streamlit structural-input components for single and batch workflows."""

from __future__ import annotations

from typing import Any, Mapping

import streamlit as st

from .ui_config import LOAD_CASES, SECTION_NAMES
from .i18n import localized_number_input, t


def render_structural_properties(title: str = "Structural properties"):
    """Render the one shared set of ModuPort structural property controls."""
    with st.expander(title, expanded=False):
        localized_number_input(st, t("field.storeys"), "storey_count", min_value=1, step=1)
        st.markdown(f'**{t("group.module_geometry")}**')
        a, b = st.columns(2)
        localized_number_input(a, t("field.module_length"), "long_outer_mm", min_value=0.001)
        localized_number_input(b, t("field.module_width"), "short_outer_mm", min_value=0.001)
        localized_number_input(a, t("field.long_centerline"), "long_centerline_mm", min_value=0.001)
        localized_number_input(b, t("field.short_centerline"), "short_centerline_mm", min_value=0.001)
        localized_number_input(a, t("field.clear_storey_height"), "clear_storey_height_mm", min_value=0.001)
        localized_number_input(b, t("field.module_gap"), "clear_gap_mm", min_value=0.001)
        localized_number_input(a, t("field.column_offset"), "column_end_offset_mm", min_value=0.001)

        st.markdown(f'**{t("group.material")}**')
        a, b, c = st.columns(3)
        localized_number_input(a, t("field.elastic_modulus"), "E_N_mm2", min_value=0.001)
        localized_number_input(b, t("field.shear_modulus"), "G_N_mm2", min_value=0.001)
        localized_number_input(c, t("field.density"), "density_kg_m3", min_value=0.001)

        st.markdown(f'**{t("group.member_sections")}**')
        section_table = st.data_editor(
            st.session_state["section_source"],
            num_rows="fixed",
            hide_index=True,
            key="section_editor_widget",
            column_config={
                "Section": st.column_config.TextColumn(t("column.member"), disabled=True),
                "A_mm2": st.column_config.NumberColumn(t("column.area"), required=True),
                "Iy_mm4": st.column_config.NumberColumn("Iy (mm⁴)", required=True),
                "Iz_mm4": st.column_config.NumberColumn("Iz (mm⁴)", required=True),
                "J_mm4": st.column_config.NumberColumn("J (mm⁴)", required=True),
            },
            use_container_width=True,
        )
        st.session_state["section_source"] = section_table

        st.markdown(f'**{t("group.connection_arm")}**')
        columns = st.columns(4)
        for column, key, label in zip(columns, ("A_mm2", "Iy_mm4", "Iz_mm4", "J_mm4"), ("A (mm²)", "Iy (mm⁴)", "Iz (mm⁴)", "J (mm⁴)")):
            state_key = f"arm_{key}"
            localized_number_input(column, label, state_key, min_value=0.001)

        connection_labels = {
            "kx": "kx (N/mm)",
            "ky": "ky (N/mm)",
            "kz": "kz (N/mm)",
            "kr1": "kr1 (N·mm/rad)",
            "kr2": "kr2 (N·mm/rad)",
            "kr3": "kr3 (N·mm/rad)",
        }
        for label_key, prefix in (("group.horizontal_connection", "horizontal"), ("group.vertical_connection", "vertical")):
            st.markdown(f'**{t(label_key)}**')
            columns = st.columns(3)
            for index, key in enumerate(("kx", "ky", "kz", "kr1", "kr2", "kr3")):
                state_key = f"{prefix}_{key}"
                localized_number_input(columns[index % 3], connection_labels[key], state_key, min_value=0.0)
    return section_table


def render_load_editor():
    load_table = st.data_editor(
        st.session_state["load_source"],
        num_rows="fixed",
        hide_index=True,
        key="load_editor_widget",
        column_config={
            "Case": st.column_config.TextColumn(disabled=True),
            "FX": st.column_config.NumberColumn("FX (N)", required=True),
            "FY": st.column_config.NumberColumn("FY (N)", required=True),
            "MZ": st.column_config.NumberColumn("MZ (N·mm)", required=True),
        },
        use_container_width=True,
    )
    st.session_state["load_source"] = load_table
    return load_table


def sections_from_table(section_table) -> dict[str, dict[str, float]]:
    return {
        str(row["Section"]): {key: float(row[key]) for key in ("A_mm2", "Iy_mm4", "Iz_mm4", "J_mm4")}
        for row in section_table.to_dict("records")
    }


def shared_values(state: Mapping[str, Any], load_table) -> dict[str, Any]:
    keys = (
        "storey_count", "long_outer_mm", "short_outer_mm", "long_centerline_mm", "short_centerline_mm",
        "clear_gap_mm", "clear_storey_height_mm", "column_end_offset_mm", "E_N_mm2", "G_N_mm2", "density_kg_m3",
        "arm_A_mm2", "arm_Iy_mm4", "arm_Iz_mm4", "arm_J_mm4",
        "horizontal_kx", "horizontal_ky", "horizontal_kz", "horizontal_kr1", "horizontal_kr2", "horizontal_kr3",
        "vertical_kx", "vertical_ky", "vertical_kz", "vertical_kr1", "vertical_kr2", "vertical_kr3",
    )
    values = {key: state[key] for key in keys}
    values["loads"] = {
        str(row["Case"]): [float(row["FX"]), float(row["FY"]), float(row["MZ"])]
        for row in load_table.to_dict("records")
        if str(row["Case"]) in LOAD_CASES
    }
    return values


__all__ = ["render_structural_properties", "render_load_editor", "sections_from_table", "shared_values"]
