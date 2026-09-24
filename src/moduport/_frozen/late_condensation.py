from __future__ import annotations

from dataclasses import dataclass
from typing import Hashable

import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import splu


DOF_NAMES = ("UX", "UY", "UZ", "RX", "RY", "RZ")


@dataclass(frozen=True)
class DOFRecord:
    key: tuple[Hashable, ...]
    index: int
    coordinate: tuple[float, float, float]
    owner: tuple[int, int]


class ExplicitDOFRegistry:
    """Physical-port keyed registry; never infers ownership from index adjacency."""

    def __init__(self) -> None:
        self._records: dict[tuple[Hashable, ...], DOFRecord] = {}
        self._index_owner: dict[int, tuple[Hashable, ...]] = {}

    def register(self, key, index: int, coordinate, owner) -> None:
        key = tuple(key)
        coordinate = tuple(map(float, coordinate))
        owner = tuple(owner)
        if key in self._records:
            raise AssertionError(f"duplicate physical DOF key: {key}")
        if int(index) in self._index_owner:
            raise AssertionError(f"duplicate equation ownership: {index}")
        self._records[key] = DOFRecord(key, int(index), coordinate, owner)
        self._index_owner[int(index)] = key

    def resolve(self, key, *, expected_owner=None, expected_coordinate=None) -> int:
        key = tuple(key)
        if key not in self._records:
            raise AssertionError(f"requested physical DOF does not exist: {key}")
        record = self._records[key]
        if expected_owner is not None and record.owner != tuple(expected_owner):
            raise AssertionError(f"physical DOF owner mismatch: {key}")
        if expected_coordinate is not None and not np.allclose(
            record.coordinate, expected_coordinate, atol=1e-8, rtol=0.0
        ):
            raise AssertionError(f"physical DOF coordinate mismatch: {key}")
        return record.index

    def six_dof_port(self, prefix, *, expected_owner=None, expected_coordinate=None) -> list[int]:
        indices = [
            self.resolve(
                tuple(prefix) + (name,),
                expected_owner=expected_owner,
                expected_coordinate=expected_coordinate,
            )
            for name in DOF_NAMES
        ]
        records = [self._records[tuple(prefix) + (name,)] for name in DOF_NAMES]
        if len({record.owner for record in records}) != 1:
            raise AssertionError("six-DOF assembly mixes physical owners")
        if len({record.coordinate for record in records}) != 1:
            raise AssertionError("six-DOF assembly mixes physical ports")
        return indices

    def records(self) -> list[DOFRecord]:
        return sorted(self._records.values(), key=lambda record: record.index)


def active_vertical_rotation_names(values) -> tuple[str, ...]:
    """ModuPort vertical constitutive components are global RX/RY/RZ."""
    return tuple(name for name, value in zip(DOF_NAMES[3:], values[3:]) if float(value) != 0.0)


@dataclass
class LateSchur:
    final_indices: np.ndarray
    temporary_indices: np.ndarray
    K_ss: sparse.csc_matrix
    factorization: object
    recovery_matrix: sparse.csr_matrix
    fill_in: int
    diagnostics: dict

    def condense_load(self, load) -> np.ndarray:
        load = np.asarray(load, float)
        pr = load[self.final_indices]
        ps = load[self.temporary_indices]
        if not np.any(ps):
            return pr.copy()
        return pr - self.recovery_matrix.T @ (-ps)

    def recover(self, q_r, load=None) -> np.ndarray:
        q_r = np.asarray(q_r, float)
        ps = np.zeros(len(self.temporary_indices)) if load is None else np.asarray(load, float)[self.temporary_indices]
        q_s = self.factorization.solve(ps - self.K_ss @ np.zeros_like(ps))
        # recovery_matrix is -K_ss^-1 K_sr.
        q_s += self.recovery_matrix @ q_r
        q = np.zeros(len(self.final_indices) + len(self.temporary_indices))
        q[self.final_indices] = q_r
        q[self.temporary_indices] = q_s
        return q


def exact_sparse_late_schur(K, M, temporary_indices, *, zero_mass_tolerance=1e-14):
    K = sparse.csr_matrix(K)
    M = sparse.csr_matrix(M)
    temporary = np.asarray(sorted(set(map(int, temporary_indices))), int)
    temporary_set = set(map(int, temporary))
    final = np.asarray([i for i in range(K.shape[0]) if i not in temporary_set], int)
    if not len(temporary):
        return K, M, None
    Krr = K[final][:, final].tocsr()
    Krs = K[final][:, temporary].tocsr()
    Ksr = K[temporary][:, final].tocsr()
    Kss = K[temporary][:, temporary].tocsc()
    Mss = M[temporary][:, temporary]
    Mrs = M[final][:, temporary]
    mass_scale = max(float(np.max(np.abs(M.data))) if M.nnz else 0.0, 1.0)
    mass_error = max(
        float(np.max(np.abs(Mss.data))) if Mss.nnz else 0.0,
        float(np.max(np.abs(Mrs.data))) if Mrs.nnz else 0.0,
    )
    if mass_error > zero_mass_tolerance * mass_scale:
        raise RuntimeError(
            "temporary rotational DOFs have nonzero mass/coupling; exact dynamic reduction required"
        )

    lu = splu(Kss)
    ncomp, labels = connected_components(Kss, directed=False)
    corr_rows: list[int] = []
    corr_cols: list[int] = []
    corr_data: list[float] = []
    rec_rows: list[int] = []
    rec_cols: list[int] = []
    rec_data: list[float] = []
    before = set(zip(*Krr.nonzero()))
    for component in range(ncomp):
        si = np.where(labels == component)[0]
        ri = np.unique(Ksr[si].indices)
        if not len(ri):
            continue
        local_ss = Kss[si][:, si].toarray()
        local_sr = Ksr[si][:, ri].toarray()
        recovery = -np.linalg.solve(local_ss, local_sr)
        correction = -Krs[ri][:, si].toarray() @ recovery
        ii, jj = np.nonzero(correction)
        corr_rows.extend(ri[ii])
        corr_cols.extend(ri[jj])
        corr_data.extend(correction[ii, jj])
        ii, jj = np.nonzero(recovery)
        rec_rows.extend(si[ii])
        rec_cols.extend(ri[jj])
        rec_data.extend(recovery[ii, jj])
    correction = sparse.coo_matrix((corr_data, (corr_rows, corr_cols)), shape=Krr.shape).tocsr()
    Keff = (Krr - correction).tocsr()
    Keff.sum_duplicates()
    recovery = sparse.coo_matrix(
        (rec_data, (rec_rows, rec_cols)), shape=(len(temporary), len(final))
    ).tocsr()
    after = set(zip(*Keff.nonzero()))
    fill_in = len(after - before)
    diagnostics = {
        "temporary_dofs": len(temporary),
        "final_dofs": len(final),
        "K_ss_dimension": len(temporary),
        "K_ss_condition_estimate": float(np.linalg.cond(Kss.toarray())) if len(temporary) <= 500 else None,
        "schur_fill_in": fill_in,
        "augmented_nnz": K.nnz,
        "final_nnz": Keff.nnz,
        "augmented_density": K.nnz / (K.shape[0] ** 2),
        "final_density": Keff.nnz / (Keff.shape[0] ** 2),
        "mass_ss_rs_max": mass_error,
        "mass_temporary_zero": True,
        "symmetry_residual": float(sparse.linalg.norm(Keff - Keff.T) / max(sparse.linalg.norm(Keff), 1.0)),
    }
    return Keff, M[final][:, final].tocsr(), LateSchur(
        final, temporary, Kss, lu, recovery, fill_in, diagnostics
    )
