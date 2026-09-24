from __future__ import annotations

import math
import unittest

from examples.multistorey_static_modal import run as run_multistorey
from examples.single_storey_static import run as run_single_storey


class PublicExampleTests(unittest.TestCase):
    def test_single_storey_static_example(self):
        result = run_single_storey()
        self.assertTrue(math.isfinite(result["storey_response"]["TH_UX"][-1]["ux_bar"]))
        self.assertTrue(result["horizontal_link_forces"]["TH_UX"])
        self.assertFalse(result["vertical_link_forces"]["TH_UX"])

    def test_multistorey_static_modal_example(self):
        static, modal = run_multistorey()
        self.assertEqual(len(static["storey_response"]["TH_UX"]), 3)
        self.assertTrue(static["vertical_link_forces"]["TH_UX"])
        self.assertEqual(len(modal["frequencies_hz"]), 3)
        self.assertTrue(all(value > 0.0 for value in modal["frequencies_hz"]))


if __name__ == "__main__":
    unittest.main()
