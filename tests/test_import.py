from __future__ import annotations

import unittest

import moduport
from moduport import ModalResult, ModuPort, ModuPortError, StaticResult, UnsupportedConfigurationError


class ImportTests(unittest.TestCase):
    def test_public_surface(self):
        self.assertIs(moduport.ModuPort, ModuPort)
        legacy = {"ModuPort", "StaticResult", "ModalResult", "ModuPortError", "ConfigurationError", "UnsupportedConfigurationError"}
        screening = {
            "Footprint", "Domino", "Layout", "enumerate_layouts", "iter_layouts",
            "ScreeningRecord", "ScreeningResults", "BatchProgress", "screen_layouts",
            "pareto_flags", "normalized_scores", "select_balanced_layout",
        }
        self.assertEqual(set(moduport.__all__), legacy | screening)
        self.assertTrue(all(item is not None for item in (StaticResult, ModalResult, ModuPortError, UnsupportedConfigurationError)))
        self.assertFalse(hasattr(moduport, "SparseFinitePortOptionCBackend"))


if __name__ == "__main__":
    unittest.main()
