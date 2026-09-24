from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np

from moduport import ConfigurationError, Footprint, ModuPort, UnsupportedConfigurationError, enumerate_layouts
from tests.synthetic_config import build_synthetic_config


STEPPED = {(0, 0), (0, 1), (0, 2), (0, 3), (1, 0), (1, 1), (2, 0), (2, 1)}
L_SHAPE = {(0, 0), (0, 1), (1, 0), (2, 0)}
RING = {(row, column) for row in range(4) for column in range(4) if not (1 <= row <= 2 and 1 <= column <= 2)}
OFFSET = {(0, 0), (0, 1), (1, 0), (1, 1), (1, 2), (1, 3), (2, 2), (2, 3)}


def irregular_config(cells, layout_index=0, *, include_reference=True):
    footprint = Footprint.from_cells(cells)
    layouts = enumerate_layouts(footprint, id_prefix="T")
    config = deepcopy(build_synthetic_config())
    config["grid_rows"] = footprint.rows
    config["grid_cols"] = footprint.columns
    config["occupied_cells"] = [list(cell) for cell in sorted(footprint.cells)]
    config["storey_layouts"] = [layouts[layout_index].expression] * config["storey_count"]
    if not include_reference:
        config.pop("reference_point", None)
    return config, layouts


class IrregularPublicApiTests(unittest.TestCase):
    def test_rectangle_without_occupied_cells_remains_unchanged(self):
        config = build_synthetic_config()
        model = ModuPort(config)
        self.assertNotIn("occupied_cells", model.to_config_dict())
        self.assertEqual(model.to_config_dict(), config)
        result = model.solve_static(["TH_UX", "TH_UY"])
        self.assertTrue(result.qa["passed"])

    def test_supported_irregular_static_and_modal(self):
        for name, cells in (("stepped", STEPPED), ("L", L_SHAPE), ("internal_void", RING), ("multiple_tilings", OFFSET)):
            with self.subTest(name=name):
                config, layouts = irregular_config(cells, include_reference=False)
                self.assertGreaterEqual(len(layouts), 1)
                model = ModuPort(config)
                static = model.solve_static(["TH_UX", "TH_UY"])
                modal = model.solve_modal(3)
                self.assertTrue(static.qa["passed"])
                self.assertTrue(modal.qa["passed"])
                self.assertTrue(np.all(np.asarray(modal.eigenvalues) > 0.0))
                self.assertTrue(np.all(np.isfinite(modal.frequencies_hz)))
                self.assertTrue(np.all(np.isfinite(modal.periods_s)))

    def test_occupied_centroid_default_and_explicit_reference(self):
        config, _ = irregular_config(STEPPED, include_reference=False)
        model = ModuPort(config)
        pitch = config["module_geometry"]["short_outer_mm"] + config["module_geometry"]["clear_gap_mm"]
        expected = [
            sum((column + 0.5) * pitch for row, column in STEPPED) / len(STEPPED),
            sum((row + 0.5) * pitch for row, column in STEPPED) / len(STEPPED),
        ]
        rectangle_center = [config["grid_cols"] * pitch / 2.0, config["grid_rows"] * pitch / 2.0]
        self.assertEqual(model.to_config_dict()["reference_point"], expected)
        self.assertNotEqual(expected, rectangle_center)

        explicit = deepcopy(config)
        explicit["reference_point"] = [1234.0, 5678.0]
        self.assertEqual(ModuPort(explicit).to_config_dict()["reference_point"], [1234.0, 5678.0])

    def test_json_roundtrip_preserves_footprint_and_computed_reference(self):
        config, _ = irregular_config(L_SHAPE, include_reference=False)
        model = ModuPort(config)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "irregular.json"
            payload = model.to_json(path)
            decoded = json.loads(payload)
            self.assertEqual(decoded["occupied_cells"], model.to_config_dict()["occupied_cells"])
            loaded = ModuPort.from_json(path)
            self.assertEqual(loaded.to_config_dict()["occupied_cells"], decoded["occupied_cells"])
            self.assertEqual(loaded.to_config_dict()["reference_point"], decoded["reference_point"])

    def test_rejected_footprint_and_layout_cases(self):
        valid, _ = irregular_config(L_SHAPE, include_reference=False)
        rejected = []

        disconnected = deepcopy(valid)
        disconnected["grid_rows"] = 3
        disconnected["grid_cols"] = 2
        disconnected["occupied_cells"] = [[0, 0], [0, 1], [2, 0], [2, 1]]
        disconnected["storey_layouts"] = ["H(0,0)|H(2,0)"] * 2
        rejected.append(("disconnected", disconnected, UnsupportedConfigurationError))

        odd = deepcopy(valid)
        odd["occupied_cells"] = [[0, 0], [0, 1], [1, 0]]
        odd["storey_layouts"] = ["H(0,0)"] * 2
        rejected.append(("odd", odd, UnsupportedConfigurationError))

        overlap = deepcopy(valid)
        overlap["grid_rows"] = 2
        overlap["grid_cols"] = 2
        overlap["occupied_cells"] = [[0, 0], [0, 1], [1, 0], [1, 1]]
        overlap["storey_layouts"] = ["H(0,0)|V(0,0)"] * 2
        rejected.append(("overlap", overlap, UnsupportedConfigurationError))

        incomplete = deepcopy(overlap)
        incomplete["storey_layouts"] = ["H(0,0)"] * 2
        rejected.append(("incomplete", incomplete, UnsupportedConfigurationError))

        on_void = deepcopy(valid)
        on_void["storey_layouts"] = ["H(0,0)|V(1,1)"] * 2
        rejected.append(("module_on_void", on_void, UnsupportedConfigurationError))

        non_domino = deepcopy(valid)
        non_domino["storey_layouts"] = ["X(0,0)|V(1,0)"] * 2
        rejected.append(("non_domino", non_domino, UnsupportedConfigurationError))

        duplicate_cell = deepcopy(valid)
        duplicate_cell["occupied_cells"] = valid["occupied_cells"] + [valid["occupied_cells"][0]]
        rejected.append(("duplicate_cell", duplicate_cell, ConfigurationError))

        outside = deepcopy(valid)
        outside["occupied_cells"] = [[0, 0], [0, 1], [1, 0], [3, 0]]
        rejected.append(("outside", outside, UnsupportedConfigurationError))

        different_storeys = deepcopy(valid)
        alternate = enumerate_layouts(Footprint.rectangle(2, 2))
        different_storeys["grid_rows"] = 2
        different_storeys["grid_cols"] = 2
        different_storeys["occupied_cells"] = [[0, 0], [0, 1], [1, 0], [1, 1]]
        different_storeys["storey_layouts"] = [alternate[0].expression, alternate[1].expression]
        rejected.append(("different_storeys", different_storeys, UnsupportedConfigurationError))

        for name, config, error_type in rejected:
            with self.subTest(name=name):
                with self.assertRaises(error_type):
                    ModuPort(config)

    def test_invalid_explicit_reference_is_not_silently_replaced(self):
        config, _ = irregular_config(L_SHAPE, include_reference=False)
        config["reference_point"] = [math.nan, 0.0]
        with self.assertRaises(ConfigurationError):
            ModuPort(config)


if __name__ == "__main__":
    unittest.main(verbosity=2)
