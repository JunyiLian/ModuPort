"""Finite-port single-storey theory engine used by ``module_layout_surrogate``.

The engine keeps actual module frame topology, condenses only non-port DOFs,
and adds finite 6-DOF connections through B.T @ k_local @ B.  It deliberately
does not contain any SAP automation or layout-specific constants.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import math
from typing import Any, Dict, Iterable, Sequence

import numpy as np


@dataclass(frozen=True)
class ModuleSpec:
    module_id: int
    orientation: str
    x0: float
    y0: float
    width: float
    height: float
    @property
    def x1(self): return self.x0 + self.width
    @property
    def y1(self): return self.y0 + self.height
    @property
    def name(self): return f"{self.orientation}{self.module_id:02d}"


@dataclass(frozen=True)
class Interface:
    index: int; direction: str; module_a: int; module_b: int
    side_a: str; side_b: str; face_a: float; face_b: float; tangent: float
    endpoint_a: str; endpoint_b: str


@dataclass
class ModulePortModel:
    stiffness: np.ndarray; port: Dict[tuple, int]; coords: Dict[tuple, np.ndarray]
    raw_nodes: int; raw_dofs: int; internal_dofs: int; frames: int


@dataclass
class PortLevelStoreyModel:
    stiffness: np.ndarray; modules: list[ModuleSpec]; cores: list[ModulePortModel]
    offsets: list[int]; interfaces: list[Interface]; arm_dofs: list[tuple[int,int]]
    diagnostics: Dict[str, Any]


def _specs(layout, cfg):
    out=[]
    for p in layout:
        rs=[x[0] for x in p.cells]; cs=[x[1] for x in p.cells]
        w=cfg.module_long_outer if p.orientation == 'H' else cfg.module_short_outer
        h=cfg.module_short_outer if p.orientation == 'H' else cfg.module_long_outer
        # Centre each physical module in its one-by-two domino-cell envelope.
        # The cell pitch includes the clear gap, so lower-left anchoring creates
        # a spurious half-gap offset and destroys geometric mirror symmetry.
        envelope_w=(2 if p.orientation == 'H' else 1)*cfg.cell_pitch
        envelope_h=(1 if p.orientation == 'H' else 2)*cfg.cell_pitch
        x0=min(cs)*cfg.cell_pitch+(envelope_w-w)/2
        y0=min(rs)*cfg.cell_pitch+(envelope_h-h)/2
        out.append(ModuleSpec(p.module_id,p.orientation,x0,y0,w,h))
    # A3 parses the textual labels in lexical order.  Fix the block order here
    # as well so weak coupling terms reproduce deterministically bit-for-bit.
    return sorted(out, key=lambda s: s.name)


def _corner(sp, xs, ys, cfg):
    return np.array((sp.x0+cfg.column_half_mm if xs=='W' else sp.x1-cfg.column_half_mm,
                     sp.y0+cfg.column_half_mm if ys=='S' else sp.y1-cfg.column_half_mm),float)


def _extra_xyz(sp, side, tangent, z, cfg):
    if side=='W': return np.array((sp.x0+cfg.column_half_mm,tangent,z))
    if side=='E': return np.array((sp.x1-cfg.column_half_mm,tangent,z))
    if side=='S': return np.array((tangent,sp.y0+cfg.column_half_mm,z))
    return np.array((tangent,sp.y1-cfg.column_half_mm,z))


def _limits(sp, direction, cfg):
    return (sp.y0+cfg.column_half_mm,sp.y1-cfg.column_half_mm) if direction=='X' else (sp.x0+cfg.column_half_mm,sp.x1-cfg.column_half_mm)


def identify_layout_interfaces(layout, geometry=None, config=None):
    """Identify only side-sharing module interfaces; diagonal contacts never enter."""
    cfg=config or geometry
    specs=_specs(layout,cfg); out=[]; tol=1e-6
    for i,first in enumerate(specs):
        for second in specs[i+1:]:
            candidates=[]
            if math.isclose(first.x1+cfg.module_clear_gap,second.x0,abs_tol=tol): candidates.append(('X',first,second,'E','W',first.x1,second.x0))
            elif math.isclose(second.x1+cfg.module_clear_gap,first.x0,abs_tol=tol): candidates.append(('X',second,first,'E','W',second.x1,first.x0))
            if math.isclose(first.y1+cfg.module_clear_gap,second.y0,abs_tol=tol): candidates.append(('Y',first,second,'N','S',first.y1,second.y0))
            elif math.isclose(second.y1+cfg.module_clear_gap,first.y0,abs_tol=tol): candidates.append(('Y',second,first,'N','S',second.y1,first.y0))
            for d,a,b,sa,sb,fa,fb in candidates:
                a0,a1=_limits(a,d,cfg); b0,b1=_limits(b,d,cfg)
                if min(a1,b1)<=max(a0,b0)+tol: continue
                for t in sorted({a0,a1,b0,b1}):
                    ia=a0-tol<=t<=a1+tol; ib=b0-tol<=t<=b1+tol
                    ca=math.isclose(t,a0,abs_tol=tol) or math.isclose(t,a1,abs_tol=tol)
                    cb=math.isclose(t,b0,abs_tol=tol) or math.isclose(t,b1,abs_tol=tol)
                    if ia and ib and (ca or cb): out.append(Interface(len(out)+1,d,a.module_id,b.module_id,sa,sb,fa,fb,t,'CORNER' if ca else 'BEAM','CORNER' if cb else 'BEAM'))
    return out


def _extras(interfaces):
    result=defaultdict(set)
    for c in interfaces:
        if c.endpoint_a=='BEAM': result[(c.module_a,c.side_a)].add(c.tangent)
        if c.endpoint_b=='BEAM': result[(c.module_b,c.side_b)].add(c.tangent)
    return result


def _section_for_side(sp, level, side, sections):
    long=(sp.width if side in ('S','N') else sp.height)>4000.
    return sections[f"{'floor' if level=='FLOOR' else 'ceiling'}_{'long' if long else 'short'}"]


def build_module_port_stiffness(orientation, geometry=None, sections=None, material=None, *, spec=None, extras=None, config=None):
    """Build H/V frame topology and statically condense non-port rotations."""
    cfg=config or geometry
    if spec is None:
        spec=ModuleSpec(1,orientation,0.,0.,cfg.module_long_outer if orientation=='H' else cfg.module_short_outer,cfg.module_short_outer if orientation=='H' else cfg.module_long_outer)
    extras=extras or {}; sections=sections or cfg.sections(); nodes=[]; ids={}; coords={}
    def add(k,xyz): ids[k]=len(nodes); coords[k]=np.asarray(xyz,float); nodes.append(coords[k])
    for lev,z in (('BOT',-cfg.column_end_offset),('FLOOR',0.),('CEIL',cfg.clear_storey_height),('TOP',cfg.clear_storey_height+cfg.column_end_offset)):
        for xs in ('W','E'):
            for ys in ('S','N'): add((lev,'C',xs,ys),tuple(_corner(spec,xs,ys,cfg))+(z,))
    for side,tans in extras.items():
        for t in sorted(tans):
            for lev,z in (('FLOOR',0.),('CEIL',cfg.clear_storey_height)): add((lev,'B',side,round(t,6)),_extra_xyz(spec,side,t,z,cfg))
    frames=[]
    for xs in ('W','E'):
        for ys in ('S','N'):
            for a,b in (('BOT','FLOOR'),('FLOOR','CEIL'),('CEIL','TOP')): frames.append((ids[(a,'C',xs,ys)],ids[(b,'C',xs,ys)],sections['column']))
    sides=(('S',('W','S'),('E','S')),('E',('E','S'),('E','N')),('N',('W','N'),('E','N')),('W',('W','S'),('W','N')))
    for lev in ('FLOOR','CEIL'):
        for side,a,b in sides:
            q=[ids[(lev,'C',*a)]]+[ids[(lev,'B',side,round(t,6))] for t in sorted(extras.get(side,()))]+[ids[(lev,'C',*b)]]
            frames += [(i,j,_section_for_side(spec,lev,side,sections)) for i,j in zip(q,q[1:])]
    # module uses same beam function as legacy script (passed through config owner)
    beam=cfg._beam_function
    K=np.zeros((6*len(nodes),6*len(nodes)))
    for i,j,s in frames:
        ke=beam(nodes[i],nodes[j],s); d=list(range(6*i,6*i+6))+list(range(6*j,6*j+6)); K[np.ix_(d,d)]+=ke
    keep=[]; port={}
    for lev in ('BOT','TOP'):
        for xs in ('W','E'):
            for ys in ('S','N'):
                for d in range(3): port[(lev,'C',xs,ys,d)]=len(keep); keep.append(6*ids[(lev,'C',xs,ys)]+d)
    for lev in ('FLOOR','CEIL'):
        for key,n in ids.items():
            if key[0]==lev:
                for d in range(6): port[key+(d,)]=len(keep); keep.append(6*n+d)
    inn=np.array([i for i in range(K.shape[0]) if i not in set(keep)],int); pp=K[np.ix_(keep,keep)]; pi=K[np.ix_(keep,inn)]
    kp=pp-pi@np.linalg.solve(K[np.ix_(inn,inn)],pi.T)
    return ModulePortModel(kp,port,coords,len(nodes),6*len(nodes),len(inn),len(frames))


def connection_local_matrix(connection_property): return connection_property.matrix()


def connection_transformation(interface):
    """6x6 global-to-local transform, including rotations, from SAP A3 axes."""
    q=np.array(((1,0,0),(0,0,1),(0,-1,0)),float).T if interface.direction=='X' else np.array(((0,1,0),(0,0,1),(1,0,0)),float).T
    z=np.zeros((6,6)); z[:3,:3]=q.T; z[3:,3:]=q.T; return z


def assemble_finite_connection(K_global, interface, connection_property, dof_map, a_dof=None, b_dof=None):
    """Add a finite 6DOF spring: B.T @ k_local @ B (no direct DOF merging)."""
    a,b=(a_dof,b_dof) if a_dof is not None else (dof_map[interface.module_a],dof_map[interface.module_b])
    B=np.zeros((6,K_global.shape[0])); T=connection_transformation(interface)
    B[:,a:a+6]=T; B[:,b:b+6]=-T; K_global += B.T@connection_local_matrix(connection_property)@B
    return B


def _corner_port(core,sp,side,tan,endpoint,lev,cfg):
    if endpoint=='BEAM':
        key=(lev,'B',side,round(tan,6)); return core.port[key+(0,)],core.coords[key]
    if side in ('W','E'): ys='S' if math.isclose(tan,sp.y0+cfg.column_half_mm,abs_tol=1e-6) else 'N'; key=(lev,'C',side,ys)
    else: xs='W' if math.isclose(tan,sp.x0+cfg.column_half_mm,abs_tol=1e-6) else 'E'; key=(lev,'C',xs,side)
    return core.port[key+(0,)],core.coords[key]


def _face(c,a,lev,cfg):
    z=0. if lev=='FLOOR' else cfg.clear_storey_height; face=c.face_a if a else c.face_b
    return np.array((face,c.tangent,z) if c.direction=='X' else (c.tangent,face,z),float)


def _property_for(c,lev,cfg):
    keys=((f'{c.module_a:02d}',f'{c.module_b:02d}',lev),(c.module_a,c.module_b,lev),(f'{c.module_a:02d}',f'{c.module_b:02d}'),(c.module_a,c.module_b))
    for k in keys:
        if k in cfg.connection_overrides: return cfg.connection_overrides[k]
    return cfg.horizontal_connection


def assemble_single_storey_port_model(layout, config):
    cfg=config
    if not hasattr(cfg, '_beam_function'):
        from ._module_layout import beam3d_global_stiffness
        cfg._beam_function=beam3d_global_stiffness
    specs=_specs(layout,cfg); interfaces=identify_layout_interfaces(layout,config=cfg); extras=_extras(interfaces)
    cores=[]
    for sp in specs: cores.append(build_module_port_stiffness(sp.orientation,config=cfg,spec=sp,extras={side:t for (mid,side),t in extras.items() if mid==sp.module_id}))
    offsets=[]; n=0
    for core in cores: offsets.append(n); n+=core.stiffness.shape[0]
    N=n+6*len(interfaces)*4; K=np.zeros((N,N))
    for off,core in zip(offsets,cores): K[off:off+len(core.stiffness),off:off+len(core.stiffness)]=core.stiffness
    from ._module_layout import Section
    armsec=Section(2e6,2e6/(2*1.3),250000.,500.**4/12,500.**4/12,.1406*500.**4); byid={s.module_id:i for i,s in enumerate(specs)}; arm=0; arm_pairs=[]
    for c in interfaces:
        for lev in ('FLOOR','CEIL'):
            ia,ib=byid[c.module_a],byid[c.module_b]; la,xa=_corner_port(cores[ia],specs[ia],c.side_a,c.tangent,c.endpoint_a,lev,cfg); lb,xb=_corner_port(cores[ib],specs[ib],c.side_b,c.tangent,c.endpoint_b,lev,cfg)
            aa=n+6*arm; arm+=1; ab=n+6*arm; arm+=1; arm_pairs.append((aa,ab)); ca=offsets[ia]+la; cb=offsets[ib]+lb
            for x0,x1,co,ao in ((xa,_face(c,True,lev,cfg),ca,aa),(xb,_face(c,False,lev,cfg),cb,ab)):
                ke=cfg._beam_function(x0,x1,armsec); ds=list(range(co,co+6))+list(range(ao,ao+6)); K[np.ix_(ds,ds)]+=ke
            assemble_finite_connection(K,c,_property_for(c,lev,cfg),{},aa,ab)
    types=Counter(f'{c.endpoint_a}-{c.endpoint_b}' for c in interfaces)
    d={'interfaces':len(interfaces),'interface_types':dict(types),'links':2*len(interfaces),'module_port_dims':[len(x.stiffness) for x in cores],'raw_dofs':sum(x.raw_dofs for x in cores),'internal_dofs':sum(x.internal_dofs for x in cores),'block_port_dofs':n,'arm_frames':arm}
    return PortLevelStoreyModel(K,specs,cores,offsets,interfaces,arm_pairs,d)


def condense_storey_to_3x3(port_model, reference_point=None):
    if reference_point is None:
        raise ValueError("reference_point is required; pass the layout geometric centre explicitly")
    K=port_model.stiffness; xref,yref=reference_point; lower=[]; upper=[]; R=np.zeros((K.shape[0],3))
    for sp,core,off in zip(port_model.modules,port_model.cores,port_model.offsets):
        for xs in ('W','E'):
            for ys in ('S','N'):
                for d in range(3): lower.append(off+core.port[('BOT','C',xs,ys,d)])
                x,y,_=core.coords[('TOP','C',xs,ys)]
                ux=off+core.port[('TOP','C',xs,ys,0)]; uy=off+core.port[('TOP','C',xs,ys,1)]; uz=off+core.port[('TOP','C',xs,ys,2)]; upper += [ux,uy,uz]; R[ux]=(1,0,-(y-yref)); R[uy]=(0,1,x-xref)
    free=np.array([i for i in range(len(K)) if i not in set(lower)|set(upper)],int); kdf=R.T@K[:,free]; ks=R.T@K@R-kdf@np.linalg.solve(K[np.ix_(free,free)],kdf.T)
    port_model.diagnostics['final_free_dofs']=len(free); return ks


def compute_layout_storey_stiffness(layout, config, reference_point=None, connection_model='finite_port'):
    if reference_point is None:
        raise ValueError("reference_point is required; pass the layout geometric centre explicitly")
    if connection_model=='legacy_union': return config._legacy_condense(layout,config)
    if connection_model!='finite_port': raise ValueError(f'unknown connection_model {connection_model!r}')
    pm=assemble_single_storey_port_model(layout,config); ks=condense_storey_to_3x3(pm,reference_point); ev=np.linalg.eigvalsh(.5*(ks+ks.T)); pm.diagnostics.update({'symmetry_error':float(np.linalg.norm(ks-ks.T)/max(np.linalg.norm(ks),1.)),'negative_eigenvalues':int(np.count_nonzero(ev<-max(abs(ev).max(),1)*1e-10))}); return ks,pm.diagnostics


@dataclass
class MultiStoreyPortModel:
    K_full: np.ndarray; dof_map: dict; fixed_dofs: np.ndarray; free_dofs: np.ndarray
    storey_node_groups: dict; module_port_groups: dict; horizontal_interfaces: list
    vertical_interfaces: list; coordinates: np.ndarray

def global_port_dof(story_offset, module_offset, local_port_dof):
    """Unique multistorey port index: story + module-block + local port."""
    return story_offset + module_offset + local_port_dof

def build_multistorey_port_model(layout, config, storeys=3):
    """Full free port system; no floor-rigid kinematic condensation."""
    models=[assemble_single_storey_port_model(layout,config) for _ in range(storeys)]
    offsets=[]; n=0
    for pm in models: offsets.append(n); n+=len(pm.stiffness)
    N=n; K=np.zeros((N,N))
    for off,pm in zip(offsets,models): K[off:off+len(pm.stiffness),off:off+len(pm.stiffness)]=pm.stiffness
    groups={}; vertical=[]; fixed=[]; coords=[]; dofmap={}
    for s,pm in enumerate(models):
        group=[]
        for mi,(core,mo) in enumerate(zip(pm.cores,pm.offsets)):
            for key,local in core.port.items(): dofmap[(s,mi,key)]=global_port_dof(offsets[s],mo,local)
            for xs in ('W','E'):
                for ys in ('S','N'):
                    d=global_port_dof(offsets[s],mo,core.port[('TOP','C',xs,ys,0)]); group.append(d); coords.append(core.coords[('TOP','C',xs,ys)])
                    if s==0: fixed += [global_port_dof(offsets[s],mo,core.port[('BOT','C',xs,ys,dof)]) for dof in range(3)]
        groups[s]=group
    # Add zero-length vertical links between independent TOP/BOT column ports.
    for s in range(storeys-1):
        low,up=models[s],models[s+1]
        for mi,(cl,cu) in enumerate(zip(low.cores,up.cores)):
            for xs in ('W','E'):
                for ys in ('S','N'):
                    a=global_port_dof(offsets[s],low.offsets[mi],cl.port[('TOP','C',xs,ys,0)]); b=global_port_dof(offsets[s+1],up.offsets[mi],cu.port[('BOT','C',xs,ys,0)])
                    # Only the retained translational TOP/BOT port components
                    # participate; the audited vertical rotational stiffnesses are zero.
                    B=np.zeros((3,N)); B[:,a:a+3]=np.eye(3); B[:,b:b+3]=-np.eye(3); K+=B.T@config.vertical_connection.matrix()[:3,:3]@B; vertical.append((s,mi,xs+ys,a,b))
    free=np.array([i for i in range(N) if i not in set(fixed)],int)
    return MultiStoreyPortModel(K,dofmap,np.array(fixed,int),free,groups,{(s,mi):list(range(offsets[s]+mo,offsets[s]+mo+len(c.stiffness))) for s,p in enumerate(models) for mi,(c,mo) in enumerate(zip(p.cores,p.offsets))},[p.interfaces for p in models],vertical,np.asarray(coords))

def solve_multistorey_port_response(model, nodal_loads, constraints=None):
    fixed=set(model.fixed_dofs); fixed.update(constraints or ()); free=np.array([i for i in range(len(model.K_full)) if i not in fixed],int); u=np.zeros(len(model.K_full)); u[free]=np.linalg.solve(model.K_full[np.ix_(free,free)],np.asarray(nodal_loads)[free]); return u

def fit_storey_generalized_response(displacements,node_indices,coordinates,reference_point=None):
    if reference_point is None:
        raise ValueError("reference_point is required; pass the layout geometric centre explicitly")
    x0,y0=reference_point; A=[];b=[]
    for d,c in zip(node_indices,coordinates): A += [[1,0,-(c[1]-y0)],[0,1,c[0]-x0]]; b += [displacements[d],displacements[d+1]]
    q=np.linalg.lstsq(A,b,rcond=None)[0]; residual=np.asarray(A)@q-np.asarray(b);return {'ux':float(q[0]),'uy':float(q[1]),'theta':float(q[2]),'rms':float(np.sqrt(np.mean(residual**2))),'normalized':float(np.linalg.norm(residual)/max(np.linalg.norm(b),1e-30)),'node_count':len(node_indices)}

def compute_three_storey_port_stiffness(layout, config, reference_point=None, storeys=3):
    """Legacy rigid-floor kinematic condensation, retained only for diagnosis."""
    if reference_point is None:
        raise ValueError("reference_point is required; pass the layout geometric centre explicitly")
    xref,yref=reference_point
    model=build_multistorey_port_model(layout,config,storeys); K=model.K_full; models=[assemble_single_storey_port_model(layout,config) for _ in range(storeys)]; offsets=[]; n=0
    for pm in models: offsets.append(n); n+=len(pm.stiffness)
    N=len(K); R=np.zeros((N,3*storeys)); constrained=list(model.fixed_dofs)
    for s,pm in enumerate(models):
        for sp,core,off0 in zip(pm.modules,pm.cores,pm.offsets):
            for xs in ('W','E'):
                for ys in ('S','N'):
                    if s==0:
                        constrained += [offsets[s]+off0+core.port[('BOT','C',xs,ys,d)] for d in range(3)]
                    x,y,_=core.coords[('TOP','C',xs,ys)]; a=offsets[s]+off0
                    ix=a+core.port[('TOP','C',xs,ys,0)]; iy=a+core.port[('TOP','C',xs,ys,1)]; iz=a+core.port[('TOP','C',xs,ys,2)]
                    constrained += [ix,iy,iz]; R[ix,3*s:3*s+3]=(1,0,-(y-yref)); R[iy,3*s:3*s+3]=(0,1,x-xref)
    free=np.array([i for i in range(N) if i not in set(constrained)],int); kdf=R.T@K[:,free]; return R.T@K@R-kdf@np.linalg.solve(K[np.ix_(free,free)],kdf.T)


def build_six_dof_pure_port_model(layout, config, storeys=3, base_boundary="fixed_translation"):
    """Formal A10 pure-port multistorey model.

    Uses A7's six-DOF structural FLOOR/CEIL ports, with virtual BOT/TOP
    points related by rigid offsets; no explicit 114.3-mm arm or 78.5-mm
    end-column Frame is assembled.  ``base_boundary`` is a theory input:
    ``fixed_translation``, ``fixed_6dof`` or an iterable of six booleans.
    """
    from importlib.util import spec_from_file_location, module_from_spec
    from pathlib import Path
    import sys
    path=Path(__file__).with_name("diagnose_A7_six_dof_boundary_ports.py")
    spec=spec_from_file_location("_a10_pure_port_core",path); core=module_from_spec(spec);sys.modules[spec.name]=core;spec.loader.exec_module(core)
    if storeys != 3:
        raise ValueError("A10 formal bridge currently validates the audited three-storey path only")
    K,fixed,groups,coordinates,vertical,storeys_data=core.multi(layout,config)
    if base_boundary == "fixed_translation":
        pass
    elif base_boundary == "fixed_6dof" or base_boundary == "fixed_6dof_physical_base":
        extra=list(fixed)
        for co,off in zip(storeys_data[0][2],storeys_data[0][3]):
            for xs in ("W","E"):
                for ys in ("S","N"):
                    d=off+co.port[("FLOOR","C",xs,ys)];extra += list(range(d+3,d+6))
        fixed=np.asarray(sorted(set(extra)),int)
    else:
        flags=tuple(base_boundary)
        if len(flags)!=6: raise ValueError("custom base boundary requires six booleans")
        fixed=[]
        for co,off in zip(storeys_data[0][2],storeys_data[0][3]):
            for xs in ("W","E"):
                for ys in ("S","N"):
                    d=off+co.port[("FLOOR","C",xs,ys)];fixed += [d+i for i,x in enumerate(flags) if x]
        fixed=np.asarray(sorted(set(fixed)),int)
    return {"K_full":K,"fixed_dofs":fixed,"storey_node_groups":groups,"coordinates":coordinates,"vertical_interfaces":vertical,"conceptual_port_dofs_per_module":96,"independent_structural_port_dofs_per_module":48,"base_boundary":base_boundary}


def solve_six_dof_pure_port_model(model, nodal_loads):
    K=model["K_full"]; fixed=set(model["fixed_dofs"]);free=np.asarray([i for i in range(len(K)) if i not in fixed],int);u=np.zeros(len(K));u[free]=np.linalg.solve(K[np.ix_(free,free)],np.asarray(nodal_loads)[free]);return u
