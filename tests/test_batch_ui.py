from __future__ import annotations

from copy import deepcopy
import csv
import io
import json
from pathlib import Path
import unittest

from streamlit.testing.v1 import AppTest

from web.batch_screening import (
    candidate_config,
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
from web.plotting import render_screening_layout_svg
from moduport import Footprint, enumerate_layouts, screen_layouts
from tests.synthetic_config import build_synthetic_config


OFFSET = {
    (0, 0), (0, 1),
    (1, 0), (1, 1), (1, 2), (1, 3),
    (2, 2), (2, 3),
}


class FootprintUiHelperTests(unittest.TestCase):
    def test_rectangular_and_irregular_editing_validation(self):
        rectangle = [(row, column) for row in range(2) for column in range(3)]
        self.assertEqual(validate_footprint_cells(2, 3, rectangle), [])
        self.assertEqual(validate_footprint_cells(3, 4, sorted(OFFSET)), [])
        self.assertTrue(any("even" in value for value in validate_footprint_cells(2, 2, [(0, 0), (0, 1), (1, 0)])))
        self.assertTrue(any("connected" in value for value in validate_footprint_cells(3, 2, [(0, 0), (0, 1), (2, 0), (2, 1)])))
        self.assertTrue(any("inside" in value for value in validate_footprint_cells(2, 2, [(0, 0), (0, 1), (1, 0), (2, 0)])))

    def test_enumeration_no_tiling_and_layout_browser_render(self):
        layouts = enumerate_layouts(Footprint.from_cells(OFFSET), id_prefix="I")
        self.assertEqual(len(layouts), 4)
        self.assertEqual([layout.layout_id for layout in layouts], ["I000001", "I000002", "I000003", "I000004"])
        no_tiling = Footprint.from_cells({(0, 0), (0, 1), (0, 2), (1, 1)})
        self.assertEqual(validate_footprint_cells(no_tiling.rows, no_tiling.columns, sorted(no_tiling.cells)), [])
        self.assertEqual(enumerate_layouts(no_tiling), [])
        svg = render_screening_layout_svg(layouts[1])
        self.assertIn("void", svg)
        self.assertIn("Horizontal module", svg)
        self.assertIn("Vertical module", svg)
        self.assertEqual(len(placements_from_layout(layouts[1])), 4)

    def test_reference_uses_public_normalization(self):
        layout = enumerate_layouts(Footprint.from_cells(OFFSET))[0]
        base = build_synthetic_config()
        base.pop("reference_point")
        reference = resolved_reference_point(base, layout)
        normalized = candidate_config(base, layout)
        self.assertEqual(list(reference), normalized["reference_point"])
        self.assertEqual(normalized["occupied_cells"], [list(cell) for cell in sorted(OFFSET)])

    def test_state_invalidation_and_structural_staleness(self):
        first = footprint_signature(2, 2, [(0, 0), (0, 1), (1, 0), (1, 1)])
        second = footprint_signature(3, 2, [(0, 0), (0, 1), (1, 0), (2, 0)])
        state = {}
        self.assertFalse(invalidate_footprint_state(state, first))
        state["batch_layouts"] = ["sentinel"]
        state["batch_screening_results"] = ["sentinel"]
        self.assertTrue(invalidate_footprint_state(state, second))
        self.assertNotIn("batch_layouts", state)
        self.assertNotIn("batch_screening_results", state)

        config = build_synthetic_config()
        signature = structural_signature(config, True)
        state["batch_screening_results"] = ["sentinel"]
        state["batch_screening_structural_signature"] = signature
        self.assertFalse(update_stale_state(state, signature))
        changed = deepcopy(config)
        changed["material"]["E_N_mm2"] += 1.0
        self.assertTrue(update_stale_state(state, structural_signature(changed, True)))


class BatchScreeningAndExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.layouts = enumerate_layouts(Footprint.from_cells(OFFSET), id_prefix="I")
        cls.serial = screen_layouts(build_synthetic_config(), cls.layouts, workers=1)
        cls.parallel = screen_layouts(build_synthetic_config(), cls.layouts, workers=2)

    def test_real_synthetic_serial_and_parallel_screening(self):
        self.assertTrue(all(record.success for record in self.serial))
        self.assertTrue(all(record.success for record in self.parallel))
        self.assertEqual([record.layout_id for record in self.serial], [record.layout_id for record in self.parallel])
        for left, right in zip(self.serial, self.parallel):
            self.assertLess(abs(left.kx_n_per_mm / right.kx_n_per_mm - 1.0), 1e-10)
            self.assertLess(abs(left.ky_n_per_mm / right.ky_n_per_mm - 1.0), 1e-10)

    def test_pareto_balanced_display_and_selected_render(self):
        rows, flags, balanced_id = result_display_rows(self.serial)
        self.assertEqual(len(rows), 4)
        self.assertEqual(len(flags), 4)
        self.assertIsNotNone(balanced_id)
        self.assertEqual(sum(row["Balanced"] for row in rows), 1)
        self.assertTrue(any(row["Pareto"] for row in rows))
        plot = design_space_rows(self.serial)
        self.assertEqual(len(plot), 4)
        self.assertIn("Balanced", {row["Category"] for row in plot})
        selected = next(record for record in self.serial if record.layout_id == balanced_id)
        self.assertIn("<svg", render_screening_layout_svg(selected.layout))

    def test_csv_and_json_exports(self):
        csv_payload = results_csv(self.serial)
        rows = list(csv.DictReader(io.StringIO(csv_payload)))
        self.assertEqual(len(rows), 4)
        self.assertIn("Pareto", rows[0])
        display, flags, balanced_id = result_display_rows(self.serial)
        record = self.serial[0]
        layout_payload = json.loads(selected_layout_json(record, pareto=flags[0], balanced=record.layout_id == balanced_id))
        self.assertEqual(layout_payload["layout"]["layout_id"], record.layout_id)
        base = build_synthetic_config()
        base.pop("reference_point")
        config_payload = json.loads(footprint_config_json(base, record.layout))
        self.assertEqual(config_payload["occupied_cells"], [list(cell) for cell in sorted(OFFSET)])
        self.assertIn("reference_point", config_payload)


class BatchStreamlitTests(unittest.TestCase):
    def test_batch_page_navigation_and_controls(self):
        app_path = Path(__file__).resolve().parents[1] / "web" / "streamlit_app.py"
        app = AppTest.from_file(str(app_path), default_timeout=30).run()
        app.sidebar.radio[0].set_value("Batch Screening").run()
        self.assertFalse(app.exception)
        labels = [button.label for button in app.button]
        self.assertIn("New 50 × 50 canvas", labels)
        self.assertIn("Generate Feasible Layouts", labels)
        self.assertIn("Run Screening", labels)
        self.assertEqual(app.number_input[0].value, 50)
        self.assertEqual(app.number_input[1].value, 50)
        self.assertTrue(any("Synthetic screening demonstration" in info.value for info in app.info))

    def test_batch_generate_and_screen_flow(self):
        app_path = Path(__file__).resolve().parents[1] / "web" / "streamlit_app.py"
        app = AppTest.from_file(str(app_path), default_timeout=60).run()
        app.sidebar.radio[0].set_value("Batch Screening").run()
        next(button for button in app.button if button.label == "Load synthetic footprint").click().run()
        next(button for button in app.button if button.label == "Generate Feasible Layouts").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any(selectbox.label == "Browse generated layout" for selectbox in app.selectbox))
        next(button for button in app.button if button.label == "Run Screening").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any(button.label == "Show balanced-stiffness layout" for button in app.button))
        self.assertTrue(any(selectbox.label == "Select evaluated layout ID" for selectbox in app.selectbox))
        self.assertEqual(len(app.get("download_button")), 4)
        self.assertTrue(any(button.label == "Export footprint JSON" for button in app.get("download_button")))

    def test_batch_screenshot_mode_keeps_results_and_hides_exports(self):
        app_path = Path(__file__).resolve().parents[1] / "web" / "streamlit_app.py"
        app = AppTest.from_file(str(app_path), default_timeout=60).run()
        app.sidebar.radio[0].set_value("Batch Screening").run()
        next(button for button in app.button if button.label == "Load synthetic footprint").click().run()
        app.sidebar.toggle[0].set_value(True).run()
        next(button for button in app.button if button.label == "Generate Feasible Layouts").click().run()
        next(button for button in app.button if button.label == "Run Screening").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any(metric.label == "Balanced-layout KX (N/mm)" for metric in app.metric))
        self.assertTrue(any(selectbox.label == "Select evaluated layout ID" for selectbox in app.selectbox))
        self.assertEqual(len(app.get("download_button")), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
