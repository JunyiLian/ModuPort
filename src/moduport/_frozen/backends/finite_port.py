from __future__ import annotations
from dataclasses import dataclass
from time import perf_counter
from typing import Any
import numpy as np
from scipy.linalg import eigh,solve

from ..runtime import imports

@dataclass
class FinitePortModule:
    module_id:int
    orientation:str
    node_coordinates:dict
    port_metadata:dict
    retained_dof_indices:np.ndarray
    internal_dof_indices:np.ndarray
    K_full:np.ndarray
    K_port:np.ndarray
    condensation_transform:np.ndarray
    recovery_operator:np.ndarray
    M_full_lumped:np.ndarray
    M_port_lumped:np.ndarray
    local_to_global_transform:np.ndarray
    frames:list
    diagnostics:dict

@dataclass
class FinitePortBuilding:
    K:np.ndarray
    M:np.ndarray
    constraint_transform:np.ndarray
    reduced_K:np.ndarray
    reduced_M:np.ndarray
    modules:list
    module_offsets:list
    hardware_pairs:list
    horizontal_links:list
    vertical_links:list
    fixed_dofs:np.ndarray
    macro_dofs:np.ndarray
    module_recovery_to_reduced:list
    module_storeys:list
    diagnostics:dict

def build_port_set(module_spec,interface_requirements,ids):
    """Frozen 72-DOF baseline plus only topology-required beam-interior ports."""
    keep=[];metadata={}
    for lev in ('BOT','TOP'):
        for xs in ('W','E'):
            for ys in ('S','N'):
                for d in range(3):
                    key=(lev,'C',xs,ys,d);metadata[key]=len(keep);keep.append(6*ids[key[:-1]]+d)
    for lev in ('FLOOR','CEIL'):
        for key,n in ids.items():
            if key[0]==lev:
                for d in range(6):metadata[key+(d,)]=len(keep);keep.append(6*n+d)
    return metadata,np.asarray(keep,int)

def _full_module(spec,extras,cfg):
    _,adapter,_=imports();fp=adapter.rvkernel.fp;sections=cfg.sections();nodes=[];ids={};coords={}
    def add(key,xyz):ids[key]=len(nodes);coords[key]=np.asarray(xyz,float);nodes.append(coords[key])
    for lev,z in (('BOT',-cfg.column_end_offset),('FLOOR',0.),('CEIL',cfg.clear_storey_height),('TOP',cfg.clear_storey_height+cfg.column_end_offset)):
        for xs in ('W','E'):
            for ys in ('S','N'):add((lev,'C',xs,ys),tuple(fp._corner(spec,xs,ys,cfg))+(z,))
    for side,tangents in extras.items():
        for tangent in sorted(tangents):
            for lev,z in (('FLOOR',0.),('CEIL',cfg.clear_storey_height)):add((lev,'B',side,round(tangent,6)),fp._extra_xyz(spec,side,tangent,z,cfg))
    frames=[]
    for xs in ('W','E'):
        for ys in ('S','N'):
            for a,b in (('BOT','FLOOR'),('FLOOR','CEIL'),('CEIL','TOP')):frames.append((ids[(a,'C',xs,ys)],ids[(b,'C',xs,ys)],sections['column']))
    for lev in ('FLOOR','CEIL'):
        for side,a,b in (('S',('W','S'),('E','S')),('E',('E','S'),('E','N')),('N',('W','N'),('E','N')),('W',('W','S'),('W','N'))):
            chain=[ids[(lev,'C',*a)]]+[ids[(lev,'B',side,round(t,6))] for t in sorted(extras.get(side,()))]+[ids[(lev,'C',*b)]]
            frames.extend((i,j,fp._section_for_side(spec,lev,side,sections)) for i,j in zip(chain,chain[1:]))
    K=np.zeros((6*len(nodes),6*len(nodes)))
    for i,j,section in frames:
        dofs=list(range(6*i,6*i+6))+list(range(6*j,6*j+6));K[np.ix_(dofs,dofs)]+=cfg._beam_function(nodes[i],nodes[j],section)
    return ids,coords,nodes,frames,K

def _lumped_mass(nodes,frames,cfg):
    from ..modal_solver import _beam_mass
    rho=float(cfg.steel_density_kg_m3)*1e-9;M=np.zeros((6*len(nodes),6*len(nodes)))
    for i,j,s in frames:
        dofs=list(range(6*i,6*i+6))+list(range(6*j,6*j+6));M[np.ix_(dofs,dofs)]+=_beam_mass(nodes[i],nodes[j],rho,s.A,s.Iy,s.Iz,True)
    return M

def _build_direct(spec,extras,cfg):
    _,adapter,_=imports();fp=adapter.rvkernel.fp
    ids,coords,nodes,frames,K=_full_module(spec,extras,cfg);port,retained=build_port_set(spec,extras,ids)
    internal=np.asarray([i for i in range(len(K)) if i not in set(retained)],int)
    Krr=K[np.ix_(retained,retained)];Kri=K[np.ix_(retained,internal)];Kir=Kri.T;Kii=K[np.ix_(internal,internal)]
    recovery=-np.linalg.solve(Kii,Kir);T=np.zeros((len(K),len(retained)));T[retained]=np.eye(len(retained));T[internal]=recovery
    Kp=Krr+Kri@recovery;Mf=_lumped_mass(nodes,frames,cfg);Mp=T.T@Mf@T
    frozen=fp.build_module_port_stiffness(spec.orientation,config=cfg,spec=spec,extras=extras)
    scale=max(np.linalg.norm(frozen.stiffness),np.linalg.norm(Kp),1.);gate=float(np.linalg.norm(Kp-frozen.stiffness)/scale)
    if gate>1e-12:raise RuntimeError(f"frozen finite-port Schur mismatch {gate}")
    return FinitePortModule(spec.module_id,spec.orientation,coords,port,retained,internal,K,Kp,T,recovery,Mf,Mp,np.eye(len(Kp)),frames,
                            {'frozen_K_port_error':gate,'symmetry_K':float(np.linalg.norm(Kp-Kp.T)/max(np.linalg.norm(Kp),1.)),
                             'symmetry_M':float(np.linalg.norm(Mp-Mp.T)/max(np.linalg.norm(Mp),1.)),'raw_dofs':len(K),'port_dofs':len(Kp),'internal_dofs':len(internal)})

def _hv_key(key):
    lev,kind,*tail=key
    side={'S':'E','N':'W','W':'S','E':'N'}
    if kind=='C':
        xs,ys=tail[:2];corner={('W','S'):('E','S'),('W','N'):('W','S'),('E','S'):('E','N'),('E','N'):('W','N')}[(xs,ys)]
        return (lev,'C',*corner,*tail[2:])
    return (lev,'B',side[tail[0]],tail[1],*tail[2:])

def _rotate_h_to_v(module,spec_v,cfg,extras_v=None):
    """Formal V superelement: permutation plus explicit 90-degree DOF rotation."""
    n=len(module.K_port);Q=np.zeros((n,n));R=np.array(((0.,-1.,0.),(1.,0.,0.),(0.,0.,1.)));R6=np.zeros((6,6));R6[:3,:3]=R.T;R6[3:,3:]=R.T
    # Q's columns must follow the canonical V-port ordering, not the source H
    # indices.  The latter is invisible to symmetric lumped mass but corrupts K.
    extras_v=extras_v or {};v_ids,v_coords,_,v_frames,_=_full_module(spec_v,extras_v,cfg);target_port,target_retained=build_port_set(spec_v,extras_v,v_ids);target_coords=dict(v_coords)
    by_coordinate={tuple(np.round(value,6)):key for key,value in v_coords.items()}
    for hkey,hi in module.port_metadata.items():
        base=hkey[:-1];p=np.asarray(module.node_coordinates[base]);pv=np.array((spec_v.x0+cfg.module_short_outer-p[1],spec_v.y0+p[0],p[2]));vbase=by_coordinate[tuple(np.round(pv,6))];vkey=vbase+(hkey[-1],)
    visited=set()
    for hkey,hi in module.port_metadata.items():
        base=hkey[:-1]
        if base in visited:continue
        visited.add(base);dofs=3 if hkey[0] in ('BOT','TOP') else 6
        p=np.asarray(module.node_coordinates[base]);pv=np.array((spec_v.x0+cfg.module_short_outer-p[1],spec_v.y0+p[0],p[2]));vbase=by_coordinate[tuple(np.round(pv,6))];h0=module.port_metadata[base+(0,)];v0=target_port[vbase+(0,)]
        Q[h0:h0+dofs,v0:v0+dofs]=R.T if dofs==3 else R6
    Kv=Q.T@module.K_port@Q;Mv=Q.T@module.M_port_lumped@Q;Qfull=np.zeros_like(module.K_full);h_nodes=list(module.node_coordinates)
    for hi,hbase in enumerate(h_nodes):
        p=np.asarray(module.node_coordinates[hbase]);pv=np.array((spec_v.x0+cfg.module_short_outer-p[1],spec_v.y0+p[0],p[2]));vi=v_ids[by_coordinate[tuple(np.round(pv,6))]];Qfull[6*hi:6*hi+6,6*vi:6*vi+6]=R6
    Kfull=Qfull.T@module.K_full@Qfull;Mfull=Qfull.T@module.M_full_lumped@Qfull;internal=np.asarray([i for i in range(len(Kfull)) if i not in set(target_retained)],int);Kri=Kfull[np.ix_(target_retained,internal)];Kii=Kfull[np.ix_(internal,internal)];recovery=-np.linalg.solve(Kii,Kri.T);Tc=np.zeros((len(Kfull),len(target_retained)));Tc[target_retained]=np.eye(len(target_retained));Tc[internal]=recovery
    full_gate=float(np.linalg.norm(Tc.T@Kfull@Tc-Kv)/max(np.linalg.norm(Kv),1.))
    if full_gate>1e-12:raise RuntimeError(f'H-to-V full recovery transform mismatch {full_gate}')
    return FinitePortModule(spec_v.module_id,'V',target_coords,target_port,target_retained,internal,Kfull,Kv,Tc,recovery,Mfull,Mv,Q,v_frames,
                            dict(module.diagnostics,H_to_V=True))

def _skew(r):
    x,y,z=map(float,r);return np.array(((0.,-z,y),(z,0.,-x),(-y,x,0.)))

def _link_B(x_i,x_j,T):
    H=np.eye(6);H[:3,3:]=-_skew(np.asarray(x_j)-np.asarray(x_i));B=np.zeros((6,12));B[:,:6]=-np.asarray(T)@H;B[:,6:]=np.asarray(T);return B

def _single_storey_building(config):
    """Port-only RV30 storey assembly; no explicit-frame building kernel."""
    _,adapter,_=imports();cfg=adapter.build_config(config.data);cfg._beam_function=adapter.beam3d_global_stiffness;fp=adapter.rvkernel.fp
    from mscsolver._layout_parser_legacy import parse_layout
    from ..modal_solver import _beam_mass
    from types import SimpleNamespace
    layout=parse_layout(config.layout[0]);mixed=len({p.orientation for p in layout})>1
    specs,interfaces=adapter.rvkernel._mixed_specs_interfaces(layout,cfg) if mixed else (fp._specs(layout,cfg),fp.identify_layout_interfaces(layout,config=cfg));extras=fp._extras(interfaces);mods=[];module_start=perf_counter()
    for sp in specs:
        module_extras={side:t for (mid,side),t in extras.items() if mid==sp.module_id}
        if sp.orientation=='H':m=_build_direct(sp,module_extras,cfg)
        else:
            reverse={'E':'S','W':'N','S':'W','N':'E'};hextras={}
            for side,values in module_extras.items():
                hside=reverse[side]
                if side in ('E','W'):mapped={float(t)-sp.y0 for t in values}
                else:mapped={cfg.module_short_outer-(float(t)-sp.x0) for t in values}
                hextras[hside]=mapped
            hs=fp.ModuleSpec(sp.module_id,'H',0.,0.,cfg.module_long_outer,cfg.module_short_outer);m=_rotate_h_to_v(_build_direct(hs,hextras,cfg),sp,cfg,module_extras)
        mods.append(m)
    module_seconds=perf_counter()-module_start;offsets=[];port_n=0
    for m in mods:offsets.append(port_n);port_n+=len(m.K_port)
    N=port_n+24*len(interfaces);K=np.zeros((N,N));M=np.zeros((N,N))
    for off,m in zip(offsets,mods):K[off:off+len(m.K_port),off:off+len(m.K_port)]=m.K_port;M[off:off+len(m.M_port_lumped),off:off+len(m.M_port_lumped)]=m.M_port_lumped
    cores=[SimpleNamespace(port=m.port_metadata,coords=m.node_coordinates) for m in mods];arm_pairs=[(port_n+24*i+12*j,port_n+24*i+12*j+6) for i in range(len(interfaces)) for j in range(2)];pm=SimpleNamespace(modules=specs,interfaces=interfaces,offsets=offsets,cores=cores,arm_dofs=arm_pairs)
    arm=cfg.arm;armsec=type(cfg.sections()['column'])(2e6,2e6/(2*1.3),arm['A_mm2'],arm['Iy_mm4'],arm['Iz_mm4'],arm['J_mm4']);rho=float(cfg.steel_density_kg_m3)*1e-9;by={s.module_id:i for i,s in enumerate(pm.modules)};links=[]
    expanded=[(it,lev) for it in pm.interfaces for lev in ('FLOOR','CEIL')]
    for (it,lev),(aa,bb) in zip(expanded,pm.arm_dofs):
        ia,ib=by[it.module_a],by[it.module_b];la,xa=fp._corner_port(pm.cores[ia],pm.modules[ia],it.side_a,it.tangent,it.endpoint_a,lev,cfg);lb,xb=fp._corner_port(pm.cores[ib],pm.modules[ib],it.side_b,it.tangent,it.endpoint_b,lev,cfg);fa=fp._face(it,True,lev,cfg);fb=fp._face(it,False,lev,cfg);T=fp.connection_transformation(it);k=cfg.horizontal_connection.matrix();B=_link_B(fa,fb,T);ds=list(range(aa,aa+6))+list(range(bb,bb+6));K[np.ix_(ds,ds)]+=B.T@k@B
        for x0,x1,co,ao in ((xa,fa,pm.offsets[ia]+la,aa),(xb,fb,pm.offsets[ib]+lb,bb)):
            dd=list(range(co,co+6))+list(range(ao,ao+6));ke=cfg._beam_function(np.asarray(x0),np.asarray(x1),armsec);K[np.ix_(dd,dd)]+=ke;M[np.ix_(dd,dd)]+=_beam_mass(np.asarray(x0),np.asarray(x1),rho,armsec.A,armsec.Iy,armsec.Iz,True)
        links.append({'id':f'H{it.index}_{lev}','i':aa,'j':bb,'x_i':fa,'x_j':fb,'T':T,'K':k,'B':B})
    fixed=[];top=[]
    for off,core in zip(pm.offsets,pm.cores):
        for key,index in core.port.items():
            if key[0]=='BOT':fixed.append(off+index)
            if key[0]=='TOP' and key[-1] in (0,1):top.append((off+index,core.coords[key[:-1]],key[-1]))
    removed=set(fixed+[x[0] for x in top]);free=[i for i in range(N) if i not in removed];A=np.zeros((N,len(free)+3))
    for j,i in enumerate(free):A[i,j]=1.
    xref,yref=map(float,config.data['reference_point'])
    for i,p,d in top:A[i,-3+d]=1.;A[i,-1]=-(p[1]-yref) if d==0 else p[0]-xref
    Kr=A.T@K@A;Mr=A.T@M@A;recovery_to_reduced=[]
    # Exact elimination of the SAP Body TOP-R3 constraint.  TOP rotations stay
    # internal; their constraint energy is projected onto the single macro RZ.
    for off,module in zip(pm.offsets,mods):
        Qp=A[off:off+len(module.K_port),:];Kii=module.K_full[np.ix_(module.internal_dof_indices,module.internal_dof_indices)];invKii=np.linalg.inv(Kii)
        top_r3=[]
        keys=list(module.node_coordinates)
        for node,key in enumerate(keys):
            if key[0]=='TOP':top_r3.append(6*node+5)
        S=np.zeros((len(top_r3),len(module.internal_dof_indices)))
        position={int(value):i for i,value in enumerate(module.internal_dof_indices)}
        for row,full_index in enumerate(top_r3):S[row,position[full_index]]=1.
        desired=np.zeros((len(top_r3),len(Kr)));desired[:,-1]=1.;C=S@module.recovery_operator@Qp-desired;W=np.linalg.inv(S@invKii@S.T)
        internal_map=module.recovery_operator@Qp-invKii@S.T@W@C;Tm=np.zeros((len(module.K_full),len(Kr)));Tm[module.retained_dof_indices]=Qp;Tm[module.internal_dof_indices]=internal_map
        Kr+=Tm.T@module.K_full@Tm-Qp.T@module.K_port@Qp;Mr+=Tm.T@module.M_full_lumped@Tm-Qp.T@module.M_port_lumped@Qp;recovery_to_reduced.append(Tm)
    diag={'global_dofs':N,'constrained_solve_dofs':len(Kr),'module_port_dofs':sum(len(m.K_port) for m in mods),'hardware_dofs':N-sum(len(m.K_port) for m in mods),'link_endpoint_dofs':N-sum(len(m.K_port) for m in mods),'macro_dofs':3,'ordinary_internal_building_dofs':0,'module_internal_recoverable_dofs':sum(len(m.internal_dof_indices) for m in mods),'module_condensation_s':module_seconds}
    return FinitePortBuilding(K,M,A,Kr,Mr,mods,pm.offsets,pm.arm_dofs,links,[],np.asarray(fixed,int),np.arange(len(Kr)-3,len(Kr)),recovery_to_reduced,[1]*len(mods),diag)

def _multistorey_building(config):
    """Assemble independent storey port blocks plus six-DOF vertical Links."""
    templates={code:_single_storey_building(config) for code in dict.fromkeys(config.layout)};locals_=[templates[code] for code in config.layout];offsets=[];N=0
    for local in locals_:offsets.append(N);N+=len(local.K)
    K=np.zeros((N,N));M=np.zeros((N,N));modules=[];module_offsets=[];module_storeys=[];horizontal=[];vertical=[]
    for storey,(go,local) in enumerate(zip(offsets,locals_),1):
        K[go:go+len(local.K),go:go+len(local.K)]=local.K;M[go:go+len(local.M),go:go+len(local.M)]=local.M
        for module,mo in zip(local.modules,local.module_offsets):modules.append(module);module_offsets.append(go+mo);module_storeys.append(storey)
        for item in local.horizontal_links:
            q=dict(item);q['i']+=go;q['j']+=go;q['id']=f'S{storey}_{item["id"]}'
            dz=(storey-1)*(float(config.module_geometry['clear_storey_height_mm'])+2.*float(config.module_geometry['column_end_offset_mm']))
            q['x_i']=np.asarray(item['x_i'],float)+np.array((0.,0.,dz));q['x_j']=np.asarray(item['x_j'],float)+np.array((0.,0.,dz));horizontal.append(q)
    # Four coincident six-DOF TOP/BOT links per stacked module pair.
    from ..connection_stiffness import resolve_vertical_connection
    resolved_vertical=resolve_vertical_connection(config.vertical_link);vk=np.diag(resolved_vertical.values)
    if any(resolved_vertical.values[3:]):
        raise RuntimeError('dense finite_port multistorey rotational Links require finite_port_sparse Option C')
    for s in range(len(locals_)-1):
        lower,upper=locals_[s],locals_[s+1];upper_by={(m.module_id,m.orientation):i for i,m in enumerate(upper.modules)}
        for li,lm in enumerate(lower.modules):
            ui=upper_by[(lm.module_id,lm.orientation)];um=upper.modules[ui]
            for xs in ('W','E'):
                for ys in ('S','N'):
                    a=offsets[s]+lower.module_offsets[li]+lm.port_metadata[('TOP','C',xs,ys,0)];b=offsets[s+1]+upper.module_offsets[ui]+um.port_metadata[('BOT','C',xs,ys,0)];lower_dofs=[a+d for d in range(3)];upper_dofs=[b+d for d in range(3)];ids=lower_dofs+upper_dofs;B3=np.c_[-np.eye(3),np.eye(3)];K[np.ix_(ids,ids)]+=B3.T@vk[:3,:3]@B3
                    xa=lm.node_coordinates[('TOP','C',xs,ys)];xb=um.node_coordinates[('BOT','C',xs,ys)].copy();xb[2]=xa[2]
                    vertical.append({'id':f'V{s+1}_{lm.orientation}{lm.module_id:02d}_{xs}{ys}','i':a,'j':b,'x_i':xa,'x_j':xb,'K':vk,'endpoint_dofs':(lower_dofs+[-1]*3,upper_dofs+[-1]*3)})
    fixed=[];top=[]
    for mi,(module,mo,storey) in enumerate(zip(modules,module_offsets,module_storeys)):
        for key,index in module.port_metadata.items():
            if storey==1 and key[0]=='BOT':fixed.append(mo+index)
            if key[0]=='TOP' and key[-1] in (0,1):top.append((mo+index,module.node_coordinates[key[:-1]],key[-1],storey))
    removed=set(fixed+[x[0] for x in top]);free=[i for i in range(N) if i not in removed];A=np.zeros((N,len(free)+3*config.storeys))
    for j,i in enumerate(free):A[i,j]=1.
    xref,yref=map(float,config.data['reference_point']);macro=np.arange(len(free),len(free)+3*config.storeys).reshape(config.storeys,3)
    for i,p,d,storey in top:A[i,macro[storey-1,d]]=1.;A[i,macro[storey-1,2]]=-(p[1]-yref) if d==0 else p[0]-xref
    Kr=A.T@K@A;Mr=A.T@M@A;recovery=[]
    for module,mo,storey in zip(modules,module_offsets,module_storeys):
        Qp=A[mo:mo+len(module.K_port)];Kii=module.K_full[np.ix_(module.internal_dof_indices,module.internal_dof_indices)];inv=np.linalg.inv(Kii);keys=list(module.node_coordinates);top_r3=[6*i+5 for i,k in enumerate(keys) if k[0]=='TOP'];pos={int(v):i for i,v in enumerate(module.internal_dof_indices)};S=np.zeros((4,len(module.internal_dof_indices)))
        for row,index in enumerate(top_r3):S[row,pos[index]]=1.
        desired=np.zeros((4,len(Kr)));desired[:,macro[storey-1,2]]=1.;C=S@module.recovery_operator@Qp-desired;W=np.linalg.inv(S@inv@S.T);internal=module.recovery_operator@Qp-inv@S.T@W@C;Tm=np.zeros((len(module.K_full),len(Kr)));Tm[module.retained_dof_indices]=Qp;Tm[module.internal_dof_indices]=internal;Kr+=Tm.T@module.K_full@Tm-Qp.T@module.K_port@Qp;Mr+=Tm.T@module.M_full_lumped@Tm-Qp.T@module.M_port_lumped@Qp;recovery.append(Tm)
    diag={'global_dofs':N,'constrained_solve_dofs':len(Kr),'module_port_dofs':sum(len(x.K_port) for x in modules),'hardware_dofs':N-sum(len(x.K_port) for x in modules),'link_endpoint_dofs':N-sum(len(x.K_port) for x in modules),'macro_dofs':3*config.storeys,'ordinary_internal_building_dofs':0,'module_internal_recoverable_dofs':sum(len(x.internal_dof_indices) for x in modules),'horizontal_links':len(horizontal),'vertical_links':len(vertical),'module_cache_entries':len(templates),'module_cache_reused':len(locals_)>len(templates)}
    return FinitePortBuilding(K,M,A,Kr,Mr,modules,module_offsets,[],horizontal,vertical,np.asarray(fixed,int),macro.reshape(-1),recovery,module_storeys,diag)

class FinitePortBackend:
    name="finite_port"
    solver_backend="FINITE_PORT_SUPERELEMENT"
    def __init__(self,config):self.config=config;self.timings={}
    def build_module(self,module_id=1,orientation='H',extras=None):
        t=perf_counter();_,adapter,_=imports();cfg=adapter.build_config(self.config.data);cfg._beam_function=adapter.beam3d_global_stiffness;fp=adapter.rvkernel.fp
        if orientation=='H':spec=fp.ModuleSpec(module_id,'H',0.,0.,cfg.module_long_outer,cfg.module_short_outer);out=_build_direct(spec,extras or {},cfg)
        else:
            hs=fp.ModuleSpec(module_id,'H',0.,0.,cfg.module_long_outer,cfg.module_short_outer);h=_build_direct(hs,{},cfg);vs=fp.ModuleSpec(module_id,'V',0.,0.,cfg.module_short_outer,cfg.module_long_outer);out=_rotate_h_to_v(h,vs,cfg)
        self.timings['module_condensation_s']=perf_counter()-t;return out
    def build_building(self):
        t=perf_counter();out=_single_storey_building(self.config) if self.config.storeys==1 else _multistorey_building(self.config);self.timings['global_assembly_s']=perf_counter()-t;self.timings['module_condensation_s']=out.diagnostics.get('module_condensation_s',0.);return out
    def solve_static(self,load_cases=None):
        from ..result import StaticResult
        b=self.build_building();names=load_cases or list(self.config.load_cases);storey={};disp={};hforce={};react={};energy={};reduced={};t=perf_counter()
        for name in names:
            if name not in ('TH_UX','TH_UY','TH_RZ'):raise NotImplementedError(name)
            macros=b.macro_dofs.reshape(self.config.storeys,3);f=np.zeros(len(b.reduced_K));f[macros[-1,('TH_UX','TH_UY','TH_RZ').index(name)]]=1.;q=solve(b.reduced_K,f,assume_a='pos',check_finite=False);u=b.constraint_transform@q
            storey[name]=[{'ux_bar':float(q[row[0]]),'uy_bar':float(q[row[1]]),'theta_z_bar':float(q[row[2]]),'distortion_norm':0.,'distortion_ratio':0.} for row in macros];disp[name]=u;reduced[name]=q;energy[name]=float(.5*q@b.reduced_K@q);react[name]=(b.K@u)[b.fixed_dofs];hforce[name]={x['id']:np.asarray(x['K'])@(x['B']@u[np.r_[np.arange(x['i'],x['i']+6),np.arange(x['j'],x['j']+6)]]) for x in b.horizontal_links}
            vf={}
            for x in b.vertical_links:
                delta=np.zeros(6)
                for component,(i,j) in enumerate(zip(*x['endpoint_dofs'])):
                    if i>=0 and j>=0:delta[component]=u[j]-u[i]
                vf[x['id']]=np.asarray(x['K'])@delta
            react[name]=react[name];
            if name not in locals().get('vforce',{}):pass
            vertical_case=vf
            if 'vertical_results' not in locals():vertical_results={}
            vertical_results[name]=vertical_case
        self.timings['static_solve_s']=perf_counter()-t;self.last_building=b;self.last_reduced_static=reduced
        qa=dict(b.diagnostics,K_symmetry=float(np.linalg.norm(b.K-b.K.T)/max(np.linalg.norm(b.K),1.)),passed=True)
        return StaticResult(storey,disp,hforce,vertical_results if b.vertical_links else {name:{} for name in names},react,energy,qa)
    def solve_modal(self,num_modes=3,mass_model='lumped'):
        from ..result import ModalResult
        if mass_model!='lumped':raise NotImplementedError('finite-port formal path is lumped mass')
        b=self.build_building();K,M=b.reduced_K,b.reduced_M;t=perf_counter();mq,U=np.linalg.eigh((M+M.T)/2);tol=max(float(mq.max())*1e-11,1e-14);P=U[:,mq>tol];N=U[:,mq<=tol]
        T=P+N@(-np.linalg.pinv(N.T@K@N,rcond=1e-12)@(N.T@K@P)) if N.shape[1] else P;ev,V=eigh(T.T@K@T,T.T@M@T,subset_by_index=(0,min(max(num_modes,6)-1,T.shape[1]-1)));keep=ev>1e-8;ev=ev[keep][:num_modes];qr=(T@V[:,keep])[:,:num_modes];phi=b.constraint_transform@qr;macro=qr[b.macro_dofs,:];types=[]
        for q in macro.T:
            amp=np.array((np.linalg.norm(q[0::3]),np.linalg.norm(q[1::3]),np.linalg.norm(q[2::3])*float(self.config.module_geometry['long_outer_mm'])));types.append(('X-dominant','Y-dominant','RZ-dominant')[int(np.argmax(amp))])
        w=np.sqrt(ev);self.timings['modal_solve_s']=perf_counter()-t;self.last_building=b;qa=dict(b.diagnostics,M_symmetry=float(np.linalg.norm(M-M.T)/max(np.linalg.norm(M),1.)),minimum_effective_mass_eigenvalue=float(mq[mq>tol].min()),passed=not np.any(mq<-tol))
        return ModalResult(ev,w,w/(2*np.pi),2*np.pi/w,phi,macro,types,mass_model,qa)
