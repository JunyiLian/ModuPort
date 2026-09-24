"""Paper-ready result presentation for the Single Model workflow."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from .i18n import t


def _mode_label(value: str) -> str:
    normalized = str(value).lower()
    if "x" in normalized and "dominant" in normalized:
        return t("mode.x")
    if "y" in normalized and "dominant" in normalized:
        return t("mode.y")
    if "tors" in normalized:
        return t("mode.torsional")
    return t("mode.mixed")


def _static_summary(static: dict) -> None:
    cases = list(static["storey_response"])
    if not cases:
        return
    selected_case = st.selectbox(t("result.load_case"), cases, key="single_result_case")
    storeys = static["storey_response"][selected_case]
    roof = storeys[-1]
    energy = float(static["strain_energy"].get(selected_case, float("nan")))
    cards = st.columns(4)
    cards[0].metric(t("result.roof_ux"), f"{float(roof['ux_bar']):.4g}")
    cards[1].metric(t("result.roof_uy"), f"{float(roof['uy_bar']):.4g}")
    cards[2].metric(t("result.roof_rz"), f"{float(roof['theta_z_bar']):.4g}")
    cards[3].metric(t("result.strain_energy"), f"{energy:.4g}")
    rows = [
        {
            t("result.storey"): index + 1,
            "UX (mm)": float(row["ux_bar"]),
            "UY (mm)": float(row["uy_bar"]),
            "RZ (rad)": float(row["theta_z_bar"]),
            t("result.distortion_norm"): float(row["distortion_norm"]),
            t("result.distortion_ratio"): float(row["distortion_ratio"]),
        }
        for index, row in enumerate(storeys)
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _advanced_static(static: dict) -> None:
    with st.expander(t("result.advanced_static"), expanded=False):
        for title, field, component_label in (
            (t("result.support_reactions"), "reactions", t("result.component_index")),
            (t("result.port_displacements"), "port_displacements", t("result.dof_index")),
        ):
            st.markdown(f"**{title}**")
            rows = [
                {t("result.load_case_column"): case, component_label: index, t("result.mixed_response"): value}
                for case, values in static[field].items()
                for index, value in enumerate(values)
            ]
            st.dataframe(rows, use_container_width=True, hide_index=True)
        for title, field in (
            (t("result.horizontal_vectors"), "horizontal_link_forces"),
            (t("result.vertical_vectors"), "vertical_link_forces"),
        ):
            st.markdown(f"**{title}**")
            rows = [
                {t("result.load_case_column"): case, t("result.connection"): link, t("result.component_index"): index, t("result.mixed_force"): value}
                for case, links in static[field].items()
                for link, values in links.items()
                for index, value in enumerate(values)
            ]
            st.dataframe(rows, use_container_width=True, hide_index=True)
        st.markdown(f'**{t("result.strain_energy")}**')
        st.dataframe(
            [{t("result.load_case_column"): case, t("result.strain_energy"): value} for case, value in static["strain_energy"].items()],
            use_container_width=True,
            hide_index=True,
        )
    with st.expander(t("result.qa_static"), expanded=False):
        st.json(static["qa"])


def _modal_summary(modal: dict) -> None:
    frequencies = modal["frequencies_hz"]
    periods = modal["periods_s"]
    types = modal["modal_types"]
    if frequencies:
        cards = st.columns(3)
        cards[0].metric(t("result.first_frequency"), f"{float(frequencies[0]):.4g}")
        cards[1].metric(t("result.first_period"), f"{float(periods[0]):.4g}")
        cards[2].metric(t("result.first_mode"), _mode_label(types[0]))
    rows = [
        {
            t("result.mode"): index + 1,
            t("result.frequency"): float(frequency),
            t("result.period"): float(periods[index]),
            t("result.dominant"): _mode_label(types[index]),
        }
        for index, frequency in enumerate(frequencies)
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    with st.expander(t("result.qa_modal"), expanded=False):
        st.json(modal["qa"])


def render_single_results(results: dict, screenshot_mode: bool = False) -> None:
    if not results:
        st.markdown(f'<div class="mp-note">{t("result.run_prompt")}</div>', unsafe_allow_html=True)
        return
    available = []
    if "static" in results:
        available.append(("static", t("result.static_tab")))
    if "modal" in results:
        available.append(("modal", t("result.modal_tab")))
    st.subheader(t("result.heading"))
    tabs = st.tabs([label for _, label in available])
    for tab, (kind, _) in zip(tabs, available):
        with tab:
            if kind == "static":
                _static_summary(results["static"])
                if not screenshot_mode:
                    _advanced_static(results["static"])
            else:
                _modal_summary(results["modal"])


__all__ = ["render_single_results"]
