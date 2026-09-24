"""Interactive Streamlit workflow for public-API batch layout screening."""

from __future__ import annotations

import os
import time

import altair as alt
import pandas as pd
import streamlit as st

from moduport import Footprint, enumerate_layouts, screen_layouts

from .batch_screening import (
    design_space_rows,
    footprint_config_json,
    footprint_signature,
    invalidate_footprint_state,
    placements_from_layout,
    resolved_reference_point,
    result_display_rows,
    results_csv,
    selected_layout_json,
    structural_signature,
    update_stale_state,
    validate_footprint_cells,
)
from .footprint_sketcher import footprint_data_json, parse_footprint_data, render_footprint_sketcher
from .i18n import current_locale, is_rtl, localize_validation, localized_number_input, t
from .plotting import render_screening_layout_svg
from .structural_inputs import render_load_editor, render_structural_properties, sections_from_table, shared_values
from .ui_config import assemble_config
from .ui_shell import page_header, workflow_strip


SYNTHETIC_CELLS = {
    (0, 0), (0, 1),
    (1, 0), (1, 1), (1, 2), (1, 3),
    (2, 2), (2, 3),
}
LARGE_LAYOUT_WARNING = 1000
DEFAULT_SKETCH_ROWS = 50
DEFAULT_SKETCH_COLUMNS = 50


def _reset_footprint(rows: int, columns: int, cells: set[tuple[int, int]] | list[tuple[int, int]]) -> None:
    st.session_state["batch_grid_rows"] = rows
    st.session_state["batch_grid_cols"] = columns
    st.session_state["batch_occupied_cells"] = sorted(cells)
    st.session_state["batch_sketcher_revision"] = int(st.session_state.get("batch_sketcher_revision", 0)) + 1
    for key in (
        "batch_layouts", "batch_screening_results", "batch_enumeration_runtime_s", "batch_screening_runtime_s",
        "batch_screening_structural_signature", "batch_results_stale", "batch_selected_layout_id", "batch_browse_layout_id",
    ):
        st.session_state.pop(key, None)


def _load_synthetic_footprint() -> None:
    _reset_footprint(3, 4, SYNTHETIC_CELLS)


def _new_large_canvas() -> None:
    _reset_footprint(DEFAULT_SKETCH_ROWS, DEFAULT_SKETCH_COLUMNS, [])


def _initialize() -> None:
    if st.session_state.get("batch_ui_initialized"):
        return
    st.session_state["batch_ui_initialized"] = True
    st.session_state["batch_custom_reference"] = False
    st.session_state["batch_workers"] = 1
    st.session_state["batch_sketcher_revision"] = 0
    _new_large_canvas()


def _footprint_editor(screenshot_mode: bool, demo_acknowledged: bool) -> tuple[int, int, list[tuple[int, int]], list[str]]:
    st.subheader(t("batch.step1"))
    if not screenshot_mode:
        st.caption(t("batch.draw_help"))
        new_canvas, sample = st.columns(2)
        if new_canvas.button(t("batch.new_canvas"), use_container_width=True):
            _new_large_canvas()
        if sample.button(t("batch.load_synthetic"), use_container_width=True):
            _load_synthetic_footprint()
    if not demo_acknowledged and not screenshot_mode:
        st.info(t("batch.demo_notice"))

    a, b = st.columns(2)
    rows = int(localized_number_input(a, t("field.grid_rows"), "batch_grid_rows", min_value=1, step=1))
    columns = int(localized_number_input(b, t("field.grid_columns"), "batch_grid_cols", min_value=1, step=1))
    current = [
        tuple(cell) for cell in st.session_state.get("batch_occupied_cells", [])
        if 0 <= int(cell[0]) < rows and 0 <= int(cell[1]) < columns
    ]
    if current != st.session_state.get("batch_occupied_cells"):
        st.session_state["batch_occupied_cells"] = current
    occupied = render_footprint_sketcher(
        rows,
        columns,
        current,
        key="batch_footprint_sketcher",
        revision=st.session_state.get("batch_sketcher_revision", 0),
        strings={
            "brush": t("canvas.brush"), "brush_help": t("canvas.brush_help"),
            "rectangle": t("canvas.rectangle"), "rectangle_help": t("canvas.rectangle_help"),
            "eraser": t("canvas.eraser"), "eraser_help": t("canvas.eraser_help"),
            "erase_rectangle": t("canvas.erase_rectangle"), "erase_rectangle_help": t("canvas.erase_rectangle_help"),
            "undo": t("canvas.undo"), "redo": t("canvas.redo"), "clear": t("canvas.clear"),
            "fill": t("canvas.fill"), "invert": t("canvas.invert"), "zoom_out": t("canvas.zoom_out"),
            "fit": t("canvas.fit"), "zoom_in": t("canvas.zoom_in"), "occupied": t("footprint.occupied"),
            "cell_count": t("footprint.cell_count"), "connectivity": t("footprint.connectivity"),
            "even": t("status.even"), "odd": t("status.odd"), "connected": t("status.connected"),
            "disconnected": t("status.disconnected"), "mouse_help": t("canvas.mouse_help"),
        },
        rtl=is_rtl(),
    )
    st.session_state["batch_occupied_cells"] = occupied
    errors = validate_footprint_cells(rows, columns, occupied)
    signature = footprint_signature(rows, columns, occupied)
    if invalidate_footprint_state(st.session_state, signature):
        st.warning(t("batch.changed"))
    connected = bool(occupied) and not any("connected" in error.lower() for error in errors)
    status_columns = st.columns(3)
    status_columns[0].metric(t("footprint.occupied"), len(occupied))
    status_columns[1].metric(t("footprint.cell_count"), t("status.even") if len(occupied) % 2 == 0 else t("status.odd"))
    status_columns[2].metric(t("footprint.connectivity"), t("status.connected") if connected else t("status.disconnected"))
    for error in errors:
        st.error(localize_validation(error))
    if not errors:
        st.success(t("batch.footprint_ready"))
    else:
        st.caption(t("batch.resolve_footprint"))
    if not screenshot_mode:
        with st.expander(t("batch.advanced_footprint"), expanded=False):
            st.caption(t("batch.coordinate_note"))
            st.dataframe(
                pd.DataFrame(occupied, columns=["row", "column"]),
                use_container_width=True,
                hide_index=True,
            )
            export_payload = footprint_data_json(rows, columns, occupied)
            io_columns = st.columns(2)
            io_columns[0].download_button(
                t("batch.export_footprint"),
                data=export_payload,
                file_name="moduport_footprint.json",
                mime="application/json",
                use_container_width=True,
            )
            uploaded = io_columns[1].file_uploader(
                t("batch.import_footprint"),
                type=["json"],
                key="batch_footprint_upload",
                label_visibility="collapsed",
            )
            if st.button(t("batch.apply_footprint"), disabled=uploaded is None, use_container_width=True):
                try:
                    imported_rows, imported_columns, imported_cells = parse_footprint_data(uploaded.getvalue())
                    st.session_state["batch_grid_rows"] = imported_rows
                    st.session_state["batch_grid_cols"] = imported_columns
                    st.session_state["batch_occupied_cells"] = imported_cells
                    st.session_state["batch_sketcher_revision"] = int(st.session_state.get("batch_sketcher_revision", 0)) + 1
                    st.rerun()
                except (ValueError, TypeError) as error:
                    st.error(t("validation.generic"))
    return rows, columns, occupied, errors


def _layout_generation(rows: int, columns: int, occupied: list[tuple[int, int]], errors: list[str]):
    st.subheader(t("batch.step2"))
    if st.button(t("action.generate_layouts"), type="primary", disabled=bool(errors), use_container_width=True):
        start = time.perf_counter()
        layouts = enumerate_layouts(Footprint.from_cells(occupied), id_prefix="L")
        st.session_state["batch_layouts"] = layouts
        st.session_state["batch_enumeration_runtime_s"] = time.perf_counter() - start
        for key in ("batch_screening_results", "batch_screening_runtime_s", "batch_screening_structural_signature", "batch_results_stale", "batch_selected_layout_id"):
            st.session_state.pop(key, None)

    layouts = st.session_state.get("batch_layouts")
    if layouts is None:
        st.caption(t("batch.explicit_enumeration"))
        return None, None
    runtime = float(st.session_state.get("batch_enumeration_runtime_s", 0.0))
    metrics = st.columns(3)
    metrics[0].metric(t("footprint.occupied"), len(occupied))
    metrics[1].metric(t("batch.feasible_layouts"), len(layouts))
    metrics[2].metric(t("batch.enumeration_time"), f"{runtime:.4f} s")
    if not layouts:
        st.error(t("batch.no_covering"))
        return layouts, None
    if len(layouts) >= LARGE_LAYOUT_WARNING:
        st.warning(t("batch.large_warning", count=f"{len(layouts):,}"))

    identifiers = [layout.layout_id for layout in layouts]
    if st.session_state.get("batch_browse_layout_id") not in identifiers:
        st.session_state["batch_browse_layout_id"] = identifiers[0]
    selected_id = st.selectbox(t("batch.browse_layout"), identifiers, key="batch_browse_layout_id")
    selected = next(layout for layout in layouts if layout.layout_id == selected_id)
    st.caption(t("batch.layout_position", index=identifiers.index(selected_id) + 1, total=len(layouts), horizontal=selected.n_h, vertical=selected.n_v))
    st.markdown(render_screening_layout_svg(selected), unsafe_allow_html=True)
    return layouts, selected


def _base_configuration(rows: int, columns: int, selected_layout):
    st.subheader(t("batch.step3"))
    section_table = render_structural_properties(t("section.structural_batch"))
    with st.expander(t("batch.directional_loads"), expanded=False):
        st.caption(t("batch.directional_help"))
        load_table = render_load_editor()
    custom = st.checkbox(t("batch.custom_reference"), key="batch_custom_reference")
    if custom:
        a, b = st.columns(2)
        reference_x = float(a.number_input(t("field.reference_x"), key="batch_reference_x_mm"))
        reference_y = float(b.number_input(t("field.reference_y"), key="batch_reference_y_mm"))
    else:
        reference_x = reference_y = 0.0
        st.caption(t("batch.auto_reference"))

    if selected_layout is None:
        return None, None
    sections = sections_from_table(section_table)
    values = shared_values(st.session_state, load_table)
    values.update({
        "grid_rows": rows,
        "grid_cols": columns,
        "reference_x_mm": reference_x,
        "reference_y_mm": reference_y,
    })
    base = assemble_config(values, placements_from_layout(selected_layout), sections)
    base["sample_id"] = "USER_BATCH_SCREENING"
    if not custom:
        base.pop("reference_point", None)
    try:
        reference = resolved_reference_point(base, selected_layout)
        st.success(t("batch.reference_used", x=f"{reference[0]:.3f}", y=f"{reference[1]:.3f}"))
    except Exception as error:
        st.error(t("batch.invalid_config"))
        return None, None
    signature = structural_signature(base, custom)
    update_stale_state(st.session_state, signature)
    return base, signature


def _run_screening(layouts, base_config, signature, screenshot_mode: bool):
    st.subheader(t("batch.step4"))
    logical_cpus = max(1, os.cpu_count() or 1)
    if screenshot_mode:
        workers = int(st.session_state.get("batch_workers", 1))
    else:
        workers = int(st.number_input(t("batch.worker_count"), min_value=1, max_value=logical_cpus, step=1, key="batch_workers"))
        st.caption(t("batch.cpu_help", count=logical_cpus))
    disabled = not layouts or base_config is None
    if st.button(t("action.run_screening"), type="primary", disabled=disabled, use_container_width=True):
        progress_bar = st.progress(0.0)
        status = st.empty()

        def report(event):
            progress_bar.progress(event.completed / max(event.total, 1))
            status.write(t("batch.progress", completed=event.completed, total=event.total, success=event.succeeded, failed=event.failed, layout_id=event.latest_layout_id))

        start = time.perf_counter()
        try:
            results = screen_layouts(base_config, layouts, workers=workers, progress=report)
            elapsed = time.perf_counter() - start
            st.session_state["batch_screening_results"] = results
            st.session_state["batch_screening_runtime_s"] = elapsed
            st.session_state["batch_screening_structural_signature"] = signature
            st.session_state["batch_results_stale"] = False
            progress_bar.progress(1.0)
            solved = sum(record.success for record in results)
            status.success(t("batch.screening_complete", success=solved, total=len(results), seconds=f"{elapsed:.3f}"))
        except Exception as error:
            status.error(t("batch.screening_failed"))
    if st.session_state.get("batch_results_stale"):
        st.warning(t("batch.results_stale"))


def _explore_results(layouts, base_config, screenshot_mode: bool):
    st.subheader(t("batch.step5"))
    results = st.session_state.get("batch_screening_results")
    if results is None:
        st.caption(t("batch.run_prompt"))
        return
    rows, flags, balanced_id = result_display_rows(results)
    successful = sum(row["status"] == "success" for row in rows)
    pareto_count = sum(row["Pareto"] for row in rows)
    balanced_row = next((row for row in rows if row["Balanced"]), None)
    elapsed = float(st.session_state.get("batch_screening_runtime_s", 0.0))
    metric_items = (
        (t("metric.total_feasible"), len(layouts)),
        (t("metric.successful"), successful),
        (t("metric.pareto"), pareto_count),
        (t("metric.balanced"), balanced_id or "—"),
        (t("metric.balanced_kx"), "—" if balanced_row is None else f"{balanced_row['KX_N_per_mm']:,.0f}"),
        (t("metric.balanced_ky"), "—" if balanced_row is None else f"{balanced_row['KY_N_per_mm']:,.0f}"),
        (t("metric.screening_time"), f"{elapsed:.3f} s"),
    )
    for metric_row in (metric_items[:4], metric_items[4:]):
        for card, (label, value) in zip(st.columns(len(metric_row)), metric_row):
            card.metric(label, value)

    result_ids = [row["layout_id"] for row in rows]
    if balanced_id and st.button(t("action.show_balanced"), use_container_width=True):
        st.session_state["batch_selected_layout_id"] = balanced_id
    if st.session_state.get("batch_selected_layout_id") not in result_ids:
        st.session_state["batch_selected_layout_id"] = balanced_id or result_ids[0]
    selected_id = st.selectbox(t("batch.select_layout"), result_ids, key="batch_selected_layout_id")
    selected_index = result_ids.index(selected_id)
    selected_record = results[selected_index]
    selected_row = rows[selected_index]
    plot_column, selected_column = st.columns([0.64, 0.36], gap="large")
    plot_rows = design_space_rows(results)
    with plot_column:
        if plot_rows:
            frame = pd.DataFrame(plot_rows)
            frame["Display class"] = frame["Category"].replace({"Ordinary": t("plot.ordinary"), "Pareto": t("plot.pareto"), "Balanced": t("plot.balanced")})
            classes = [t("plot.ordinary"), t("plot.pareto"), t("plot.balanced")]
            chart = (
                alt.Chart(frame)
                .mark_circle(opacity=0.88, stroke="#ffffff", strokeWidth=0.8)
                .encode(
                    x=alt.X("KX_N_per_mm:Q", title="KX (N/mm)", scale=alt.Scale(zero=False)),
                    y=alt.Y("KY_N_per_mm:Q", title="KY (N/mm)", scale=alt.Scale(zero=False)),
                    color=alt.Color(
                        "Display class:N",
                        scale=alt.Scale(domain=classes, range=["#AAB2BD", "#E45756", "#2CA25F"]),
                        legend=alt.Legend(title=t("plot.class"), orient="top"),
                    ),
                    size=alt.Size(
                        "Display class:N",
                        scale=alt.Scale(domain=classes, range=[45, 95, 180]),
                        legend=None,
                    ),
                    tooltip=[
                        alt.Tooltip("layout_id:N", title=t("plot.layout")),
                        alt.Tooltip("KX_N_per_mm:Q", title="KX (N/mm)", format=".4g"),
                        alt.Tooltip("KY_N_per_mm:Q", title="KY (N/mm)", format=".4g"),
                        alt.Tooltip("H_count:Q", title=t("plot.h_modules")),
                        alt.Tooltip("V_count:Q", title=t("plot.v_modules")),
                        alt.Tooltip("Display class:N", title=t("plot.class")),
                    ],
                )
                .properties(title=t("plot.title"), height=430)
                .interactive()
            )
            st.altair_chart(chart, use_container_width=True)
    with selected_column:
        st.markdown(f'**{t("batch.selected_layout")}**')
        st.markdown(render_screening_layout_svg(selected_record.layout), unsafe_allow_html=True)
        summary = st.columns(2)
        summary[0].metric("KX (N/mm)", "—" if selected_row["KX_N_per_mm"] is None else f"{selected_row['KX_N_per_mm']:,.0f}")
        summary[1].metric("KY (N/mm)", "—" if selected_row["KY_N_per_mm"] is None else f"{selected_row['KY_N_per_mm']:,.0f}")
        runtime_text = "—" if selected_row["runtime_s"] is None else f"{selected_row['runtime_s']:.3f} s"
        st.caption(t("batch.layout_summary", layout_id=selected_id, horizontal=selected_row["H_count"], vertical=selected_row["V_count"], pareto=t("status.yes") if selected_row["Pareto"] else t("status.no"), balanced=t("status.yes") if selected_row["Balanced"] else t("status.no"), status=t(f"status.{selected_row['status']}"), runtime=runtime_text))
        if selected_row["error"]:
            st.error(t("batch.screening_failed"))

    if not screenshot_mode:
        st.markdown(f'**{t("batch.results")}**')
        status_options = sorted({row["status"] for row in rows})
        status_labels = [t(f"status.{value}") for value in status_options]
        status_label_to_value = dict(zip(status_labels, status_options))
        canonical_status = st.session_state.get("batch_result_status_values", status_options)
        status_key = f"batch_result_status_filter_{current_locale()}"
        if status_key not in st.session_state:
            st.session_state[status_key] = [t(f"status.{value}") for value in canonical_status if value in status_options]
        visible_labels = st.multiselect(t("batch.filter_status"), status_labels, key=status_key)
        visible_status = [status_label_to_value[label] for label in visible_labels]
        st.session_state["batch_result_status_values"] = visible_status
        filtered_rows = [row for row in rows if row["status"] in visible_status]
        display_frame = pd.DataFrame(filtered_rows)
        if not display_frame.empty:
            display_frame["status"] = display_frame["status"].map(lambda value: t(f"status.{value}"))
            display_frame["error"] = display_frame["error"].map(lambda value: "" if not value else t("batch.screening_failed"))
        display_frame = display_frame.rename(columns={
            "layout_id": t("column.layout"),
            "H_count": t("column.h_modules"),
            "V_count": t("column.v_modules"),
            "KX_N_per_mm": "KX (N/mm)",
            "KY_N_per_mm": "KY (N/mm)",
            "Balanced": t("column.balanced"),
            "runtime_s": t("column.runtime"),
            "status": t("column.status"),
            "error": t("column.error"),
        })
        st.dataframe(display_frame, use_container_width=True, hide_index=True)
        export_columns = st.columns(3)
        export_columns[0].download_button(
            t("download.results_csv"), data=results_csv(results), file_name="moduport_screening_results.csv", mime="text/csv", use_container_width=True,
        )
        export_columns[1].download_button(
            t("download.selected_json"),
            data=selected_layout_json(selected_record, pareto=flags[selected_index], balanced=selected_id == balanced_id),
            file_name=f"{selected_id}.json", mime="application/json", use_container_width=True,
        )
        if base_config is not None:
            export_columns[2].download_button(
                t("download.config_json"), data=footprint_config_json(base_config, selected_record.layout),
                file_name="moduport_screening_config.json", mime="application/json", use_container_width=True,
            )


def render_batch_screening(*, screenshot_mode: bool = False, demo_acknowledged: bool = False) -> None:
    _initialize()
    page_header(t("page.batch"))
    workflow_strip([t("workflow.define_footprint"), t("workflow.generate_layouts"), t("workflow.set_properties"), t("workflow.run_screening"), t("workflow.explore")])
    rows, columns, occupied, errors = _footprint_editor(screenshot_mode, demo_acknowledged)
    layouts, selected_layout = _layout_generation(rows, columns, occupied, errors)
    base_config, signature = _base_configuration(rows, columns, selected_layout)
    _run_screening(layouts, base_config, signature, screenshot_mode)
    _explore_results(layouts, base_config, screenshot_mode)


__all__ = ["render_batch_screening"]
