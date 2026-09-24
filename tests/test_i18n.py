from __future__ import annotations

import ast
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch
import unittest

import numpy as np
from streamlit.testing.v1 import AppTest

from web.i18n import (
    DEFAULT_LOCALE,
    NATIVE_LANGUAGE_NAMES,
    SUPPORTED_LOCALES,
    is_rtl,
    load_catalog,
    placeholder_names,
    translate,
)
from web.batch_screening import results_csv
from web.ui_config import LOAD_CASES, config_to_json, execute_analysis
from moduport import Footprint, enumerate_layouts, pareto_flags, screen_layouts, select_balanced_layout
from tests.synthetic_config import build_synthetic_config


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "web" / "streamlit_app.py"
LOCALE_DIR = ROOT / "web" / "locales"
IRREGULAR = {
    (0, 0), (0, 1),
    (1, 0), (1, 1), (1, 2), (1, 3),
    (2, 2), (2, 3),
}


class LocaleResourceTests(unittest.TestCase):
    def test_all_catalogs_are_well_formed_complete_and_without_duplicate_keys(self):
        english_keys = set(load_catalog(DEFAULT_LOCALE))

        def no_duplicates(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise AssertionError(f"duplicate locale key: {key}")
                result[key] = value
            return result

        for locale in SUPPORTED_LOCALES:
            path = LOCALE_DIR / f"{locale}.json"
            self.assertTrue(path.is_file())
            raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicates)
            self.assertEqual(set(raw), english_keys, locale)
            self.assertTrue(all(isinstance(value, str) and value for value in raw.values()))
            for key in english_keys:
                self.assertEqual(placeholder_names(raw[key]), placeholder_names(load_catalog(DEFAULT_LOCALE)[key]), (locale, key))

    def test_english_fallback_and_dynamic_placeholders(self):
        english = {"example": "Solved {success}/{total} layouts."}
        with patch("web.i18n.load_catalog", side_effect=lambda locale: english if locale == "en" else {}):
            self.assertEqual(translate("example", locale="fr", success=3, total=4), "Solved 3/4 layouts.")
        self.assertIn("12/12", translate("batch.screening_complete", locale="en", success=12, total=12, seconds="1.25"))

    def test_arabic_is_the_only_rtl_locale(self):
        self.assertTrue(is_rtl("ar"))
        self.assertTrue(all(not is_rtl(locale) for locale in SUPPORTED_LOCALES if locale != "ar"))

    def test_engineering_symbols_and_units_are_preserved(self):
        contracts = {
            "field.elastic_modulus": ("E", "N/mm²"),
            "field.shear_modulus": ("G", "N/mm²"),
            "column.area": ("A", "mm²"),
            "result.first_frequency": ("Hz",),
            "result.first_period": ("s",),
            "result.roof_ux": ("UX", "mm"),
            "result.roof_uy": ("UY", "mm"),
            "result.roof_rz": ("RZ", "rad"),
        }
        for locale in SUPPORTED_LOCALES:
            for key, tokens in contracts.items():
                value = translate(key, locale=locale)
                for token in tokens:
                    self.assertIn(token, value, (locale, key, token))

    def test_no_untranslated_literal_streamlit_labels(self):
        methods = {
            "subheader", "caption", "info", "warning", "error", "success", "button", "number_input",
            "checkbox", "radio", "selectbox", "multiselect", "download_button", "expander", "write",
            "markdown", "file_uploader", "spinner",
        }
        allowed = {"KX (N/mm)", "KY (N/mm)"}
        violations = []
        for path in (ROOT / "web").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr not in methods or not node.args:
                    continue
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str) and first.value not in allowed:
                    violations.append((path.name, node.lineno, first.value))
        self.assertEqual(violations, [])


class MultilingualUiTests(unittest.TestCase):
    def test_single_batch_and_sketcher_render_in_every_locale(self):
        for locale in SUPPORTED_LOCALES:
            with self.subTest(locale=locale):
                app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
                app.sidebar.selectbox[0].set_value(NATIVE_LANGUAGE_NAMES[locale]).run()
                self.assertFalse(app.exception)
                self.assertTrue(any(button.label == translate("action.run_analysis", locale=locale) for button in app.button))
                app.sidebar.radio[0].set_value(translate("nav.batch", locale=locale)).run()
                self.assertFalse(app.exception)
                self.assertTrue(any(button.label == translate("batch.new_canvas", locale=locale) for button in app.button))
                self.assertTrue(any(translate("batch.step1", locale=locale) in item.value for item in app.subheader))

    def test_language_switch_preserves_model_and_batch_state(self):
        app = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
        next(button for button in app.button if button.label == translate("action.run_analysis", locale="en")).click().run(timeout=60)
        analysis_before = json.dumps(app.session_state["analysis_results"], sort_keys=True)
        grid_rows = next(item for item in app.number_input if item.key == "grid_rows__en")
        grid_rows.set_value(5).run()
        next(item for item in app.number_input if item.key == "E_N_mm2__en").set_value(200001.0).run()
        app.sidebar.selectbox[0].set_value(NATIVE_LANGUAGE_NAMES["zh-CN"]).run()
        self.assertEqual(next(item for item in app.number_input if item.key == "grid_rows__zh-CN").value, 5)
        self.assertEqual(next(item for item in app.number_input if item.key == "E_N_mm2__zh-CN").value, 200001.0)
        self.assertEqual(json.dumps(app.session_state["analysis_results"], sort_keys=True), analysis_before)
        app.sidebar.radio[0].set_value(translate("nav.batch", locale="zh-CN")).run()
        next(button for button in app.button if button.label == translate("batch.load_synthetic", locale="zh-CN")).click().run()
        next(button for button in app.button if button.label == translate("action.generate_layouts", locale="zh-CN")).click().run()
        signatures = [layout.signature for layout in app.session_state["batch_layouts"]]
        next(button for button in app.button if button.label == translate("action.run_screening", locale="zh-CN")).click().run(timeout=60)
        screening_before = tuple((row.layout_id, row.status, row.kx_n_per_mm, row.ky_n_per_mm) for row in app.session_state["batch_screening_results"])
        app.sidebar.selectbox[0].set_value(NATIVE_LANGUAGE_NAMES["fr"]).run()
        self.assertEqual([layout.signature for layout in app.session_state["batch_layouts"]], signatures)
        self.assertEqual(set(app.session_state["batch_occupied_cells"]), IRREGULAR)
        self.assertEqual(tuple((row.layout_id, row.status, row.kx_n_per_mm, row.ky_n_per_mm) for row in app.session_state["batch_screening_results"]), screening_before)

    def test_arabic_rtl_and_screenshot_language(self):
        app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
        app.sidebar.selectbox[0].set_value(NATIVE_LANGUAGE_NAMES["ar"]).run()
        self.assertTrue(any("direction: rtl" in value.value for value in app.markdown))
        app.sidebar.toggle[0].set_value(True).run()
        self.assertEqual(app.sidebar.selectbox[0].value, NATIVE_LANGUAGE_NAMES["ar"])
        self.assertTrue(any(button.label == translate("action.run_analysis", locale="ar") for button in app.button))


class NumericalLocaleInvarianceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = build_synthetic_config()
        cls.layouts = enumerate_layouts(Footprint.from_cells(IRREGULAR), id_prefix="I")

    def test_static_modal_outputs_are_locale_invariant(self):
        baseline = None
        for locale in SUPPORTED_LOCALES:
            translate("message.analysis_running", locale=locale)
            results = execute_analysis(deepcopy(self.config), "Both", list(LOAD_CASES), 3)
            fingerprint = results
            if baseline is None:
                baseline = fingerprint
            self.assertEqual(fingerprint["static"]["storey_response"], baseline["static"]["storey_response"], locale)
            self.assertEqual(fingerprint["static"]["strain_energy"], baseline["static"]["strain_energy"], locale)
            np.testing.assert_allclose(fingerprint["modal"]["frequencies_hz"], baseline["modal"]["frequencies_hz"], rtol=1e-10, atol=1e-12)
            np.testing.assert_allclose(fingerprint["modal"]["periods_s"], baseline["modal"]["periods_s"], rtol=1e-10, atol=1e-12)

    def test_screening_pareto_and_balance_are_locale_invariant(self):
        baseline = None
        for locale in SUPPORTED_LOCALES:
            translate("action.run_screening", locale=locale)
            results = screen_layouts(deepcopy(self.config), self.layouts, workers=1)
            fingerprint = (
                tuple((row.layout_id, row.status, row.kx_n_per_mm, row.ky_n_per_mm) for row in results),
                pareto_flags(results),
                select_balanced_layout(results).layout_id,
            )
            if baseline is None:
                baseline = fingerprint
            self.assertEqual(fingerprint, baseline, locale)

    def test_json_and_csv_export_semantics_are_locale_invariant(self):
        results = screen_layouts(deepcopy(self.config), self.layouts, workers=1)
        baseline = None
        for locale in SUPPORTED_LOCALES:
            translate("action.download_csv", locale=locale)
            fingerprint = (config_to_json(self.config), results_csv(results))
            if baseline is None:
                baseline = fingerprint
            self.assertEqual(fingerprint, baseline, locale)


if __name__ == "__main__":
    unittest.main(verbosity=2)
