class ModuPortSolver:
    """Stable public facade over the validated RV30 project-side runtime."""
    def __init__(self,config,backend="explicit_reference"):
        self.config=config;self.backend_name=backend
        if backend=="explicit_reference":
            from .backends import ExplicitReferenceBackend
            self.backend=ExplicitReferenceBackend(config)
        elif backend=="finite_port":
            from .backends import FinitePortBackend
            self.backend=FinitePortBackend(config)
        elif backend=="finite_port_sparse":
            from .backends.finite_port_sparse_option_c import SparseFinitePortOptionCBackend
            self.backend=SparseFinitePortOptionCBackend(config)
        else:raise ValueError("backend must be 'explicit_reference' or 'finite_port'")
    def solve_static(self,load_cases=None):return self.backend.solve_static(load_cases or list(self.config.load_cases))
    def solve_modal(self,num_modes=3,mass_model="lumped"):return self.backend.solve_modal(num_modes,mass_model)
