from __future__ import annotations

import json
import unittest

import numpy as np

from moduport import ModuPort
from tests.synthetic_config import build_synthetic_config


def maximum_difference(left, right):
    absolute = np.max(np.abs(np.asarray(left, float) - np.asarray(right, float)))
    scale = np.maximum(np.maximum(np.abs(left), np.abs(right)), 1.0e-300)
    relative = np.max(np.abs(np.asarray(left, float) - np.asarray(right, float)) / scale)
    return float(absolute), float(relative)


class NumericalSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = ModuPort(build_synthetic_config())
        cls.public_static = cls.model.solve_static(["TH_UX", "TH_UY"])
        cls.public_modal = cls.model.solve_modal(3)
        frozen_solver = __import__("_moduport_frozen.solver", fromlist=["ModuPortSolver"]).ModuPortSolver(
            cls.model._config, "finite_port_sparse"
        )
        cls.direct_static = frozen_solver.solve_static(["TH_UX", "TH_UY"])
        cls.direct_modal = frozen_solver.solve_modal(3, "lumped")

    def test_static_numerical_sanity_and_direct_parity(self):
        for field in ("port_displacements", "reactions", "horizontal_link_forces", "vertical_link_forces"):
            value = getattr(self.public_static, field)
            self.assertTrue(value)
            for case in value.values():
                arrays = case.values() if isinstance(case, dict) else (case,)
                self.assertTrue(all(np.all(np.isfinite(array)) for array in arrays))
        for field in ("port_displacements", "reactions"):
            public = getattr(self.public_static, field)
            direct = getattr(self.direct_static, field)
            for case in public:
                self.assertTrue(np.array_equal(public[case], direct[case]))
        self.assertTrue(all(np.array_equal(self.public_static.horizontal_link_forces[c][k], self.direct_static.horizontal_link_forces[c][k]) for c in self.public_static.horizontal_link_forces for k in self.public_static.horizontal_link_forces[c]))
        self.assertTrue(all(np.array_equal(self.public_static.vertical_link_forces[c][k], self.direct_static.vertical_link_forces[c][k]) for c in self.public_static.vertical_link_forces for k in self.public_static.vertical_link_forces[c]))

    def test_modal_numerical_sanity_and_direct_parity(self):
        self.assertEqual(len(self.public_modal.eigenvalues), 3)
        for values in (self.public_modal.eigenvalues, self.public_modal.frequencies_hz, self.public_modal.periods_s):
            self.assertTrue(np.all(np.isfinite(values)))
            self.assertTrue(np.all(np.asarray(values) > 0.0))
        absolute, relative = maximum_difference(self.public_modal.frequencies_hz, self.direct_modal.frequencies_hz)
        self.assertLess(absolute, 1.0e-9)
        self.assertLess(relative, 1.0e-9)

    def test_serialization(self):
        json.dumps(self.public_static.to_dict(), allow_nan=False)
        json.dumps(self.public_modal.to_dict(), allow_nan=False)


if __name__ == "__main__":
    unittest.main()
