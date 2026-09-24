"""Three-storey static and modal analyses using one authoritative solver path."""

from __future__ import annotations

from moduport import ModuPort

try:
    from .model_data import synthetic_config
except ImportError:  # Direct execution: python examples/multistorey_static_modal.py
    from model_data import synthetic_config


def run() -> tuple[dict, dict]:
    model = ModuPort(synthetic_config(storeys=3))
    static = model.solve_static(["TH_UX", "TH_UY"]).to_dict()
    modal = model.solve_modal(num_modes=3).to_dict()

    roof_x = static["storey_response"]["TH_UX"][-1]
    vertical_id, vertical_force = next(iter(static["vertical_link_forces"]["TH_UX"].items()))
    print(f"roof UX under TH_UX = {roof_x['ux_bar']:.9g} mm")
    print(f"representative vertical connection {vertical_id}: {vertical_force}")
    for index, (frequency, period, mode_type) in enumerate(
        zip(modal["frequencies_hz"], modal["periods_s"], modal["modal_types"]),
        start=1,
    ):
        print(f"mode {index}: {frequency:.6g} Hz, {period:.6g} s, {mode_type}")
    return static, modal


if __name__ == "__main__":
    run()
