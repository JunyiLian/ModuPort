from dataclasses import dataclass
from typing import Any
import numpy as np

@dataclass
class StaticResult:
    storey_response: dict[str,list[dict[str,float]]]
    port_displacements: dict[str,np.ndarray]
    horizontal_link_forces: dict[str,dict[str,np.ndarray]]
    vertical_link_forces: dict[str,dict[str,np.ndarray]]
    reactions: dict[str,np.ndarray]
    strain_energy: dict[str,float]
    qa: dict[str,Any]

@dataclass
class ModalResult:
    eigenvalues: np.ndarray
    circular_frequencies: np.ndarray
    frequencies_hz: np.ndarray
    periods_s: np.ndarray
    mode_shapes_port: np.ndarray
    mode_shapes_macro: np.ndarray
    modal_types: list[str]
    mass_model: str
    qa: dict[str,Any]

@dataclass
class ValidationResult:
    passed: bool
    metrics: dict[str,float]
    qa: dict[str,Any]
