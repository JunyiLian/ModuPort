from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import numpy as np
from streamlit.testing.v1 import AppTest

from web.layout_editor import ModulePlacement, placements_from_records, records_from_layout, validate_placements
from web.plotting import render_layout_svg
from web.ui_config import config_from_json, config_to_json, execute_analysis, synthetic_demo_config


class LayoutEditorTests(unittest.TestCase):
    def test_valid_mixed_layout_and_preview(self):
        config = synthetic_demo_config()
        placements = placements_from_records(records_from_layout(config["storey_layouts"][0]))
        self.assertEqual(validate_placements(2, 3, placements), [])
        svg = render_layout_svg(2, 3, placements)
        self.assertIn("<svg", svg)
        self.assertIn("Horizontal module", svg)
        self.assertIn("Vertical module", svg)

    def test_overlap_outside_and_incomplete_are_rejected(self):
        overlap = [ModulePlacement(1, "H", 0, 0), ModulePlacement(2, "V", 0, 1)]
        self.assertTrue(any("overlap" in error.lower() for error in validate_placements(2, 2, overlap)))
        outside = [ModulePlacement(1, "H", 0, 1)]
        self.assertTrue(any("outside" in error.lower() for error in validate_placements(1, 2, outside)))
        incomplete = [ModulePlacement(1, "H", 0, 0)]
        self.assertTrue(any("incomplete" in error.lower() for error in validate_placements(2, 2, incomplete)))


class UiConfigurationTests(unittest.TestCase):
    def test_json_round_trip(self):
        config = synthetic_demo_config()
        self.assertEqual(config_from_json(config_to_json(config)), config)

    def test_public_api_dispatch(self):
        fake = Mock()
        fake.solve_static.return_value.to_dict.return_value = {"static": True}
        fake.solve_modal.return_value.to_dict.return_value = {"modal": True}
        with patch("web.ui_config.ModuPort", return_value=fake) as constructor:
            result = execute_analysis(synthetic_demo_config(), "Both", ["TH_UX"], 2)
        constructor.assert_called_once()
        fake.solve_static.assert_called_once_with(["TH_UX"])
        fake.solve_modal.assert_called_once_with(num_modes=2)
        self.assertEqual(set(result), {"static", "modal"})

    def test_real_synthetic_static_and_modal(self):
        result = execute_analysis(synthetic_demo_config(), "Both", ["TH_UX", "TH_UY"], 3)
        self.assertIn("static", result)
        self.assertIn("modal", result)
        self.assertTrue(np.all(np.isfinite(result["modal"]["frequencies_hz"])))
        self.assertTrue(np.all(np.asarray(result["modal"]["frequencies_hz"]) > 0.0))
        json.dumps(result, allow_nan=False)


class StreamlitAppTests(unittest.TestCase):
    def test_app_renders_without_analysis(self):
        app_path = Path(__file__).resolve().parents[1] / "web" / "streamlit_app.py"
        app = AppTest.from_file(str(app_path), default_timeout=20).run()
        self.assertFalse(app.exception)
        self.assertTrue(any(button.label == "Run Analysis" for button in app.button))
        self.assertTrue(any("Synthetic software demonstration" in info.value for info in app.info))

    def test_single_model_summary_units_and_screenshot_mode(self):
        app_path = Path(__file__).resolve().parents[1] / "web" / "streamlit_app.py"
        app = AppTest.from_file(str(app_path), default_timeout=60).run()
        labels = {item.label for item in app.number_input}
        self.assertIn("Elastic modulus E (N/mm²)", labels)
        self.assertIn("Density (kg/m³)", labels)
        next(button for button in app.button if button.label == "Run Analysis").click().run()
        metric_labels = {metric.label for metric in app.metric}
        self.assertIn("First frequency (Hz)", metric_labels)
        self.assertIn("First period (s)", metric_labels)
        app.sidebar.toggle[0].set_value(True).run()
        self.assertFalse(app.exception)
        self.assertFalse(any("Synthetic software demonstration" in info.value for info in app.info))

    def test_about_page(self):
        app_path = Path(__file__).resolve().parents[1] / "web" / "streamlit_app.py"
        app = AppTest.from_file(str(app_path), default_timeout=30).run()
        app.sidebar.radio[0].set_value("About").run()
        self.assertFalse(app.exception)
        self.assertTrue(any("About ModuPort" in item.value for item in app.subheader))
        self.assertTrue(any(metric.label == "Version" and metric.value == "0.1.0" for metric in app.metric))


if __name__ == "__main__":
    unittest.main(verbosity=2)
