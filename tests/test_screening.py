from __future__ import annotations

from copy import deepcopy
import math
import unittest

from moduport import (
    Footprint,
    enumerate_layouts,
    normalized_scores,
    pareto_flags,
    screen_layouts,
    select_balanced_layout,
)

from tests.synthetic_config import build_synthetic_config


class EnumerationTests(unittest.TestCase):
    def test_known_rectangle_counts(self):
        self.assertEqual(len(enumerate_layouts(Footprint.rectangle(2, 2))), 2)
        self.assertEqual(len(enumerate_layouts(Footprint.rectangle(2, 3))), 3)

    def test_irregular_and_void_footprints(self):
        irregular = Footprint.from_cells({(0, 0), (0, 1), (1, 0), (2, 0)})
        layouts = enumerate_layouts(irregular)
        self.assertEqual(len(layouts), 1)
        self.assertFalse(irregular.is_full_rectangle)
        self.assertEqual(set(cell for domino in layouts[0].dominoes for cell in domino.cells), set(irregular.cells))
        masked = Footprint.from_mask([[1, 1, 0], [1, 1, 1], [0, 1, 1]])
        self.assertEqual(masked.occupied_cell_count, 7)
        self.assertEqual(enumerate_layouts(masked), [])

    def test_unique_exact_and_deterministic(self):
        domain = Footprint.rectangle(2, 3)
        first = enumerate_layouts(domain)
        second = enumerate_layouts(domain)
        self.assertEqual([layout.signature for layout in first], [layout.signature for layout in second])
        self.assertEqual(len({layout.signature for layout in first}), len(first))
        for layout in first:
            cells = [cell for domino in layout.dominoes for cell in domino.cells]
            self.assertEqual(len(cells), len(set(cells)))
            self.assertEqual(set(cells), set(domain.cells))


class PostProcessingTests(unittest.TestCase):
    def test_exact_pareto_ties_and_final_raw_balance(self):
        records = [
            {"layout_id": "L1", "KX_N_per_mm": 10.0, "KY_N_per_mm": 8.0, "status": "success"},
            {"layout_id": "L2", "KX_N_per_mm": 9.0, "KY_N_per_mm": 9.0, "status": "success"},
            {"layout_id": "L3", "KX_N_per_mm": 8.0, "KY_N_per_mm": 10.0, "status": "success"},
            {"layout_id": "L4", "KX_N_per_mm": 9.0, "KY_N_per_mm": 7.0, "status": "success"},
            {"layout_id": "L5", "KX_N_per_mm": 9.0, "KY_N_per_mm": 9.0, "status": "success"},
        ]
        self.assertEqual(pareto_flags(records), (True, True, True, False, True))
        self.assertEqual(select_balanced_layout(records)["layout_id"], "L2")
        scores = normalized_scores(records)
        self.assertEqual(len(scores), 5)
        self.assertTrue(all(0.0 < row["SX"] <= 1.0 and 0.0 < row["SY"] <= 1.0 for row in scores))


class EndToEndScreeningTests(unittest.TestCase):
    def test_serial_parallel_public_api_screening(self):
        config = build_synthetic_config()
        original = deepcopy(config)
        layouts = enumerate_layouts(Footprint.rectangle(2, 3), id_prefix="S")
        progress = []
        serial = screen_layouts(config, layouts, workers=1, progress=progress.append)
        parallel = screen_layouts(config, layouts, workers=2)
        self.assertEqual(config, original)
        self.assertEqual([row.layout_id for row in serial], [row.layout_id for row in parallel])
        self.assertEqual(progress[-1].completed, len(layouts))
        self.assertEqual(progress[-1].failed, 0)
        for left, right in zip(serial, parallel):
            self.assertTrue(left.success and right.success)
            self.assertGreater(left.kx_n_per_mm, 0.0)
            self.assertGreater(left.ky_n_per_mm, 0.0)
            self.assertTrue(math.isclose(left.kx_n_per_mm, right.kx_n_per_mm, rel_tol=1e-12, abs_tol=1e-9), (left.layout_id, left.kx_n_per_mm, right.kx_n_per_mm))
            self.assertTrue(math.isclose(left.ky_n_per_mm, right.ky_n_per_mm, rel_tol=1e-12, abs_tol=1e-9), (left.layout_id, left.ky_n_per_mm, right.ky_n_per_mm))
        self.assertEqual(len(serial.to_dicts()), len(layouts))

    def test_irregular_solver_domain_succeeds(self):
        config = build_synthetic_config()
        irregular = Footprint.from_cells({(0, 0), (0, 1), (1, 0), (2, 0)})
        result = screen_layouts(config, enumerate_layouts(irregular), workers=1)
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].success)
        self.assertGreater(result[0].kx_n_per_mm, 0.0)
        self.assertGreater(result[0].ky_n_per_mm, 0.0)

    def test_irregular_exhaustive_serial_parallel_pareto_and_balance(self):
        config = build_synthetic_config()
        footprint = Footprint.from_cells({
            (0, 0), (0, 1),
            (1, 0), (1, 1), (1, 2), (1, 3),
            (2, 2), (2, 3),
        })
        first = enumerate_layouts(footprint, id_prefix="I")
        second = enumerate_layouts(footprint, id_prefix="I")
        self.assertEqual(len(first), 4)
        self.assertEqual([layout.layout_id for layout in first], [layout.layout_id for layout in second])
        self.assertEqual([layout.signature for layout in first], [layout.signature for layout in second])
        serial = screen_layouts(config, first, workers=1)
        parallel = screen_layouts(config, first, workers=2)
        self.assertTrue(all(record.success for record in serial))
        self.assertEqual([record.layout_id for record in serial], [record.layout_id for record in parallel])
        for left, right in zip(serial, parallel):
            self.assertTrue(right.success)
            self.assertTrue(math.isclose(left.kx_n_per_mm, right.kx_n_per_mm, rel_tol=1e-10, abs_tol=1e-4), (left.layout_id, left.kx_n_per_mm, right.kx_n_per_mm))
            self.assertTrue(math.isclose(left.ky_n_per_mm, right.ky_n_per_mm, rel_tol=1e-10, abs_tol=1e-4), (left.layout_id, left.ky_n_per_mm, right.ky_n_per_mm))
        flags = pareto_flags(serial)
        self.assertEqual(len(flags), len(first))
        self.assertTrue(any(flags))
        balanced = select_balanced_layout(serial)
        self.assertIn(balanced.layout_id, [layout.layout_id for layout in first])


if __name__ == "__main__":
    unittest.main(verbosity=2)
