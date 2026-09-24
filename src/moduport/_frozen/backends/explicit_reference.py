from __future__ import annotations

class ExplicitReferenceBackend:
    """Named adapter for the frozen RV30 explicit-reference implementation."""
    name="explicit_reference"
    solver_backend="EXPLICIT_RV30_REFERENCE"
    def __init__(self,config):self.config=config
    def solve_static(self,load_cases=None):
        from ..static_solver import solve_static
        return solve_static(self.config,load_cases or list(self.config.load_cases))
    def solve_modal(self,num_modes=3,mass_model="lumped"):
        from ..modal_solver import solve_modal
        return solve_modal(self.config,num_modes,mass_model)
