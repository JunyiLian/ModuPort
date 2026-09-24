from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

import numpy as np
from scipy import sparse

from .finite_port import _link_B
from .finite_port_sparse import SparseFinitePortBuilding, SparseFinitePortGlobalBackend, _add, _storey
from ..connection_stiffness import resolve_vertical_connection
from ..late_condensation import (
    DOF_NAMES,
    ExplicitDOFRegistry,
    active_vertical_rotation_names,
    exact_sparse_late_schur,
)
from ..runtime import imports


@dataclass
class AugmentedModule:
    module: object
    retained_raw: np.ndarray
    temporary_raw: np.ndarray
    internal_raw: np.ndarray
    transform: np.ndarray
    K: np.ndarray
    M: np.ndarray
    metadata: dict


def _node_key(module, level, xs, ys):
    return (level, "C", xs, ys)


def _raw(module, level, xs, ys, dof):
    node = list(module.node_coordinates).index(_node_key(module, level, xs, ys))
    return 6 * node + DOF_NAMES.index(dof)


def _port_id(level, xs, ys):
    return f"{level}-C-{xs}{ys}"


def _augment_module(module, temporary_raw):
    baseline = list(map(int, module.retained_dof_indices))
    temporary = sorted(set(map(int, temporary_raw)) - set(baseline))
    retained = baseline + temporary
    internal = [i for i in range(len(module.K_full)) if i not in set(retained)]
    K = np.asarray(module.K_full, float)
    Kii = K[np.ix_(internal, internal)]
    Kir = K[np.ix_(internal, retained)]
    recovery = -np.linalg.solve(Kii, Kir) if internal else np.empty((0, len(retained)))
    T = np.zeros((len(K), len(retained)))
    T[retained] = np.eye(len(retained))
    if internal:
        T[internal] = recovery
    Ka = T.T @ K @ T
    Ma = T.T @ module.M_full_lumped @ T
    metadata = dict(module.port_metadata)
    for raw in temporary:
        node, dof = divmod(raw, 6)
        metadata[list(module.node_coordinates)[node] + (dof,)] = len(metadata)
    return AugmentedModule(
        module,
        np.asarray(baseline, int),
        np.asarray(temporary, int),
        np.asarray(internal, int),
        T,
        Ka,
        Ma,
        metadata,
    )


def _stacked_pairs(config, stores):
    parser = __import__("mscsolver._layout_parser_legacy", fromlist=["parse_layout"]).parse_layout
    result = []
    for si in range(len(stores) - 1):
        lower = parser(config.layout[si])
        upper = parser(config.layout[si + 1])
        upper_by = {(frozenset(p.cells), p.orientation): p for p in upper}
        for p in lower:
            up = upper_by.get((frozenset(p.cells), p.orientation))
            if up is not None:
                result.append((si, p, up))
    return result


def _link_deformation(link, u):
    if "endpoint_dofs" not in link:
        ids = np.r_[np.arange(link["i"], link["i"] + 6), np.arange(link["j"], link["j"] + 6)]
        return link["B"] @ u[ids]
    lower, upper = link["endpoint_dofs"]
    value = np.zeros(6)
    for d, (i, j) in enumerate(zip(lower, upper)):
        if i >= 0 and j >= 0:
            value[d] = u[j] - u[i]
    return value


def build_sparse_building_option_c(config):
    from ..modal_solver import _beam_mass

    t0 = perf_counter()
    stores = [_storey(config, expression) for expression in config.layout]
    cfg = stores[0].cfg
    resolved = resolve_vertical_connection(config.vertical_link)
    active_rotation_names = active_vertical_rotation_names(resolved.values)
    pairs = _stacked_pairs(config, stores)
    starts = np.cumsum([0] + [len(s.mods) for s in stores])
    module_lookup = {(si, m.module_id): m for si, s in enumerate(stores) for m in s.mods}

    temporary_by_module = {(si, m.module_id): set() for si, s in enumerate(stores) for m in s.mods}
    # TOP RZ is retained temporarily because the formal Body constraint owns it.
    for si, s in enumerate(stores):
        for m in s.mods:
            for xs in ("W", "E"):
                for ys in ("S", "N"):
                    temporary_by_module[(si, m.module_id)].add(_raw(m, "TOP", xs, ys, "RZ"))
    for si, lower, upper in pairs:
        lm = module_lookup[(si, lower.module_id)]
        um = module_lookup[(si + 1, upper.module_id)]
        for xs in ("W", "E"):
            for ys in ("S", "N"):
                for name in active_rotation_names:
                    temporary_by_module[(si, lm.module_id)].add(_raw(lm, "TOP", xs, ys, name))
                    temporary_by_module[(si + 1, um.module_id)].add(_raw(um, "BOT", xs, ys, name))

    augmented = []
    modules = []
    module_storeys = []
    module_offsets = []
    offsets = []
    N = 0
    for si, s in enumerate(stores):
        offsets.append(N)
        for m in s.mods:
            a = _augment_module(m, temporary_by_module[(si, m.module_id)])
            augmented.append(a)
            modules.append(m)
            module_storeys.append(si + 1)
            module_offsets.append(N)
            N += len(a.K)
        N += 24 * len(s.interfaces)

    rK = []
    cK = []
    dK = []
    rM = []
    cM = []
    dM = []
    registry = ExplicitDOFRegistry()
    augmented_by_instance = {}
    audit_rows = []
    cursor = 0
    for si, s in enumerate(stores):
        dz = si * (cfg.clear_storey_height + 2 * cfg.column_end_offset)
        for m in s.mods:
            a = augmented[cursor]
            offset = module_offsets[cursor]
            augmented_by_instance[(si, m.module_id)] = (a, offset)
            ids = np.arange(offset, offset + len(a.K))
            _add(rK, cK, dK, ids, a.K)
            _add(rM, cM, dM, ids, a.M)
            inverse = {index: key for key, index in a.metadata.items()}
            for local, key in inverse.items():
                level, kind, *tail, dof = key
                if kind != "C":
                    continue
                xs, ys = tail[:2]
                coordinate = np.asarray(m.node_coordinates[key[:-1]], float) + [0.0, 0.0, dz]
                registry.register(
                    (si + 1, m.module_id, _port_id(level, xs, ys), DOF_NAMES[dof]),
                    offset + local,
                    coordinate,
                    (si + 1, m.module_id),
                )
            cursor += 1

    horizontal = []
    cursor = 0
    for si, (go, s) in enumerate(zip(offsets, stores), 1):
        local_port = sum(len(augmented[cursor + i].K) for i in range(len(s.mods)))
        moffs = module_offsets[cursor : cursor + len(s.mods)]
        cores = [type("Core", (), {"port": m.port_metadata, "coords": m.node_coordinates}) for m in s.mods]
        by = {x.module_id: i for i, x in enumerate(s.specs)}
        expanded = [(it, level) for it in s.interfaces for level in ("FLOOR", "CEIL")]
        armbase = go + local_port
        armsec = type(cfg.sections()["column"])(
            2e6,
            2e6 / (2 * 1.3),
            cfg.arm["A_mm2"],
            cfg.arm["Iy_mm4"],
            cfg.arm["Iz_mm4"],
            cfg.arm["J_mm4"],
        )
        rho = float(cfg.steel_density_kg_m3) * 1e-9
        for h, (it, level) in enumerate(expanded):
            aa, bb = armbase + 12 * h, armbase + 12 * h + 6
            ia, ib = by[it.module_a], by[it.module_b]
            la, xa = s.fp._corner_port(cores[ia], s.specs[ia], it.side_a, it.tangent, it.endpoint_a, level, cfg)
            lb, xb = s.fp._corner_port(cores[ib], s.specs[ib], it.side_b, it.tangent, it.endpoint_b, level, cfg)
            fa, fb = s.fp._face(it, True, level, cfg), s.fp._face(it, False, level, cfg)
            T = s.fp.connection_transformation(it)
            k = cfg.horizontal_connection.matrix()
            B = _link_B(fa, fb, T)
            idx = np.r_[np.arange(aa, aa + 6), np.arange(bb, bb + 6)]
            _add(rK, cK, dK, idx, B.T @ k @ B)
            for x0, x1, co, ao in ((xa, fa, moffs[ia] + la, aa), (xb, fb, moffs[ib] + lb, bb)):
                local = np.r_[np.arange(co, co + 6), np.arange(ao, ao + 6)]
                ke = cfg._beam_function(np.asarray(x0), np.asarray(x1), armsec)
                me = _beam_mass(np.asarray(x0), np.asarray(x1), rho, armsec.A, armsec.Iy, armsec.Iz, True)
                _add(rK, cK, dK, local, ke)
                _add(rM, cM, dM, local, me)
            dz = (si - 1) * (cfg.clear_storey_height + 2 * cfg.column_end_offset)
            horizontal.append(
                {"id": f"S{si}_H{it.index}_{level}", "i": aa, "j": bb, "x_i": np.asarray(fa) + [0, 0, dz], "x_j": np.asarray(fb) + [0, 0, dz], "K": k, "B": B}
            )
        cursor += len(s.mods)

    vertical = []
    for si, lower, upper in pairs:
        lm = module_lookup[(si, lower.module_id)]
        um = module_lookup[(si + 1, upper.module_id)]
        step = cfg.clear_storey_height + 2 * cfg.column_end_offset
        for xs in ("W", "E"):
            for ys in ("S", "N"):
                lower_coord = np.asarray(lm.node_coordinates[_node_key(lm, "TOP", xs, ys)], float) + [0, 0, si * step]
                upper_coord = np.asarray(um.node_coordinates[_node_key(um, "BOT", xs, ys)], float) + [0, 0, (si + 1) * step]
                if not np.allclose(lower_coord, upper_coord, atol=1e-8, rtol=0.0):
                    raise AssertionError("vertical endpoint coordinate mismatch")
                lower_indices = []
                upper_indices = []
                for dof, value in zip(DOF_NAMES, resolved.values):
                    if value == 0.0 and dof.startswith("R"):
                        lower_indices.append(-1)
                        upper_indices.append(-1)
                        continue
                    lower_indices.append(
                        registry.resolve(
                            (si + 1, lm.module_id, _port_id("TOP", xs, ys), dof),
                            expected_owner=(si + 1, lm.module_id),
                            expected_coordinate=lower_coord,
                        )
                    )
                    upper_indices.append(
                        registry.resolve(
                            (si + 2, um.module_id, _port_id("BOT", xs, ys), dof),
                            expected_owner=(si + 2, um.module_id),
                            expected_coordinate=upper_coord,
                        )
                    )
                for d, stiffness in enumerate(resolved.values):
                    if stiffness == 0.0:
                        continue
                    i, j = lower_indices[d], upper_indices[d]
                    rK.extend((i, i, j, j))
                    cK.extend((i, j, i, j))
                    dK.extend((stiffness, -stiffness, -stiffness, stiffness))
                link_id = f"V{si + 1}_{lower.orientation}{lower.module_id:02d}_{xs}{ys}"
                identity = {
                    "link_id": link_id,
                    "lower_storey": si + 1,
                    "upper_storey": si + 2,
                    "lower_module_id": lower.module_id,
                    "upper_module_id": upper.module_id,
                    "corner_id": xs + ys,
                    "lower_dof_indices": lower_indices,
                    "upper_dof_indices": upper_indices,
                    "x_lower": lower_coord.tolist(),
                    "x_upper": upper_coord.tolist(),
                }
                vertical.append(
                    {"id": link_id, "i": lower_indices[0], "j": upper_indices[0], "K": np.diag(resolved.values), "endpoint_dofs": (lower_indices, upper_indices), "identity": identity}
                )
                for endpoint, m, level, indices in (("lower", lm, "TOP", lower_indices), ("upper", um, "BOT", upper_indices)):
                    audit_rows.append(
                        {
                            "module_id": m.module_id,
                            "port_id": _port_id(level, xs, ys),
                            "coordinate": lower_coord.tolist(),
                            "connection_id": link_id,
                            "connection_type": config.vertical_link.get("type", resolved.source),
                            "RX_active": indices[3] >= 0,
                            "RY_active": indices[4] >= 0,
                            "RZ_active": indices[5] >= 0,
                            "reason": f"{endpoint} endpoint; nonzero constitutive rotation or TOP Body RZ requirement",
                            "augmented_indices": indices,
                            "final_condensed_status": "TOP RZ maps to macro; other temporary rotations late-condensed",
                        }
                    )

    K = sparse.coo_matrix((dK, (rK, cK)), shape=(N, N)).tocsr()
    M = sparse.coo_matrix((dM, (rM, cM)), shape=(N, N)).tocsr()
    K.sum_duplicates()
    M.sum_duplicates()

    fixed = []
    top = []
    temporary_global = []
    for a, offset, si in zip(augmented, module_offsets, module_storeys):
        m = a.module
        inverse = {index: key for key, index in a.metadata.items()}
        for local, key in inverse.items():
            if si == 1 and key[0] == "BOT" and key[-1] < 3:
                fixed.append(offset + local)
            if key[0] == "TOP" and key[-1] in (0, 1, 5):
                top.append((offset + local, m.node_coordinates[key[:-1]], key[-1], si))
        for local in range(len(a.retained_raw), len(a.K)):
            key = inverse[local]
            if not (key[0] == "TOP" and key[-1] == 5):
                temporary_global.append(offset + local)

    removed = set(fixed + [x[0] for x in top])
    free = [i for i in range(N) if i not in removed]
    free_column = {row: column for column, row in enumerate(free)}
    macro = np.arange(len(free), len(free) + 3 * config.storeys).reshape(config.storeys, 3)
    ar = list(free)
    ac = list(range(len(free)))
    ad = [1.0] * len(free)
    xref, yref = map(float, config.data["reference_point"])
    for row, point, dof, si in top:
        if dof in (0, 1):
            ar.append(row)
            ac.append(int(macro[si - 1, dof]))
            ad.append(1.0)
            ar.append(row)
            ac.append(int(macro[si - 1, 2]))
            ad.append(float(-(point[1] - yref) if dof == 0 else point[0] - xref))
        else:
            ar.append(row)
            ac.append(int(macro[si - 1, 2]))
            ad.append(1.0)
    A0 = sparse.coo_matrix((ad, (ar, ac)), shape=(N, len(free) + 3 * config.storeys)).tocsr()
    Kc = (A0.T @ K @ A0).tocsr()
    Mc = (A0.T @ M @ A0).tocsr()
    temporary_columns = [free_column[index] for index in temporary_global if index in free_column]
    Kr, Mr, late = exact_sparse_late_schur(Kc, Mc, temporary_columns)
    if late is None:
        Tlate = sparse.eye(Kc.shape[0], format="csr")
        final_map = {i: i for i in range(Kc.shape[0])}
        late_diag = {"temporary_dofs": 0, "final_dofs": Kc.shape[0], "schur_fill_in": 0, "mass_temporary_zero": True}
    else:
        nr = len(late.final_indices)
        rows = list(map(int, late.final_indices))
        cols = list(range(nr))
        vals = [1.0] * nr
        ii, jj = late.recovery_matrix.nonzero()
        rows.extend(late.temporary_indices[ii])
        cols.extend(jj)
        vals.extend(late.recovery_matrix[ii, jj].A1)
        Tlate = sparse.coo_matrix((vals, (rows, cols)), shape=(Kc.shape[0], nr)).tocsr()
        final_map = {int(old): new for new, old in enumerate(late.final_indices)}
        late_diag = late.diagnostics
    A = (A0 @ Tlate).tocsr()
    final_macro = np.asarray([final_map[int(index)] for index in macro.reshape(-1)], int)
    mem = lambda X: X.data.nbytes + X.indices.nbytes + X.indptr.nbytes
    diagnostics = {
        "global_dofs": N,
        "augmented_constrained_dofs": Kc.shape[0],
        "constrained_solve_dofs": Kr.shape[0],
        "nnz_K": Kr.nnz,
        "nnz_M": Mr.nnz,
        "density_K": Kr.nnz / (Kr.shape[0] ** 2),
        "density_M": Mr.nnz / (Mr.shape[0] ** 2),
        "csr_K_bytes": mem(Kr),
        "csr_M_bytes": mem(Mr),
        "estimated_dense_K_bytes": 8 * N * N,
        "ordinary_internal_building_dofs": 0,
        "module_port_dofs": sum(len(m.K_port) for m in modules),
        "augmented_module_dofs": sum(len(a.K) for a in augmented),
        "temporary_rotation_count": len(temporary_columns),
        "horizontal_links": len(horizontal),
        "vertical_links": len(vertical),
        "vertical_assembly_identity_mismatch_count": 0,
        "vertical_assembly_audit": audit_rows,
        "dof_registry_size": len(registry.records()),
        "unsafe_contiguous_vertical_slice": False,
        "late_condensation": late_diag,
        "assembly_s": perf_counter() - t0,
    }
    recovery = [(np.arange(offset, offset + len(a.K)), a.transform) for a, offset in zip(augmented, module_offsets)]
    building = SparseFinitePortBuilding(
        K,
        M,
        A,
        Kr,
        Mr,
        modules,
        module_offsets,
        horizontal,
        vertical,
        np.asarray(fixed, int),
        final_macro,
        recovery,
        module_storeys,
        diagnostics,
    )
    building.late_schur = late
    building.dof_registry = registry
    building.augmented_modules = augmented
    return building


class SparseFinitePortOptionCBackend(SparseFinitePortGlobalBackend):
    name = "finite_port"
    solver_backend = "FINITE_PORT_SUPERELEMENT"
    global_storage = "sparse"

    def build_building(self):
        building = build_sparse_building_option_c(self.config)
        self.last_building = building
        self.timings["global_assembly_s"] = building.diagnostics["assembly_s"]
        return building
