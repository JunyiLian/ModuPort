# ModuPort

ModuPort is a mechanics-based superelement solver for linear static and modal analysis of multi-storey framed modular structures. It exposes the validated Option-C computational backend through a small Python API and an interactive Streamlit interface.

> **Publication status:** this repository is a local public-release candidate. Public distribution is blocked until the ownership and redistribution terms of the bundled RV30 adapter and private `mscsolver` sources are confirmed. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [LICENSE](LICENSE).

Interface documentation: **English** · [简体中文](docs/README_zh-CN.md) · [Français](docs/README_fr.md) · [Español](docs/README_es.md) · [Русский](docs/README_ru.md) · [العربية](docs/README_ar.md).

## Capabilities

- Linear-elastic static and modal analysis
- Finite-port modular-unit superelements with exact static condensation
- Validated horizontal and vertical connection formulations
- Rectangular and supported irregular occupied-cell footprints
- Exact enumeration of horizontal 1×2 and vertical 2×1 domino layouts
- Batch directional-stiffness screening and Pareto inspection
- Mouse-driven footprint sketcher up to 50×50 logical cells
- Six interface languages, including right-to-left Arabic

“Arbitrary layouts” means exact horizontal/vertical domino coverings within the supported connected occupied-cell domain. It does not imply arbitrary module shapes, disconnected domains, storey-varying layouts, or unrestricted geometry.

## Installation

The current baseline is Python 3.10 or later with NumPy and SciPy.

```bash
python -m pip install -e .
```

Install optional screening or interface dependencies when required:

```bash
python -m pip install -e ".[screening]"
python -m pip install -e ".[ui]"
```

## Minimal Python API

```python
from moduport import ModuPort
from examples.model_data import synthetic_config

model = ModuPort(synthetic_config(storeys=1))
static = model.solve_static()
modal = model.solve_modal(num_modes=3)

print(static.responses)
print(modal.frequencies_hz)
```

The public facade delegates directly to `SparseFinitePortOptionCBackend`; it does not duplicate or replace the frozen mechanics. See [docs/PUBLIC_API.md](docs/PUBLIC_API.md) for the input and result groups.

## Examples

The examples use small synthetic configurations and contain no validation or manuscript data.

```bash
python examples/single_storey_static.py
python examples/multistorey_static_modal.py
```

See [examples/README.md](examples/README.md).

## Interactive web interface

```bash
python -m streamlit run web/streamlit_app.py
```

The normal Batch Screening workflow starts with the footprint sketcher, reports occupied-cell count, connectivity, and parity, and then guides the user to feasible-layout generation. Raw `occupied_cells` data remain in the advanced section. Language switching preserves the working session and Arabic uses right-to-left layout.

## Supported domain and limitations

- The solver currently addresses the validated linear static and modal formulations only.
- Footprints must satisfy the topology and exact-cover requirements checked by the public input layer.
- The first release retains the frozen A30 implementation byte-for-byte. Historical absolute-path strings remain inside two frozen source files, but portable bootstrap resolution prevents runtime dependence on those locations.
- RV30 and `mscsolver` ownership/licensing must be resolved before public distribution.
- No SAP2000 automation, research datasets, A30/A32 cases, benchmark outputs, figures, or manuscript results are included.

## Repository structure

```text
src/moduport/              public facade and release bootstrap
src/moduport/_frozen/      byte-for-byte validated ModuPort core
src/moduport/_vendor/      frozen RV30 and mscsolver dependencies
web/                       Streamlit interface and localization
examples/                  synthetic API examples
tests/                     SAP-free regression and interface tests
docs/                      API and translated interface notes
```

## Verification

```bash
python -m unittest discover -s tests -p "test_*.py"
node tests/footprint_sketcher_core.test.js
```

Release verification also compares all 26 frozen Python sources against the authoritative A1 SHA-256 manifest.
The sanitized repository-relative digest list is stored in [provenance/FROZEN_SOURCE_SHA256.txt](provenance/FROZEN_SOURCE_SHA256.txt).

## Citation and contribution

Citation metadata are provided in [CITATION.cff](CITATION.cff). Contributions must follow the frozen-core rules in [CONTRIBUTING.md](CONTRIBUTING.md): validated mechanics are not edited directly; wrappers, tests, and documentation belong outside the frozen directories.

## License status

No public open-source license is granted by this release candidate. See [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Replace the review notice with an approved license only after every bundled dependency has been cleared for redistribution.
