"""RV30 config adapter over the frozen ModuPort internal kernel."""
from __future__ import annotations
import json, sys
import numpy as np
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT=Path(r"E:\text\SCI\SCI-layout arrangement\Sap2000-api")
OUTPUT_ROOT=PROJECT_ROOT/"a20_validation"
MODUPORT_ROOT=Path(r"E:\text\SCI\SCI-layout arrangement\codex\封装\ModuPort_Eight_Node_V1")
if str(MODUPORT_ROOT) not in sys.path:sys.path.insert(0,str(MODUPORT_ROOT))
from mscsolver._module_layout import ConnectionStiffness,ModelConfig,Section,beam3d_global_stiffness
from mscsolver import _kernel_v1 as kernel
from a20_rv30_connection_geometry import compute_horizontal_connection_geometry
import a20_rv30_geometry_kernel as rvkernel

@dataclass
class RV30Config(ModelConfig):
    rv30_sections:dict[str,Section]|None=None
    reinforced_zone:dict[str,float]|None=None
    arm:dict[str,float]|None=None
    loads:dict[str,list[float]]|None=None
    boundary:dict[str,Any]|None=None
    def sections(self):return self.rv30_sections if self.rv30_sections is not None else super().sections()

def _section(v,E,G):return Section(E,G,float(v["A_mm2"]),float(v["Iy_mm4"]),float(v["Iz_mm4"]),float(v["J_mm4"]))
def _link(v,name):
    k=float(v.get("k_trans_N_mm",v.get("horizontal_k_link_N_mm",1e8)));kr=float(v.get("k_rot_N_mm_rad",v.get("krot_N_mm_rad",0)))
    return ConnectionStiffness(name,k,k,k,kr,kr,kr)
def build_config(data:dict[str,Any])->RV30Config:
    g=data["module_geometry"];m=data["material"];E=float(m["E_N_mm2"]);G=float(m["G_N_mm2"])
    cfg=RV30Config(grid_rows=int(data["grid_rows"]),grid_cols=int(data["grid_cols"]),storeys=int(data["storey_count"]),module_long_outer=float(g["long_outer_mm"]),module_short_outer=float(g["short_outer_mm"]),module_long_centerline=float(g["long_centerline_mm"]),module_short_centerline=float(g["short_centerline_mm"]),module_clear_gap=float(g["clear_gap_mm"]),clear_storey_height=float(g["clear_storey_height_mm"]),column_end_offset=float(g["column_end_offset_mm"]),steel_E=E,steel_nu=E/(2*G)-1,steel_density_kg_m3=float(m.get("density_kg_m3",7850)),horizontal_connection=_link(data["horizontal_link"],"RV30_HORIZONTAL"),vertical_connection=_link(data["vertical_link"],"RV30_VERTICAL"),reinforced_zone={k:float(v) for k,v in data["reinforced_zone"].items()},arm={k:float(v) for k,v in data["arm"].items()},loads={k:[float(x) for x in v] for k,v in data["loads"].items()},boundary=dict(data["boundary"]))
    cfg.rv30_sections={n:_section(v,E,G) for n,v in data["sections"].items()};cfg._beam_function=beam3d_global_stiffness
    # The frozen RV001 V1 assembly receives reference-port DOFs.  Preserve its
    # H(r_IJ) path by default; alternative modes are audit-only and opt-in.
    cfg.horizontal_connection_kinematics_mode=data.get("connection_kinematics_mode","REFERENCE_PORT_DOF")
    if cfg.horizontal_connection_kinematics_mode not in {"REFERENCE_PORT_DOF","ACTUAL_LINK_ENDPOINT_DOF","DOUBLE_ENDPOINT_TRANSPORT"}:
        raise ValueError(f"unsupported horizontal connection kinematics: {cfg.horizontal_connection_kinematics_mode}")
    need={"column","floor_long","floor_short","ceiling_long","ceiling_short"}
    if set(cfg.rv30_sections)!=need:raise ValueError(f"section set mismatch: {set(cfg.rv30_sections)^need}")
    return cfg
def solve_rv30_config(path:str|Path):
    p=Path(path);data=json.loads(p.read_text(encoding="utf-8"));cfg=build_config(data)
    if cfg.boundary.get("mode")!="B0":raise ValueError("only B0 is supported")
    case={"case_id":data["sample_id"],"grid_rows":cfg.grid_rows,"grid_cols":cfg.grid_cols,"storey_count":cfg.storeys,"storey_layouts":data["storey_layouts"],"reference_point":data["reference_point"]}
    mode=kernel.IN_PLANE_RIGID_BODY if cfg.boundary.get("top_in_plane_rigid") else kernel.FREE_BARE_FRAME
    cfg.reinforced_zone_active=bool(data.get("reinforced_zone_active",False))
    result=rvkernel.case_result(case,config=cfg,boundary_mode=mode)
    # Shared-geometry contract: V1 faces are column outer faces and their chord
    # must equal clear_gap.  The core remains frozen; this is an adapter QA.
    sec=data["sections"]["column"]
    for q in result["model"].horizontal_links:
        li=np.asarray(q["x_i"],float);lj=np.asarray(q["x_j"],float);n=(lj-li)/np.linalg.norm(lj-li)
        half=0.5*(float(sec["width_mm"]) if abs(n[0])>=abs(n[1]) else float(sec["depth_mm"]))
        geo=compute_horizontal_connection_geometry(li-n*half,lj+n*half,sec,sec,n,data["module_geometry"]["clear_gap_mm"])
        if not np.allclose(geo["link_I"],li) or not np.allclose(geo["link_J"],lj):raise ValueError(f"shared horizontal geometry mismatch: {q['id']}")
    return {"result":result,"config":cfg,"input":data}
