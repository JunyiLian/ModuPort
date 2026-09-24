from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import numpy as np

from moduport import ModuPort, UnsupportedConfigurationError
from tests.synthetic_config import build_synthetic_config


class PublicApiTests(unittest.TestCase):
    def test_mapping_and_json_constructors(self):
        model = ModuPort(build_synthetic_config())
        self.assertEqual(model._solver.backend.__class__.__name__, "SparseFinitePortOptionCBackend")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.json"
            path.write_text(json.dumps(build_synthetic_config()), encoding="utf-8")
            self.assertEqual(ModuPort.from_json(path)._config.mass_model, "lumped")

    def test_validated_domain_guard(self):
        config = copy.deepcopy(build_synthetic_config())
        config["mass_model"] = "consistent"
        with self.assertRaises(UnsupportedConfigurationError):
            ModuPort(config)
        config = copy.deepcopy(build_synthetic_config())
        config["boundary"]["mode"] = "OTHER"
        with self.assertRaises(UnsupportedConfigurationError):
            ModuPort(config)

    def test_dispatch_and_serialization(self):
        model = ModuPort(build_synthetic_config())
        result_module = __import__("_moduport_frozen.result", fromlist=["StaticResult", "ModalResult"])
        raw_static = result_module.StaticResult(
            {"TH_UX": [{"ux_bar": 1.0}]},
            {"TH_UX": np.array([1.0])},
            {"TH_UX": {"H": np.array([2.0])}},
            {"TH_UX": {"V": np.array([3.0])}},
            {"TH_UX": np.array([4.0])},
            {"TH_UX": np.float64(5.0)},
            {"passed": np.bool_(True)},
        )
        raw_modal = result_module.ModalResult(
            np.array([1.0]), np.array([1.0]), np.array([0.15915494309189535]), np.array([6.283185307179586]),
            np.array([[1.0]]), np.array([[1.0]]), ["X"], "lumped", {"passed": np.bool_(True)},
        )
        model._solver.backend.solve_static = Mock(return_value=raw_static)
        model._solver.backend.solve_modal = Mock(return_value=raw_modal)
        static = model.solve_static(["TH_UX"])
        modal = model.solve_modal(1)
        model._solver.backend.solve_static.assert_called_once_with(["TH_UX"])
        model._solver.backend.solve_modal.assert_called_once_with(1, "lumped")
        self.assertEqual(static.to_dict()["reactions"]["TH_UX"], [4.0])
        self.assertEqual(modal.to_dict()["mass_model"], "lumped")


if __name__ == "__main__":
    unittest.main()
