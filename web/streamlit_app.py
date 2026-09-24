"""First ModuPort Streamlit interface: presentation layer only."""

from __future__ import annotations

from pathlib import Path
import sys

APP_ROOT = Path(__file__).resolve().parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import pandas as pd
import streamlit as st

from moduport import ModuPortError
from web.i18n import current_locale, localize_validation, localized_multiselect, localized_number_input, t
from web.layout_editor import placements_from_records, records_from_layout, validate_placements
from web.plotting import render_layout_svg
from web.single_results import render_single_results
from web.structural_inputs import render_load_editor, render_structural_properties, sections_from_table, shared_values
from web.ui_config import LOAD_CASES, SECTION_NAMES, assemble_config, config_from_json, config_to_json, execute_analysis, synthetic_demo_config
from web.ui_shell import apply_app_style, page_header, render_about_page, sidebar_controls, workflow_strip


st.set_page_config(page_title="ModuPort", page_icon="▦", layout="wide")


def _load_config(config):
    geometry = config["module_geometry"]
    material = config["material"]
    st.session_state.update(
        ui_initialized=True,
        ui_demo=config.get("sample_id") == "SYNTHETIC_SOFTWARE_DEMONSTRATION",
        grid_rows=int(config["grid_rows"]),
        grid_cols=int(config["grid_cols"]),
        storey_count=int(config["storey_count"]),
        long_outer_mm=float(geometry["long_outer_mm"]),
        short_outer_mm=float(geometry["short_outer_mm"]),
        long_centerline_mm=float(geometry["long_centerline_mm"]),
        short_centerline_mm=float(geometry["short_centerline_mm"]),
        clear_gap_mm=float(geometry["clear_gap_mm"]),
        clear_storey_height_mm=float(geometry["clear_storey_height_mm"]),
        column_end_offset_mm=float(geometry["column_end_offset_mm"]),
        reference_x_mm=float(config["reference_point"][0]),
        reference_y_mm=float(config["reference_point"][1]),
        E_N_mm2=float(material["E_N_mm2"]),
        G_N_mm2=float(material["G_N_mm2"]),
        density_kg_m3=float(material["density_kg_m3"]),
        analysis_selection="Both",
        analysis_kind="Both",
        num_modes=3,
        static_cases=list(LOAD_CASES),
    )
    for prefix, source in (("arm", config["arm"]), ("horizontal", config["horizontal_link"]), ("vertical", config["vertical_link"])):
        keys = ("A_mm2", "Iy_mm4", "Iz_mm4", "J_mm4") if prefix == "arm" else ("kx", "ky", "kz", "kr1", "kr2", "kr3")
        for key in keys:
            st.session_state[f"{prefix}_{key}"] = float(source[key])
    st.session_state["layout_source"] = pd.DataFrame(records_from_layout(config["storey_layouts"][0]))
    st.session_state["section_source"] = pd.DataFrame(
        [{"Section": name, **{key: float(config["sections"][name][key]) for key in ("A_mm2", "Iy_mm4", "Iz_mm4", "J_mm4")}} for name in SECTION_NAMES]
    )
    st.session_state["load_source"] = pd.DataFrame(
        [
            {"Case": name, "FX": float(config["loads"][name][0]), "FY": float(config["loads"][name][1]), "MZ": float(config["loads"][name][2])}
            for name in LOAD_CASES
        ]
    )
    for widget_key in ("layout_editor_widget", "section_editor_widget", "load_editor_widget"):
        st.session_state.pop(widget_key, None)
    st.session_state["single_page_state"] = {
        "grid_rows": int(config["grid_rows"]),
        "grid_cols": int(config["grid_cols"]),
        "reference_x_mm": float(config["reference_point"][0]),
        "reference_y_mm": float(config["reference_point"][1]),
        "analysis_selection": "Both",
        "analysis_kind": "Both",
        "num_modes": 3,
        "static_cases": list(LOAD_CASES),
    }
    st.session_state.pop("analysis_results", None)


if not st.session_state.get("ui_initialized"):
    _load_config(synthetic_demo_config())

navigation, screenshot_mode, demo_acknowledged = sidebar_controls()
apply_app_style(screenshot_mode)
if navigation == "about":
    render_about_page()
    st.stop()
if navigation == "batch":
    from web.batch_page import render_batch_screening

    render_batch_screening(screenshot_mode=screenshot_mode, demo_acknowledged=demo_acknowledged)
    st.stop()

for key, value in st.session_state.get("single_page_state", {}).items():
    st.session_state.setdefault(key, value)


page_header(t("page.single"))
workflow_strip([t("workflow.define_inputs"), t("workflow.preview_layout"), t("workflow.run_analysis"), t("workflow.review_results")])
left, right = st.columns([0.46, 0.54], gap="large")

with left:
    st.subheader(t("single.model_input"))
    if not screenshot_mode:
        controls, io = st.columns(2)
        if controls.button(t("single.load_demo"), use_container_width=True):
            _load_config(synthetic_demo_config())
            st.rerun()
        uploaded = io.file_uploader(t("single.import_config"), type=["json"], label_visibility="collapsed")
        if uploaded is not None and io.button(t("single.apply_json"), use_container_width=True):
            try:
                imported = config_from_json(uploaded.getvalue())
                validated = __import__("moduport", fromlist=["ModuPort"]).ModuPort(imported)
                _load_config(validated.to_config_dict())
                st.session_state["ui_demo"] = False
                st.rerun()
            except Exception as error:
                st.error(t("validation.generic"))
    if st.session_state.get("ui_demo") and not demo_acknowledged and not screenshot_mode:
        st.info(t("single.demo_notice"))

    with st.expander(t("single.building_reference"), expanded=True):
        a, b = st.columns(2)
        localized_number_input(a, t("field.grid_rows"), "grid_rows", min_value=1, step=1)
        localized_number_input(b, t("field.grid_columns"), "grid_cols", min_value=1, step=1)
        a, b = st.columns(2)
        localized_number_input(a, t("field.reference_x"), "reference_x_mm")
        localized_number_input(b, t("field.reference_y"), "reference_y_mm")

    with st.expander(t("single.module_layout"), expanded=True):
        st.caption(t("single.module_help"))
        layout_table = st.data_editor(
            st.session_state["layout_source"],
            num_rows="dynamic",
            hide_index=True,
            key="layout_editor_widget",
            column_config={
                "Module": st.column_config.NumberColumn(t("column.module"), disabled=True),
                "Orientation": st.column_config.SelectboxColumn(t("column.orientation"), options=["H", "V"], required=True),
                "Row": st.column_config.NumberColumn(t("column.row"), min_value=0, step=1, required=True),
                "Column": st.column_config.NumberColumn(t("column.column"), min_value=0, step=1, required=True),
            },
            use_container_width=True,
        )
        st.session_state["layout_source"] = layout_table

    section_table = render_structural_properties(t("section.structural"))

    with st.expander(t("single.analysis_settings"), expanded=True):
        analysis_values = ["Static", "Modal", "Both"]
        analysis_labels = [t(f"analysis.{value.lower()}") for value in analysis_values]
        analysis_label_to_value = dict(zip(analysis_labels, analysis_values))
        analysis_value = st.session_state.get("analysis_kind", st.session_state.get("analysis_selection", "Both"))
        analysis_key = f"analysis_display_{current_locale()}"
        if analysis_key not in st.session_state:
            st.session_state[analysis_key] = analysis_labels[analysis_values.index(analysis_value)]
        analysis_display = st.radio(
            t("field.analysis_type"),
            analysis_labels,
            horizontal=True,
            key=analysis_key,
        )
        st.session_state["analysis_kind"] = analysis_label_to_value[analysis_display]
        st.session_state["analysis_selection"] = st.session_state["analysis_kind"]
        localized_multiselect(st, t("field.static_cases"), list(LOAD_CASES), "static_cases")
        load_table = render_load_editor()
        localized_number_input(st, t("field.requested_modes"), "num_modes", min_value=1, step=1)

try:
    placements = placements_from_records(layout_table.to_dict("records"))
    layout_errors = validate_placements(int(st.session_state.grid_rows), int(st.session_state.grid_cols), placements)
except ValueError as error:
    placements = []
    layout_errors = [str(error)]

sections = sections_from_table(section_table)
values = shared_values(st.session_state, load_table)
values.update({key: st.session_state[key] for key in ("grid_rows", "grid_cols", "reference_x_mm", "reference_y_mm")})
current_config = assemble_config(values, placements, sections) if placements else None
st.session_state["single_page_state"] = {
    key: st.session_state[key]
    for key in ("grid_rows", "grid_cols", "reference_x_mm", "reference_y_mm", "analysis_selection", "analysis_kind", "num_modes", "static_cases")
}

with right:
    st.subheader(t("single.layout_preview"))
    st.markdown(render_layout_svg(int(st.session_state.grid_rows), int(st.session_state.grid_cols), placements), unsafe_allow_html=True)
    if layout_errors:
        for error in layout_errors:
            st.warning(localize_validation(error))
    else:
        st.success(t("single.complete_covering", count=len(placements)))

    if current_config is not None:
        st.download_button(
            t("single.download_config"),
            data=config_to_json(current_config),
            file_name="moduport_config.json",
            mime="application/json",
            use_container_width=True,
        )
    run = st.button(t("action.run_analysis"), type="primary", use_container_width=True, disabled=bool(layout_errors or current_config is None))
    if run:
        if st.session_state.analysis_kind in {"Static", "Both"} and not st.session_state.static_cases:
            st.error(t("validation.static_case_required"))
        else:
            try:
                with st.spinner(t("message.analysis_running")):
                    st.session_state["analysis_results"] = execute_analysis(
                        current_config,
                        st.session_state.analysis_kind,
                        list(st.session_state.static_cases),
                        int(st.session_state.num_modes),
                    )
                st.success(t("message.analysis_complete"))
            except (ModuPortError, ValueError, RuntimeError) as error:
                st.error(t("message.analysis_failed"))

st.divider()
render_single_results(st.session_state.get("analysis_results", {}), screenshot_mode=screenshot_mode)
