# Public Python API

`ModuPort` is the supported public facade. It delegates every solve to the frozen `ModuPortSolver` using `SparseFinitePortOptionCBackend`; the release layer contains no second implementation of the structural mechanics.

## Construction

```python
from moduport import ModuPort

model = ModuPort(config)
model = ModuPort.from_json(path_or_json_text)
```

The configuration groups describe geometry and storeys, member sections and material properties, occupied logical cells, the horizontal/vertical layout tokens, connections, boundary conditions, loads, and modal settings. Layout tokens follow the validated convention: `H(i,j)` covers adjacent cells horizontally and `V(i,j)` covers adjacent cells vertically.

`to_config_dict()` and `to_json()` return portable representations of the accepted configuration.

## Static analysis

```python
result = model.solve_static()
```

The static result preserves the solver response groups, including global displacements, reactions, strain energy, and recovered connection/member responses when requested by the configuration.

## Modal analysis

```python
result = model.solve_modal(num_modes=6)
```

The modal result exposes eigenvalues, frequencies, periods, mode shapes, and available directional participation information. Mode interpretation should use participation rather than eigenvalue order alone.

## Stability boundary

Files under `src/moduport/_frozen/` and `src/moduport/_vendor/` are byte-for-byte frozen against the authoritative 26-file A1 source manifest. Public wrappers may validate, serialize, and present inputs or outputs, but they must not change condensation, connection kinematics, assembly, supports, static/modal formulation, or response recovery.
