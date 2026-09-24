from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np

from ._module_layout import ModelConfig, Placement, beam3d_global_stiffness
from ._finite_port import (
    ModuleSpec,
    assemble_single_storey_port_model,
    build_module_port_stiffness,
    condense_storey_to_3x3,
)

TRANSFORMS = {
    "mirror_x": np.diag([-1.0, 1.0, -1.0]),
    "mirror_y": np.diag([1.0, -1.0, -1.0]),
    "rotate_180": np.diag([-1.0, -1.0, 1.0]),
}
REL_TOL = 2.0e-9
CENTER_TOL_MM = 1.0e-4
RHO_TOL = 1.0e-8


def parse_layout(code: str) -> list[Placement]:
    pieces = []
    for token in code.split("|"):
        orientation = token[0]
        row, col = (int(x.strip()) for x in token[token.index("(") + 1 : token.index(")")].split(","))
        cells = ((row, col), (row, col + 1)) if orientation == "H" else ((row, col), (row + 1, col))
        pieces.append((orientation, cells))
    return [Placement(i + 1, orientation, cells) for i, (orientation, cells) in enumerate(pieces)]


def transform_layout(layout: list[Placement], rows: int, cols: int, name: str) -> list[Placement]:
    def transform_cell(cell):
        r, c = cell
        if name == "mirror_x":
            return r, cols - 1 - c
        if name == "mirror_y":
            return rows - 1 - r, c
        return rows - 1 - r, cols - 1 - c

    rebuilt = []
    for p in layout:
        cells = tuple(sorted(transform_cell(cell) for cell in p.cells))
        orientation = "H" if cells[0][0] == cells[1][0] else "V"
        rebuilt.append((min(cells), orientation, cells))
    rebuilt.sort()
    return [Placement(i + 1, orientation, cells) for i, (_, orientation, cells) in enumerate(rebuilt)]


def validate_layout(layout: list[Placement], rows: int, cols: int) -> tuple[bool, str]:
    occupied = []
    for p in layout:
        cells = tuple(p.cells)
        if len(cells) != 2:
            return False, "module does not contain two cells"
        if any(not (0 <= r < rows and 0 <= c < cols) for r, c in cells):
            return False, "cell outside grid"
        dr = abs(cells[0][0] - cells[1][0]); dc = abs(cells[0][1] - cells[1][1])
        expected = "H" if dr == 0 and dc == 1 else "V" if dr == 1 and dc == 0 else None
        if expected != p.orientation:
            return False, "orientation or adjacency mismatch"
        occupied.extend(cells)
    if len(occupied) != rows * cols or len(set(occupied)) != rows * cols:
        return False, "grid is not covered exactly once"
    return True, ""


def topology(layout: list[Placement], rows: int, cols: int) -> dict[str, int]:
    grid = {cell: p for p in layout for cell in p.cells}
    counts = {"N": len(layout), "nH": sum(p.orientation == "H" for p in layout), "nV": sum(p.orientation == "V" for p in layout), "HH": 0, "VV": 0, "HV": 0, "interfaces": 0}
    for r in range(rows):
        for c in range(cols):
            for other in ((r + 1, c), (r, c + 1)):
                if other in grid and grid[(r, c)] is not grid[other]:
                    counts["interfaces"] += 1
                    pair = "".join(sorted((grid[(r, c)].orientation, grid[other].orientation)))
                    counts["HH" if pair == "HH" else "VV" if pair == "VV" else "HV"] += 1
    return counts


def module_k(orientation: str, cfg: ModelConfig) -> np.ndarray:
    width = cfg.module_long_outer if orientation == "H" else cfg.module_short_outer
    height = cfg.module_short_outer if orientation == "H" else cfg.module_long_outer
    spec = ModuleSpec(1, orientation, 0.0, 0.0, width, height)
    core = build_module_port_stiffness(orientation, config=cfg, spec=spec, extras={})
    K = core.stiffness
    R = np.zeros((len(K), 3)); lower = []; upper = []
    xc, yc = (spec.x0 + spec.x1) / 2, (spec.y0 + spec.y1) / 2
    for xs in ("W", "E"):
        for ys in ("S", "N"):
            lower += [core.port[("BOT", "C", xs, ys, d)] for d in range(3)]
            x, y, _ = core.coords[("TOP", "C", xs, ys)]
            for d, values in ((0, (1, 0, -(y - yc))), (1, (0, 1, x - xc)), (2, (0, 0, 1))):
                upper.append(core.port[("TOP", "C", xs, ys, d)])
                R[core.port[("TOP", "C", xs, ys, d)]] = values
    free = np.array([i for i in range(len(K)) if i not in set(lower) | set(upper)], int)
    coupling = R.T @ K[:, free]
    return R.T @ K @ R - coupling @ np.linalg.solve(K[np.ix_(free, free)], coupling.T)


def projection(layout: list[Placement], rows: int, cols: int, cfg: ModelConfig, kh: np.ndarray, kv: np.ndarray) -> np.ndarray:
    x0, y0 = cols * cfg.cell_pitch / 2, rows * cfg.cell_pitch / 2
    result = np.zeros((3, 3))
    for p in layout:
        rs = [cell[0] for cell in p.cells]; cs = [cell[1] for cell in p.cells]
        x = (min(cs) + (1.0 if p.orientation == "H" else 0.5)) * cfg.cell_pitch
        y = (min(rs) + (0.5 if p.orientation == "H" else 1.0)) * cfg.cell_pitch
        T = np.array(((1, 0, -(y - y0)), (0, 1, x - x0), (0, 0, 1.0)))
        result += T.T @ (kh if p.orientation == "H" else kv) @ T
    return result


def normalized_error(actual: np.ndarray, expected: np.ndarray) -> float:
    return float(np.linalg.norm(actual - expected) / max(np.linalg.norm(expected), 1.0))


def rho(K: np.ndarray) -> np.ndarray:
    return np.array((K[0, 2] / math.sqrt(K[0, 0] * K[2, 2]), K[1, 2] / math.sqrt(K[1, 1] * K[2, 2])))


def stiffness_center(K: np.ndarray, reference: np.ndarray) -> np.ndarray:
    dy, minus_dx = -np.linalg.solve(K[:2, :2], K[:2, 2])
    return reference + np.array((-minus_dx, dy))


def main() -> int:
    qa_dir = OUT / "qa"; qa_dir.mkdir(parents=True, exist_ok=True)
    database = list(csv.DictReader((OUT / "processed_results" / "A15_cross_grid_stiffness_database.csv").open(encoding="utf-8-sig")))
    if len(database) != 63:
        raise RuntimeError(f"expected 63 original layouts, found {len(database)}")
    cfg = ModelConfig(); cfg._beam_function = beam3d_global_stiffness
    kh = 0.5 * (module_k("H", cfg) + module_k("H", cfg).T)
    kv = 0.5 * (module_k("V", cfg) + module_k("V", cfg).T)
    results = []
    max_k_error = max_projection_error = 0.0
    for source in database:
        rows, cols = int(source["grid_rows"]), int(source["grid_cols"])
        reference = np.array((cols * cfg.cell_pitch / 2, rows * cfg.cell_pitch / 2))
        original = parse_layout(source["layout_code"])
        valid_original, why = validate_layout(original, rows, cols)
        if not valid_original:
            raise RuntimeError(f"invalid source layout {source['id']}: {why}")
        K0 = np.array(((float(source["K11"]), float(source["K12"]), float(source["K13"])), (float(source["K12"]), float(source["K22"]), float(source["K23"])), (float(source["K13"]), float(source["K23"]), float(source["K33"]))))
        P0 = np.array([[float(source[f"Kproj_{i}{j}"]) for j in range(1, 4)] for i in range(1, 4)])
        topo0 = topology(original, rows, cols); center0 = stiffness_center(K0, reference); rho0 = rho(K0)
        for name, S in TRANSFORMS.items():
            transformed = transform_layout(original, rows, cols, name)
            valid, reason = validate_layout(transformed, rows, cols)
            pm = assemble_single_storey_port_model(transformed, cfg)
            K1raw = condense_storey_to_3x3(pm, tuple(reference))
            K1 = 0.5 * (K1raw + K1raw.T)
            P1 = projection(transformed, rows, cols, cfg, kh, kv)
            expected_K = S.T @ K0 @ S; expected_P = S.T @ P0 @ S
            k_error = normalized_error(K1, expected_K); p_error = normalized_error(P1, expected_P)
            max_k_error = max(max_k_error, k_error); max_projection_error = max(max_projection_error, p_error)
            rho1 = rho(K1); expected_rho = np.array((S[0, 0] * S[2, 2] * rho0[0], S[1, 1] * S[2, 2] * rho0[1]))
            center1 = stiffness_center(K1, reference)
            delta0 = center0 - reference
            expected_center = reference + (np.array((-delta0[0], delta0[1])) if name == "mirror_x" else np.array((delta0[0], -delta0[1])) if name == "mirror_y" else -delta0)
            topo1 = topology(transformed, rows, cols)
            topology_pass = topo1 == topo0
            coupling_scale = max(abs(expected_K[0, 2]), abs(expected_K[1, 2]), math.sqrt(expected_K[0, 0] * expected_K[2, 2]), math.sqrt(expected_K[1, 1] * expected_K[2, 2]), 1.0)
            coupling_error = max(abs(K1[0, 2] - expected_K[0, 2]), abs(K1[1, 2] - expected_K[1, 2])) / coupling_scale
            center_error = float(np.linalg.norm(center1 - expected_center))
            rho_error = float(np.max(np.abs(rho1 - expected_rho)))
            rhoc_error = abs(float(np.linalg.norm(rho1) - np.linalg.norm(rho0)))
            checks = {
                "layout_legal_pass": valid,
                "topology_counts_pass": topology_pass,
                "K_congruence_pass": k_error <= REL_TOL,
                "Kproj_congruence_pass": p_error <= REL_TOL,
                "coupling_sign_pass": coupling_error <= REL_TOL,
                "stiffness_center_pass": center_error <= CENTER_TOL_MM,
                "rho_x_y_pass": rho_error <= RHO_TOL,
                "rho_c_pass": rhoc_error <= RHO_TOL,
            }
            results.append({
                "source_id": source["id"], "transform": name, "grid_rows": rows, "grid_cols": cols,
                "reference_center_x": reference[0], "reference_center_y": reference[1],
                "layout_legal_pass": valid, "layout_error": reason, "topology_counts_pass": topology_pass,
                "interfaces_original": topo0["interfaces"], "interfaces_transformed": topo1["interfaces"],
                "K_normalized_error": k_error, "Kproj_normalized_error": p_error,
                "coupling_normalized_error": coupling_error, "stiffness_center_error_mm": center_error,
                "rho_x_error": abs(rho1[0] - expected_rho[0]), "rho_y_error": abs(rho1[1] - expected_rho[1]), "rho_c_error": rhoc_error,
                "K_congruence_pass": checks["K_congruence_pass"], "Kproj_congruence_pass": checks["Kproj_congruence_pass"],
                "coupling_sign_pass": checks["coupling_sign_pass"], "stiffness_center_pass": checks["stiffness_center_pass"],
                "rho_x_y_pass": checks["rho_x_y_pass"], "rho_c_pass": checks["rho_c_pass"],
                "status": "PASS" if all(checks.values()) else "FAIL",
            })
    failures = sum(row["status"] == "FAIL" for row in results)
    fields = list(results[0])
    with (qa_dir / "A15_symmetry_QA.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(results)
    summary = {
        "original_layouts": len(database), "transformations_per_layout": 3, "tests_completed": len(results), "failures": failures,
        "K_max_normalized_error": max_k_error, "Kproj_max_normalized_error": max_projection_error,
        "stiffness_center_passed": sum(row["stiffness_center_pass"] for row in results),
        "stiffness_center_failures": sum(not row["stiffness_center_pass"] for row in results),
        "max_stiffness_center_error_mm": max(row["stiffness_center_error_mm"] for row in results),
        "tolerances": {"matrix_relative": REL_TOL, "center_mm": CENTER_TOL_MM, "rho_absolute": RHO_TOL},
        "status": "PASS" if failures == 0 else "FAIL", "exit_code": 0 if failures == 0 else 1,
    }
    (qa_dir / "A15_symmetry_QA_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    report = "# A15-A permanent geometric symmetry QA\n\n" + "\n".join((
        f"- Original layouts: {len(database)}", f"- Formal transformed tests: {len(results)}", f"- Failures: {failures}",
        f"- Maximum normalized K error: {max_k_error:.12e}", f"- Maximum normalized K_proj error: {max_projection_error:.12e}",
        f"- Stiffness-centre checks: {summary['stiffness_center_passed']}/{len(results)} passed", f"- Maximum stiffness-centre error: {summary['max_stiffness_center_error_mm']:.12e} mm",
        f"- Result: {summary['status']}",
    )) + "\n"
    (qa_dir / "A15_symmetry_QA_report.md").write_text(report, encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return summary["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
