"""4x4 模块化建筑层间刚度代理模型（N-mm-s 单位制）。

核心定义：每一层的下端口平面为零参考，上端口平面保留
delta=[Delta ux, Delta uy, Delta theta z]^T；其余自由度自由调整，
通过 Schur 凝聚得到 3x3 层间广义刚度 K_story。

当前连接简化：水平和竖向连接均只协调 ux,uy,uz，连接两侧转角独立。
"""
from __future__ import annotations

# A4 formal default: finite module-port assembly with 6-DOF local Link
# matrices, finite 114.3-mm arms and P2/P3 ports; ``legacy_union`` is retained
# below only for historical comparison.  Final K is an inter-storey [ux,uy,rz].

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple
import csv
import json
import math

import numpy as np
from scipy import linalg
from scipy.sparse import coo_matrix, csc_matrix
from scipy.sparse.linalg import splu

# A10 formal pure six-DOF port path.  Imported lazily by callers so legacy
# single-storey/public calculations remain backward compatible.
from ._finite_port import build_six_dof_pure_port_model, solve_six_dof_pure_port_model


Cell = Tuple[int, int]


@dataclass(frozen=True)
class Placement:
    module_id: int
    orientation: str
    cells: Tuple[Cell, Cell]


@dataclass(frozen=True)
class Section:
    E: float
    G: float
    A: float
    Iy: float
    Iz: float
    J: float


@dataclass(frozen=True)
class ConnectionStiffness:
    """Six-DOF local connection law; a supplied matrix must be symmetric."""
    name: str = "PIN_TRANSLATION_1E8"
    ku1: float = 1.0e8
    ku2: float = 1.0e8
    ku3: float = 1.0e8
    kr1: float = 0.0
    kr2: float = 0.0
    kr3: float = 0.0
    local_matrix: np.ndarray | None = None

    def matrix(self) -> np.ndarray:
        result = np.diag((self.ku1, self.ku2, self.ku3, self.kr1, self.kr2, self.kr3)) if self.local_matrix is None else np.asarray(self.local_matrix, dtype=float)
        if result.shape != (6, 6) or not np.allclose(result, result.T, rtol=1e-12, atol=1e-12):
            raise ValueError("ConnectionStiffness.local_matrix must be symmetric 6x6")
        return result


@dataclass
class ModelConfig:
    grid_rows: int = 4
    grid_cols: int = 4
    storeys: int = 3
    module_long_outer: float = 6000.0
    module_short_outer: float = 2990.0
    module_long_centerline: float = 5771.4
    module_short_centerline: float = 2761.4
    module_clear_gap: float = 20.0
    clear_storey_height: float = 3000.0
    column_end_offset: float = 78.5
    steel_E: float = 200000.0
    steel_nu: float = 0.30
    steel_density_kg_m3: float = 7850.0
    floor_mass_kg_m2: float = 500.0
    added_floor_mass_kg: float = 0.0
    # A4 defaults: finite port connections.  Vertical baseline is the existing
    # SAP translational link definition (1e8 N/mm; rotations released).
    connection_model: str = "finite_port"
    horizontal_connection: ConnectionStiffness = field(default_factory=ConnectionStiffness)
    vertical_connection: ConnectionStiffness = field(default_factory=lambda: ConnectionStiffness("VERTICAL_PIN_TRANSLATION_1E8"))
    connection_overrides: Dict[object, ConnectionStiffness] = field(default_factory=dict)

    @property
    def column_half_mm(self) -> float:
        return 0.5 * (self.module_short_outer - self.module_short_centerline)

    @property
    def steel_G(self) -> float:
        return self.steel_E / (2.0 * (1.0 + self.steel_nu))

    @property
    def cell_pitch(self) -> float:
        return self.module_short_outer + self.module_clear_gap

    @property
    def total_column_height(self) -> float:
        return self.clear_storey_height + 2.0 * self.column_end_offset

    def sections(self) -> Dict[str, Section]:
        return {
            "column": hss_section(228.6, 228.6, 15.9, self.steel_E, self.steel_G),
            "floor_long": hss_section(127.0, 127.0, 7.9, self.steel_E, self.steel_G),
            "floor_short": hss_section(127.0, 127.0, 7.9, self.steel_E, self.steel_G),
            "ceiling_long": hss_section(127.0, 50.8, 9.5, self.steel_E, self.steel_G),
            "ceiling_short": hss_section(127.0, 50.8, 9.5, self.steel_E, self.steel_G),
        }


def hss_section(depth: float, width: float, thickness: float, E: float, G: float) -> Section:
    """Sharp-corner rectangular HSS properties; J uses a closed thin-wall median-line model."""
    di = depth - 2.0 * thickness
    wi = width - 2.0 * thickness
    if min(di, wi, thickness) <= 0.0:
        raise ValueError("HSS dimensions are invalid")
    area = depth * width - di * wi
    iy = (width * depth**3 - wi * di**3) / 12.0
    iz = (depth * width**3 - di * wi**3) / 12.0
    dm = depth - thickness
    wm = width - thickness
    enclosed = dm * wm
    j = 4.0 * enclosed**2 / (2.0 * (dm + wm) / thickness)
    return Section(E, G, area, iy, iz, j)


def enumerate_domino_layouts(rows: int = 4, cols: int = 4) -> List[List[Placement]]:
    """Enumerate all labelled-by-position domino tilings; a 4x4 board has 36."""
    occupied = [[False] * cols for _ in range(rows)]
    raw: List[List[Tuple[str, Cell, Cell]]] = []

    def first_empty() -> Cell | None:
        for r in range(rows):
            for c in range(cols):
                if not occupied[r][c]:
                    return r, c
        return None

    def visit(current: List[Tuple[str, Cell, Cell]]) -> None:
        cell = first_empty()
        if cell is None:
            raw.append(current.copy())
            return
        r, c = cell
        for orientation, other in (("H", (r, c + 1)), ("V", (r + 1, c))):
            rr, cc = other
            if rr >= rows or cc >= cols or occupied[rr][cc]:
                continue
            occupied[r][c] = occupied[rr][cc] = True
            current.append((orientation, (r, c), other))
            visit(current)
            current.pop()
            occupied[r][c] = occupied[rr][cc] = False

    visit([])
    layouts: List[List[Placement]] = []
    for tiling in raw:
        ordered = sorted(tiling, key=lambda x: min(x[1], x[2]))
        layouts.append([Placement(i + 1, p[0], (p[1], p[2])) for i, p in enumerate(ordered)])
    return layouts


def layout_matrix(layout: Sequence[Placement], rows: int = 4, cols: int = 4) -> List[List[str]]:
    result = [["" for _ in range(cols)] for _ in range(rows)]
    for p in layout:
        label = f"{p.orientation}{p.module_id:02d}"
        for r, c in p.cells:
            result[r][c] = label
    return result


def layout_matrix_text(layout: Sequence[Placement], rows: int = 4, cols: int = 4) -> str:
    return " / ".join(" ".join(row) for row in layout_matrix(layout, rows, cols))


class UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


class FrameModel:
    def __init__(self) -> None:
        self.coords: List[np.ndarray] = []
        self.elements: List[Tuple[int, int, Section]] = []
        self.boundary_nodes: Dict[Tuple[int, str, int, int], int] = {}
        self.bottom_nodes: List[int] = []
        self.top_nodes: List[int] = []
        self.horizontal_pin_pairs: List[Tuple[int, int]] = []

    def node(self, xyz: Iterable[float]) -> int:
        self.coords.append(np.asarray(tuple(xyz), dtype=float))
        return len(self.coords) - 1

    def element(self, a: int, b: int, section: Section) -> None:
        self.elements.append((a, b, section))


def _module_boundary(p: Placement) -> Tuple[int, int, int, int, List[Cell]]:
    cells = sorted(p.cells)
    rs = [x[0] for x in cells]
    cs = [x[1] for x in cells]
    r0, r1, c0, c1 = min(rs), max(rs) + 1, min(cs), max(cs) + 1
    if p.orientation == "H":
        vertices = [(r0, c0), (r0, c0 + 1), (r0, c1), (r1, c1), (r1, c0 + 1), (r1, c0)]
    else:
        vertices = [(r0, c0), (r0, c1), (r0 + 1, c1), (r1, c1), (r1, c0), (r0 + 1, c0)]
    return r0, r1, c0, c1, vertices


def _physical_xy(p: Placement, vertex: Cell, cfg: ModelConfig) -> Tuple[float, float]:
    r0, r1, c0, c1, _ = _module_boundary(p)
    r, c = vertex
    x_outer0, y_outer0 = c0 * cfg.cell_pitch, r0 * cfg.cell_pitch
    width = cfg.module_long_outer if p.orientation == "H" else cfg.module_short_outer
    height = cfg.module_short_outer if p.orientation == "H" else cfg.module_long_outer
    inset = 0.5 * (cfg.module_short_outer - cfg.module_short_centerline)
    x = x_outer0 + (inset if c == c0 else width - inset if c == c1 else width / 2.0)
    y = y_outer0 + (inset if r == r0 else height - inset if r == r1 else height / 2.0)
    return x, y


def build_frame_model(layout: Sequence[Placement], cfg: ModelConfig) -> FrameModel:
    sections = cfg.sections()
    model = FrameModel()
    z_floor = cfg.column_end_offset
    z_ceiling = cfg.column_end_offset + cfg.clear_storey_height
    z_top = cfg.total_column_height

    placement_by_id = {p.module_id: p for p in layout}
    cell_owner = {cell: p.module_id for p in layout for cell in p.cells}

    for p in layout:
        r0, r1, c0, c1, vertices = _module_boundary(p)
        corners = {(r0, c0), (r0, c1), (r1, c1), (r1, c0)}
        plane_nodes: Dict[str, Dict[Cell, int]] = {"floor": {}, "ceiling": {}}
        for level, z in (("floor", z_floor), ("ceiling", z_ceiling)):
            for vertex in vertices:
                x, y = _physical_xy(p, vertex, cfg)
                node = model.node((x, y, z))
                plane_nodes[level][vertex] = node
                model.boundary_nodes[(p.module_id, level, vertex[0], vertex[1])] = node
            for i, v1 in enumerate(vertices):
                v2 = vertices[(i + 1) % len(vertices)]
                n1, n2 = plane_nodes[level][v1], plane_nodes[level][v2]
                dx = abs(model.coords[n2][0] - model.coords[n1][0])
                dy = abs(model.coords[n2][1] - model.coords[n1][1])
                # The split half-long edge (~2886 mm) is close to the short
                # edge (~2761 mm), so classify by orientation, not length.
                is_long = (dx > dy) if p.orientation == "H" else (dy > dx)
                sec = sections[f"{level}_{'long' if is_long else 'short'}"]
                model.element(n1, n2, sec)
        for vertex in corners:
            x, y = _physical_xy(p, vertex, cfg)
            nb = model.node((x, y, 0.0))
            nt = model.node((x, y, z_top))
            nf = plane_nodes["floor"][vertex]
            nc = plane_nodes["ceiling"][vertex]
            model.element(nb, nf, sections["column"])
            model.element(nf, nc, sections["column"])
            model.element(nc, nt, sections["column"])
            model.bottom_nodes.append(nb)
            model.top_nodes.append(nt)

    # Every shared basic-cell edge is an interface. Connect its two endpoints at
    # floor and ceiling levels; diagonal-only contacts never enter this loop.
    for r in range(cfg.grid_rows):
        for c in range(cfg.grid_cols):
            owner = cell_owner[(r, c)]
            for dr, dc, endpoints in (
                (0, 1, ((r, c + 1), (r + 1, c + 1))),
                (1, 0, ((r + 1, c), (r + 1, c + 1))),
            ):
                rr, cc = r + dr, c + dc
                if rr >= cfg.grid_rows or cc >= cfg.grid_cols:
                    continue
                other = cell_owner[(rr, cc)]
                if other == owner:
                    continue
                for level in ("floor", "ceiling"):
                    for vr, vc in endpoints:
                        n1 = model.boundary_nodes[(owner, level, vr, vc)]
                        n2 = model.boundary_nodes[(other, level, vr, vc)]
                        model.horizontal_pin_pairs.append((n1, n2))
    return model


def beam3d_global_stiffness(x1: np.ndarray, x2: np.ndarray, s: Section) -> np.ndarray:
    delta = x2 - x1
    L = float(np.linalg.norm(delta))
    if L <= 1.0e-9:
        raise ValueError("zero-length frame element")
    ex = delta / L
    reference = np.array([0.0, 0.0, 1.0])
    if abs(float(np.dot(ex, reference))) > 0.9:
        reference = np.array([0.0, 1.0, 0.0])
    ey = np.cross(reference, ex)
    ey /= np.linalg.norm(ey)
    ez = np.cross(ex, ey)
    rot = np.vstack((ex, ey, ez))
    transform = np.zeros((12, 12))
    for start in (0, 3, 6, 9):
        transform[start:start + 3, start:start + 3] = rot

    k = np.zeros((12, 12))
    EA, GJ = s.E * s.A, s.G * s.J
    EIy, EIz = s.E * s.Iy, s.E * s.Iz
    k[0, 0] = k[6, 6] = EA / L
    k[0, 6] = k[6, 0] = -EA / L
    k[3, 3] = k[9, 9] = GJ / L
    k[3, 9] = k[9, 3] = -GJ / L

    # Local-y translation / local-z bending.
    a, b, c, d = 12 * EIz / L**3, 6 * EIz / L**2, 4 * EIz / L, 2 * EIz / L
    ids = (1, 5, 7, 11)
    block = np.array([[a, b, -a, b], [b, c, -b, d], [-a, -b, a, -b], [b, d, -b, c]])
    k[np.ix_(ids, ids)] += block
    # Local-z translation / local-y bending.
    a, b, c, d = 12 * EIy / L**3, 6 * EIy / L**2, 4 * EIy / L, 2 * EIy / L
    ids = (2, 4, 8, 10)
    block = np.array([[a, -b, -a, -b], [-b, c, b, d], [-a, b, a, b], [-b, d, b, c]])
    k[np.ix_(ids, ids)] += block
    return transform.T @ k @ transform


def condense_story_stiffness(layout: Sequence[Placement], cfg: ModelConfig) -> Tuple[np.ndarray, Dict[str, float]]:
    model = build_frame_model(layout, cfg)
    full_dofs = 6 * len(model.coords)
    uf = UnionFind(full_dofs)
    for n1, n2 in model.horizontal_pin_pairs:
        for dof in range(3):
            uf.union(6 * n1 + dof, 6 * n2 + dof)
    roots = sorted({uf.find(i) for i in range(full_dofs)})
    root_index = {root: i for i, root in enumerate(roots)}
    mapping = np.array([root_index[uf.find(i)] for i in range(full_dofs)], dtype=int)
    ndof = len(roots)

    row: List[int] = []
    col: List[int] = []
    data: List[float] = []
    for n1, n2, section in model.elements:
        ke = beam3d_global_stiffness(model.coords[n1], model.coords[n2], section)
        edofs = [6 * n1 + i for i in range(6)] + [6 * n2 + i for i in range(6)]
        reduced = mapping[edofs]
        for i in range(12):
            for j in range(12):
                if abs(ke[i, j]) > 0.0:
                    row.append(int(reduced[i])); col.append(int(reduced[j])); data.append(float(ke[i, j]))
    K = coo_matrix((data, (row, col)), shape=(ndof, ndof)).tocsc()

    lower = {int(mapping[6 * n + d]) for n in model.bottom_nodes for d in range(3)}
    upper_xyz = {int(mapping[6 * n + d]) for n in model.top_nodes for d in range(3)}
    constrained = lower | upper_xyz
    free = np.array([i for i in range(ndof) if i not in constrained], dtype=int)

    xs = [model.coords[n][0] for n in model.top_nodes]
    ys = [model.coords[n][1] for n in model.top_nodes]
    x0, y0 = 0.5 * (min(xs) + max(xs)), 0.5 * (min(ys) + max(ys))
    R = np.zeros((ndof, 3))
    for n in model.top_nodes:
        x, y, _ = model.coords[n]
        ix, iy = int(mapping[6 * n]), int(mapping[6 * n + 1])
        R[ix] = (1.0, 0.0, -(y - y0))
        R[iy] = (0.0, 1.0, +(x - x0))

    Kdd = R.T @ (K @ R)
    Kdf = np.asarray(R.T @ K[:, free])
    Kff = csc_matrix(K[free, :][:, free])
    try:
        solution = splu(Kff).solve(Kdf.T)
    except RuntimeError as exc:
        raise RuntimeError("Local stiffness is singular; inspect mechanisms or duplicate generalized modes") from exc
    Ks = Kdd - Kdf @ solution
    Ks = 0.5 * (Ks + Ks.T)
    scale = max(float(np.linalg.norm(Ks)), 1.0)
    symmetry_error = float(np.linalg.norm(Ks - Ks.T) / scale)
    eigenvalues = np.linalg.eigvalsh(Ks)
    diagnostics = {
        "nodes": float(len(model.coords)),
        "frames": float(len(model.elements)),
        "horizontal_pin_pairs": float(len(model.horizontal_pin_pairs)),
        "independent_dofs": float(ndof),
        "local_dofs": float(len(free)),
        "symmetry_error": symmetry_error,
        "min_story_eigenvalue": float(eigenvalues[0]),
    }
    return Ks, diagnostics


def assemble_building(story_matrices: Sequence[np.ndarray]) -> np.ndarray:
    n = len(story_matrices)
    D = np.zeros((3 * n, 3 * n))
    eye = np.eye(3)
    for s in range(n):
        D[3 * s:3 * s + 3, 3 * s:3 * s + 3] = eye
        if s > 0:
            D[3 * s:3 * s + 3, 3 * (s - 1):3 * (s - 1) + 3] = -eye
    Kblock = linalg.block_diag(*story_matrices)
    return D.T @ Kblock @ D


def floor_mass_matrix(layout: Sequence[Placement], cfg: ModelConfig) -> np.ndarray:
    area_m2 = len(layout) * cfg.module_long_outer * cfg.module_short_outer / 1.0e6
    frame_model = build_frame_model(layout, cfg)
    steel_volume_mm3 = sum(
        section.A * float(np.linalg.norm(frame_model.coords[n2] - frame_model.coords[n1]))
        for n1, n2, section in frame_model.elements
    )
    steel_mass_kg = steel_volume_mm3 * 1.0e-9 * cfg.steel_density_kg_m3
    mass_kg = area_m2 * cfg.floor_mass_kg_m2 + cfg.added_floor_mass_kg + steel_mass_kg
    xs: List[float] = []
    ys: List[float] = []
    for p in layout:
        r0, r1, c0, c1, vertices = _module_boundary(p)
        for vertex in vertices:
            x, y = _physical_xy(p, vertex, cfg)
            xs.append(x); ys.append(y)
    lx, ly = max(xs) - min(xs), max(ys) - min(ys)
    polar_kg_mm2 = mass_kg * (lx**2 + ly**2) / 12.0
    return np.diag((mass_kg / 1000.0, mass_kg / 1000.0, polar_kg_mm2 / 1000.0))


def building_results(story_layouts: Sequence[Sequence[Placement]], story_matrices: Sequence[np.ndarray], cfg: ModelConfig) -> Dict[str, object]:
    Kb = assemble_building(story_matrices)
    masses = [floor_mass_matrix(layout, cfg) for layout in story_layouts]
    Mb = linalg.block_diag(*masses)
    evals, _ = linalg.eigh(Kb, Mb, check_finite=True)
    evals = np.maximum(evals, 0.0)
    omega = np.sqrt(evals)
    frequencies = omega / (2.0 * math.pi)
    periods = np.divide(1.0, frequencies, out=np.full_like(frequencies, np.inf), where=frequencies > 0)

    n = len(story_matrices)
    top = 3 * (n - 1)
    unit_fx = np.zeros(3 * n); unit_fx[top] = 1000.0
    unit_fy = np.zeros(3 * n); unit_fy[top + 1] = 1000.0
    unit_mz = np.zeros(3 * n); unit_mz[top + 2] = 1.0e6
    ux = linalg.solve(Kb, unit_fx, assume_a="sym")
    uy = linalg.solve(Kb, unit_fy, assume_a="sym")
    ut = linalg.solve(Kb, unit_mz, assume_a="sym")

    return {
        "K_building": Kb,
        "M_building": Mb,
        "frequencies_hz": frequencies,
        "periods_s": periods,
        "roof_ux_mm_per_1kN_X": float(ux[top]),
        "roof_uy_mm_per_1kN_Y": float(uy[top + 1]),
        "roof_theta_mrad_per_1kNm": float(ut[top + 2] * 1000.0),
        "roof_theta_mrad_per_1kN_X": float(ux[top + 2] * 1000.0),
        "roof_theta_mrad_per_1kN_Y": float(uy[top + 2] * 1000.0),
    }


def matrix_json(matrix: np.ndarray) -> str:
    return json.dumps(np.asarray(matrix).tolist(), ensure_ascii=False, separators=(",", ":"))


def result_row(layout_id: int, story_layouts: Sequence[Sequence[Placement]], story_matrices: Sequence[np.ndarray], diagnostics: Sequence[Dict[str, float]], cfg: ModelConfig) -> Dict[str, object]:
    layout = story_layouts[0]
    result = building_results(story_layouts, story_matrices, cfg)
    Ks = story_matrices[0]
    freqs = result["frequencies_hz"]
    periods = result["periods_s"]
    row: Dict[str, object] = {
        "layout_matrix": layout_matrix_text(layout, cfg.grid_rows, cfg.grid_cols),
        "layout_id": layout_id,
        "story_layout_ids": "same" if all(x == story_layouts[0] for x in story_layouts) else "mixed",
        "H_modules": sum(p.orientation == "H" for p in layout),
        "V_modules": sum(p.orientation == "V" for p in layout),
        "K_story_3x3_json": matrix_json(Ks),
        "K11_N_per_mm": Ks[0, 0], "K12_N_per_mm": Ks[0, 1],
        "K22_N_per_mm": Ks[1, 1], "K13_N": Ks[0, 2],
        "K23_N": Ks[1, 2], "K33_Nmm_per_rad": Ks[2, 2],
        "K_building_9x9_json": matrix_json(result["K_building"]),
        "roof_ux_mm_per_1kN_X": result["roof_ux_mm_per_1kN_X"],
        "roof_uy_mm_per_1kN_Y": result["roof_uy_mm_per_1kN_Y"],
        "roof_theta_mrad_per_1kNm": result["roof_theta_mrad_per_1kNm"],
        "roof_theta_mrad_per_1kN_X": result["roof_theta_mrad_per_1kN_X"],
        "roof_theta_mrad_per_1kN_Y": result["roof_theta_mrad_per_1kN_Y"],
        "story_nodes": int(diagnostics[0]["nodes"]),
        "story_frames": int(diagnostics[0]["frames"]),
        "horizontal_pin_pairs": int(diagnostics[0]["horizontal_pin_pairs"]),
        "symmetry_error": diagnostics[0]["symmetry_error"],
        "min_story_eigenvalue": diagnostics[0]["min_story_eigenvalue"],
    }
    for i in range(min(6, len(freqs))):
        row[f"f{i + 1}_Hz"] = float(freqs[i])
        row[f"T{i + 1}_s"] = float(periods[i])
    return row


def write_rows(path: Path, rows: Sequence[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError("no result rows")
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


# A4 finite-port override.  The original function remains available for
# historical reproduction as ``legacy_condense_story_stiffness``.
legacy_condense_story_stiffness = condense_story_stiffness


def condense_story_stiffness(layout: Sequence[Placement], cfg: ModelConfig) -> Tuple[np.ndarray, Dict[str, float]]:
    """Return one storey's inter-storey generalized [ux, uy, rz] stiffness.

    ``finite_port`` (default) retains module connection ports until all finite
    Link matrices and short arms are assembled. ``legacy_union`` is retained
    only as an explicit historical/infinite-compatibility comparison mode.
    """
    if cfg.connection_model == "legacy_union":
        return legacy_condense_story_stiffness(layout, cfg)
    if cfg.connection_model != "finite_port":
        raise ValueError("connection_model must be 'finite_port' or 'legacy_union'")
    # The engine uses this injected function rather than duplicating frame math.
    cfg._beam_function = beam3d_global_stiffness
    cfg._legacy_condense = legacy_condense_story_stiffness
    from ._finite_port import compute_layout_storey_stiffness
    rows = 1 + max(row for placement in layout for row, _ in placement.cells)
    cols = 1 + max(col for placement in layout for _, col in placement.cells)
    reference_point = (cols * cfg.cell_pitch / 2, rows * cfg.cell_pitch / 2)
    return compute_layout_storey_stiffness(layout, cfg, reference_point, cfg.connection_model)


# Public finite-port APIs, imported here to keep existing callers importing only
# this formal theory module.
from ._finite_port import (  # noqa: E402
    ModulePortModel, PortLevelStoreyModel, Interface,
    build_module_port_stiffness, identify_layout_interfaces,
    connection_local_matrix, connection_transformation,
    assemble_finite_connection, assemble_single_storey_port_model,
    condense_storey_to_3x3, compute_layout_storey_stiffness,
    MultiStoreyPortModel, global_port_dof, build_multistorey_port_model,
    solve_multistorey_port_response, fit_storey_generalized_response,
)
