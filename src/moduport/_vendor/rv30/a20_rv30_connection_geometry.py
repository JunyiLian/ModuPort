"""Shared pure geometry for RV30 horizontal connections (N-mm)."""
from __future__ import annotations
import math
import numpy as np

def _half_size(section: dict, normal: np.ndarray) -> float:
    """Section half-size along the interface normal.

    RV30 maps section width to global X and depth to global Y for vertical
    columns.  The current square column is orientation invariant.
    """
    n=np.abs(normal)
    if n[0] >= n[1] and n[0] >= n[2]: return 0.5*float(section["width_mm"])
    if n[1] >= n[0] and n[1] >= n[2]: return 0.5*float(section["depth_mm"])
    raise ValueError("horizontal interface normal must lie in global XY")

def compute_horizontal_connection_geometry(column_I_center, column_J_center,
                                           column_I_section, column_J_section,
                                           interface_normal, clear_gap):
    ci=np.asarray(column_I_center,float);cj=np.asarray(column_J_center,float)
    n=np.asarray(interface_normal,float);nn=np.linalg.norm(n)
    if nn <= 0: raise ValueError("zero interface normal")
    n=n/nn
    if np.dot(cj-ci,n)<0:n=-n
    hi=_half_size(column_I_section,n);hj=_half_size(column_J_section,n)
    link_i=ci+n*hi;link_j=cj-n*hj;r=link_j-link_i
    tol=1e-8
    if not math.isclose(np.linalg.norm(link_i-ci),hi,rel_tol=0,abs_tol=tol):raise AssertionError("arm I QA")
    if not math.isclose(np.linalg.norm(cj-link_j),hj,rel_tol=0,abs_tol=tol):raise AssertionError("arm J QA")
    if not math.isclose(np.linalg.norm(r),float(clear_gap),rel_tol=0,abs_tol=tol):
        raise ValueError(f"centre/section/gap inconsistency: link={np.linalg.norm(r)}, clear_gap={clear_gap}")
    return {"arm_I_root":ci,"arm_I_tip":link_i,"link_I":link_i,
            "link_J":link_j,"arm_J_tip":link_j,"arm_J_root":cj,
            "arm_I_length":hi,"link_length":float(np.linalg.norm(r)),
            "arm_J_length":hj,"midpoint":0.5*(link_i+link_j),"r_IJ":r}
