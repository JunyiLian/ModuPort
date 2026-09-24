from __future__ import annotations

import subprocess
from pathlib import Path
import unittest

from web.batch_screening import footprint_signature, invalidate_footprint_state
from web.footprint_sketcher import footprint_data_json, parse_footprint_data
from moduport import Footprint, enumerate_layouts, screen_layouts
from tests.synthetic_config import build_synthetic_config


IRREGULAR = {
    (0, 0), (0, 1),
    (1, 0), (1, 1), (1, 2), (1, 3),
    (2, 2), (2, 3),
}


class FootprintSketcherTests(unittest.TestCase):
    def test_browser_side_operations(self):
        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            ["node", str(root / "tests" / "footprint_sketcher_core.test.js")],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("PASS", completed.stdout)

    def test_export_clear_import_exact_recovery(self):
        payload = footprint_data_json(3, 4, sorted(IRREGULAR))
        rows, columns, recovered = parse_footprint_data(payload)
        self.assertEqual((rows, columns), (3, 4))
        self.assertEqual(set(recovered), IRREGULAR)

    def test_invalid_import_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unique in-bounds"):
            parse_footprint_data('{"grid_rows":2,"grid_cols":2,"occupied_cells":[[0,0],[0,0]]}')
        with self.assertRaisesRegex(ValueError, "positive integers"):
            parse_footprint_data('{"grid_rows":0,"grid_cols":2,"occupied_cells":[]}')

    def test_change_invalidates_generated_and_screened_state_without_regeneration(self):
        first = footprint_signature(2, 2, [(0, 0), (0, 1), (1, 0), (1, 1)])
        second = footprint_signature(3, 4, sorted(IRREGULAR))
        state = {}
        self.assertFalse(invalidate_footprint_state(state, first))
        state["batch_layouts"] = ["generated"]
        state["batch_screening_results"] = ["screened"]
        self.assertTrue(invalidate_footprint_state(state, second))
        self.assertNotIn("batch_layouts", state)
        self.assertNotIn("batch_screening_results", state)

    def test_drawn_irregular_domain_enumerates_and_screens(self):
        layouts = enumerate_layouts(Footprint.from_cells(IRREGULAR), id_prefix="D")
        self.assertEqual(len(layouts), 4)
        results = screen_layouts(build_synthetic_config(), layouts, workers=1)
        self.assertEqual(len(results), 4)
        self.assertTrue(all(record.success for record in results))
        self.assertTrue(all(record.kx_n_per_mm > 0 and record.ky_n_per_mm > 0 for record in results))


if __name__ == "__main__":
    unittest.main(verbosity=2)
