"""Single-storey mixed-layout static analysis using the public API."""

from __future__ import annotations

from moduport import ModuPort

try:
    from .model_data import synthetic_config
except ImportError:  # Direct execution: python examples/single_storey_static.py
    from model_data import synthetic_config


def run() -> dict:
    model = ModuPort(synthetic_config(storeys=1))
    result = model.solve_static(["TH_UX"]).to_dict()

    roof = result["storey_response"]["TH_UX"][-1]
    horizontal_id, horizontal_force = next(iter(result["horizontal_link_forces"]["TH_UX"].items()))

    print(f"roof UX = {roof['ux_bar']:.9g} mm")
    print(f"strain energy = {result['strain_energy']['TH_UX']:.9g} N·mm")
    print(f"horizontal connection {horizontal_id}: {horizontal_force}")
    print("vertical connections: none in a single-storey model")
    return result


if __name__ == "__main__":
    run()
