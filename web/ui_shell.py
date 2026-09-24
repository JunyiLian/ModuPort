"""Shared presentation shell for the ModuPort Streamlit application."""

from __future__ import annotations

import streamlit as st

from .i18n import NATIVE_LANGUAGE_NAMES, SUPPORTED_LOCALES, current_locale, is_rtl, t


APP_NAME = "ModuPort"
APP_VERSION = "0.1.0"
APP_SUBTITLE = "Mechanics-based superelement analysis and layout screening for multi-storey framed modular structures"
LANGUAGE_WIDGET_LABEL = "Language"


def apply_app_style(screenshot_mode: bool = False) -> None:
    """Apply compact engineering-style presentation rules without changing behaviour."""
    def css_text(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    file_drop = css_text(t("file.drop"))
    file_limit = css_text(t("file.limit"))
    file_browse = css_text(t("file.browse"))
    screenshot_rules = """
        [data-testid="stToolbar"], [data-testid="stDecoration"], #MainMenu, footer {display: none !important;}
        header[data-testid="stHeader"] {height: 0 !important; background: transparent !important;}
        .block-container {padding-top: 1.1rem !important;}
    """ if screenshot_mode else ""
    direction_rules = """
        .stApp, [data-testid="stSidebar"] {direction: rtl; text-align: right;}
        [data-testid="stMetricValue"], [data-testid="stDataFrame"], .vega-embed, code, pre, svg {direction: ltr;}
        input {text-align: left; direction: ltr;}
        .mp-flow {flex-direction: row-reverse;}
    """ if is_rtl() else ""
    st.markdown(
        f"""
        <style>
        :root {{ --mp-ink: #1f2933; --mp-blue: #3b6f8f; --mp-line: #d8dee4; --mp-soft: #f5f7f9; }}
        .block-container {{max-width: 1440px; padding-top: 2rem; padding-bottom: 2rem;}}
        h1 {{font-size: 2.15rem !important; letter-spacing: -0.02em; color: var(--mp-ink); margin-bottom: 0.1rem !important;}}
        h2 {{font-size: 1.45rem !important; color: var(--mp-ink); margin-top: 1.25rem !important;}}
        h3 {{font-size: 1.08rem !important; color: var(--mp-ink); margin-top: 1rem !important;}}
        [data-testid="stMetric"] {{background: var(--mp-soft); border: 1px solid var(--mp-line); border-radius: 0.35rem; padding: 0.65rem 0.8rem;}}
        [data-testid="stMetricLabel"] {{font-weight: 600; color: #52606d;}}
        [data-testid="stExpander"] {{border: 1px solid var(--mp-line); border-radius: 0.35rem;}}
        [data-testid="stFileUploaderDropzoneInstructions"] div > span {{font-size:0 !important;}}
        [data-testid="stFileUploaderDropzoneInstructions"] div > span::after {{content:"{file_drop}"; font-size:0.95rem;}}
        [data-testid="stFileUploaderDropzoneInstructions"] small {{font-size:0 !important;}}
        [data-testid="stFileUploaderDropzoneInstructions"] small::after {{content:"{file_limit} · JSON"; font-size:0.8rem;}}
        [data-testid="stFileUploaderDropzone"] > button {{font-size:0 !important;}}
        [data-testid="stFileUploaderDropzone"] > button::after {{content:"{file_browse}"; font-size:0.875rem;}}
        .mp-eyebrow {{font-size: 0.78rem; font-weight: 700; letter-spacing: 0.08em; color: var(--mp-blue); text-transform: uppercase; margin-bottom: 0.1rem;}}
        .mp-subtitle {{font-size: 1rem; color: #52606d; margin-bottom: 1.15rem;}}
        .mp-flow {{display:flex; align-items:center; gap:0.55rem; flex-wrap:wrap; margin:0.4rem 0 1.1rem 0;}}
        .mp-flow span {{border:1px solid var(--mp-line); background:#fff; border-radius:999px; padding:0.32rem 0.7rem; font-size:0.82rem; color:#364152;}}
        .mp-flow b {{color:#8a98a6; font-weight:400;}}
        .mp-note {{border-left:3px solid var(--mp-blue); background:var(--mp-soft); padding:0.6rem 0.8rem; color:#52606d; font-size:0.88rem;}}
        {direction_rules}
        {screenshot_rules}
        </style>
        """,
        unsafe_allow_html=True,
    )


def page_header(section: str) -> None:
    st.markdown(f'<div class="mp-eyebrow">{section}</div>', unsafe_allow_html=True)
    st.title(APP_NAME)
    st.markdown(f'<div class="mp-subtitle">{t("app.subtitle")}</div>', unsafe_allow_html=True)


def workflow_strip(items: list[str]) -> None:
    content = "<b>→</b>".join(f"<span>{item}</span>" for item in items)
    st.markdown(f'<div class="mp-flow">{content}</div>', unsafe_allow_html=True)


def sidebar_controls() -> tuple[str, bool, bool]:
    st.session_state.setdefault("locale", "en")
    names = list(NATIVE_LANGUAGE_NAMES.values())
    name_to_locale = {name: locale for locale, name in NATIVE_LANGUAGE_NAMES.items()}
    st.session_state.setdefault("language_choice", NATIVE_LANGUAGE_NAMES.get(current_locale(), "English"))
    st.session_state["locale"] = name_to_locale.get(st.session_state["language_choice"], "en")

    st.sidebar.markdown(f"### {APP_NAME}")
    st.sidebar.caption(t("sidebar.version", version=APP_VERSION))
    st.sidebar.markdown(f'**{t("language.label")}**')
    language_choice = st.sidebar.selectbox(
        LANGUAGE_WIDGET_LABEL,
        names,
        key="language_choice",
        label_visibility="collapsed",
    )
    st.session_state["locale"] = name_to_locale.get(language_choice, "en")
    navigation_values = ["single", "batch", "about"]
    navigation_labels = [t(f"nav.{value}") for value in navigation_values]
    navigation_label_to_value = dict(zip(navigation_labels, navigation_values))
    navigation_value = st.session_state.get("workflow_navigation", "single")
    navigation_key = f"workflow_navigation_display_{current_locale()}"
    if navigation_key not in st.session_state:
        st.session_state[navigation_key] = navigation_labels[navigation_values.index(navigation_value)]
    navigation_display = st.sidebar.radio(
        t("nav.workflow"),
        navigation_labels,
        key=navigation_key,
    )
    navigation = navigation_label_to_value[navigation_display]
    st.session_state["workflow_navigation"] = navigation
    st.sidebar.divider()
    screenshot_mode = st.sidebar.toggle(
        t("sidebar.screenshot"),
        key="screenshot_mode",
        help=t("sidebar.screenshot_help"),
    )
    demo_acknowledged = st.sidebar.checkbox(
        t("sidebar.acknowledge"),
        key="demo_acknowledged",
        help=t("sidebar.acknowledge_help"),
    )
    return navigation, screenshot_mode, demo_acknowledged


def render_about_page() -> None:
    page_header(t("page.software"))
    left, right = st.columns([0.58, 0.42], gap="large")
    with left:
        st.subheader(t("about.heading"))
        st.write(t("about.description"))
        st.caption(t("about.full_title"))
        st.markdown(f'**{t("about.scope")}**')
        st.markdown(t("about.scope_list"))
        st.markdown(f'**{t("about.domain")}**')
        st.write(t("about.domain_text"))
        st.markdown(f'**{t("about.solver")}**')
        st.write(t("about.solver_text"))
    with right:
        st.metric(t("about.version"), APP_VERSION)
        st.markdown(f'**{t("about.limitations")}**')
        st.markdown(t("about.limitations_list"))
    st.subheader(t("about.architecture"))
    workflow_strip([t("architecture.ui"), t("architecture.api"), t("architecture.layout"), t("architecture.solver"), t("architecture.core")])


__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "APP_SUBTITLE",
    "apply_app_style",
    "page_header",
    "workflow_strip",
    "sidebar_controls",
    "render_about_page",
]
