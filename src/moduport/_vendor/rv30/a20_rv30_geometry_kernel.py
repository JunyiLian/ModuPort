"""RV30 geometry-parametric assembly over frozen ModuPort V1 formulations."""
from __future__ import annotations
import time
import numpy as np
from scipy.linalg import block_diag
from scipy.sparse import csc_matrix
from mscsolver import _kernel_v1 as v1
from mscsolver import _finite_port as fp
from mscsolver import _module_layout as mm

REFERENCE_PORT_DOF = "REFERENCE_PORT_DOF"
ACTUAL_LINK_ENDPOINT_DOF = "ACTUAL_LINK_ENDPOINT_DOF"
DOUBLE_ENDPOINT_TRANSPORT = "DOUBLE_ENDPOINT_TRANSPORT"

def _mixed_specs_interfaces(layout,cfg):
    """RV30 mixed-orientation placement/interface policy over frozen core types."""
    specs=[]
    for p in layout:
        rs=[x[0] for x in p.cells];cs=[x[1] for x in p.cells]
        w=cfg.module_long_outer if p.orientation=='H' else cfg.module_short_outer
        h=cfg.module_short_outer if p.orientation=='H' else cfg.module_long_outer
        specs.append(fp.ModuleSpec(p.module_id,p.orientation,min(cs)*cfg.cell_pitch,min(rs)*cfg.cell_pitch,w,h))
    specs=sorted(specs,key=lambda s:s.name);out=[];tol=1e-6
    for i,a0 in enumerate(specs):
        for b0 in specs[i+1:]:
            candidates=[]
            if np.isclose(a0.x1+cfg.module_clear_gap,b0.x0,atol=tol):candidates.append(('X',a0,b0,'E','W',a0.x1,b0.x0))
            elif np.isclose(b0.x1+cfg.module_clear_gap,a0.x0,atol=tol):candidates.append(('X',b0,a0,'E','W',b0.x1,a0.x0))
            if np.isclose(a0.y1+cfg.module_clear_gap,b0.y0,atol=tol):candidates.append(('Y',a0,b0,'N','S',a0.y1,b0.y0))
            elif np.isclose(b0.y1+cfg.module_clear_gap,a0.y0,atol=tol):candidates.append(('Y',b0,a0,'N','S',b0.y1,a0.y0))
            for d,a,b,sa,sb,fa,fb in candidates:
                aa=(a.y0+cfg.column_half_mm,a.y1-cfg.column_half_mm) if d=='X' else (a.x0+cfg.column_half_mm,a.x1-cfg.column_half_mm)
                bb=(b.y0+cfg.column_half_mm,b.y1-cfg.column_half_mm) if d=='X' else (b.x0+cfg.column_half_mm,b.x1-cfg.column_half_mm)
                for t in sorted({max(aa[0],bb[0]),min(aa[1],bb[1])}):
                    if t>min(aa[1],bb[1])+tol or t<max(aa[0],bb[0])-tol:continue
                    ca=np.isclose(t,aa[0],atol=tol) or np.isclose(t,aa[1],atol=tol);cb=np.isclose(t,bb[0],atol=tol) or np.isclose(t,bb[1],atol=tol)
                    out.append(fp.Interface(len(out)+1,d,a.module_id,b.module_id,sa,sb,fa,fb,float(t),'CORNER' if ca else 'BEAM','CORNER' if cb else 'BEAM'))
    return specs,out

def horizontal_link_B(x_i, x_j, T=None, mode=REFERENCE_PORT_DOF, p_i=None, p_j=None):
    """Adapter-level horizontal Link kinematics without changing V1 core.

    Reference-port DOFs require the formal H(r_IJ) transport.  Explicit arm-tip
    DOFs already sit at the finite Link ends and therefore use only u_J-u_I.
    """
    if mode == REFERENCE_PORT_DOF:
        return v1.link_B(x_i, x_j, T)
    if mode == DOUBLE_ENDPOINT_TRANSPORT:
        if p_i is None or p_j is None:
            raise ValueError("double-endpoint transport requires both reference-port coordinates")
        T=np.eye(6) if T is None else np.asarray(T,float)
        B=np.zeros((6,12));B[:,:6]=-T@v1.H(np.asarray(x_i)-np.asarray(p_i));B[:,6:]=T@v1.H(np.asarray(x_j)-np.asarray(p_j))
        return B
    if mode != ACTUAL_LINK_ENDPOINT_DOF:
        raise ValueError(f"unknown horizontal Link kinematics mode: {mode}")
    T=np.eye(6) if T is None else np.asarray(T,float)
    B=np.zeros((6,12)); B[:3,:3]=-T[:3,:3]; B[:3,6:9]=T[:3,:3]
    return B

def horizontal_link_matrix(x_i, x_j, k, T=None, mode=REFERENCE_PORT_DOF, p_i=None, p_j=None):
    B=horizontal_link_B(x_i,x_j,T,mode,p_i,p_j)
    return B.T@np.asarray(k,float)@B

def reinforced_zone_intervals(sp, extras, cfg):
    """Boundary-shifted, merged T-zone intervals on each mother beam."""
    if not getattr(cfg,'reinforced_zone_active',False) or sp.orientation!='V':return {}
    Lr=float(cfg.reinforced_zone['zone_length_mm']);out={}
    for side,tans in extras.items():
        lo=(sp.y0+cfg.column_half_mm if side in ('W','E') else sp.x0+cfg.column_half_mm);hi=(sp.y1-cfg.column_half_mm if side in ('W','E') else sp.x1-cfg.column_half_mm)
        if hi-lo<=Lr:raw=[(lo,hi)]
        else:raw=[(min(max(float(t)-Lr/2,lo),hi-Lr),min(max(float(t)-Lr/2,lo),hi-Lr)+Lr) for t in sorted(tans)]
        merged=[]
        for a,b in sorted(raw):
            if merged and a<=merged[-1][1]+1e-9:merged[-1]=(merged[-1][0],max(merged[-1][1],b))
            else:merged.append((a,b))
        out[side]={'ports':sorted(map(float,tans)),'raw':raw,'merged':merged,'bounds':(lo,hi)}
    return out

def _rv30_core(sp,extras,cfg):
    zones=reinforced_zone_intervals(sp,extras,cfg)
    if not zones:return v1._core(sp,extras,cfg)
    sec=cfg.sections();nodes=[];ids={};co={}
    def add(k,p):
        if k not in ids:ids[k]=len(nodes);co[k]=np.asarray(p,float);nodes.append(co[k])
    for lev,z in (('FLOOR',0.),('CEIL',cfg.clear_storey_height)):
        for xs in ('W','E'):
            for ys in ('S','N'):add((lev,'C',xs,ys),tuple(fp._corner(sp,xs,ys,cfg))+(z,))
    for side,tans in extras.items():
        lo,hi=zones[side]['bounds'];vals=set(map(float,tans))
        for a,b in zones[side]['merged']:vals.update((a,b))
        for t in sorted(x for x in vals if x>lo+1e-9 and x<hi-1e-9):
            for lev,z in (('FLOOR',0.),('CEIL',cfg.clear_storey_height)):add((lev,'B',side,round(t,6)),fp._extra_xyz(sp,side,t,z,cfg))
    mult=cfg.reinforced_zone
    def rz(s):return mm.Section(s.E,s.G,s.A*mult['A_multiplier'],s.Iy*mult['Iy_multiplier'],s.Iz*mult['Iz_multiplier'],s.J*mult['J_multiplier'])
    fr=[];sides=(('S',('W','S'),('E','S')),('E',('E','S'),('E','N')),('N',('W','N'),('E','N')),('W',('W','S'),('W','N')))
    for xs in ('W','E'):
        for ys in ('S','N'):fr.append((('FLOOR','C',xs,ys),('CEIL','C',xs,ys),sec['column'],'MAIN_COLUMN'))
    for lev in ('FLOOR','CEIL'):
        for side,a,b in sides:
            mids=sorted((k for k in ids if k[0]==lev and k[1]=='B' and k[2]==side),key=lambda k:k[3]);q=[(lev,'C',*a)]+mids+[(lev,'C',*b)];base=fp._section_for_side(sp,lev,side,sec)
            tangent=lambda k:float(co[k][1] if side in ('W','E') else co[k][0])
            for i,j in zip(q,q[1:]):
                mid=.5*(tangent(i)+tangent(j));active=any(x-1e-9<=mid<=y+1e-9 for x,y in zones.get(side,{}).get('merged',()))
                fr.append((i,j,rz(base) if active else base,lev+'_BEAM_RZ' if active else lev+'_BEAM'))
    K=np.zeros((6*len(nodes),6*len(nodes)))
    for a,b,s,_ in fr:
        if np.linalg.norm(co[a]-co[b])<=1e-9:raise ValueError(f'zero T-zone segment {sp} {a} {b}')
        ke=cfg._beam_function(co[a],co[b],s);d=list(range(6*ids[a],6*ids[a]+6))+list(range(6*ids[b],6*ids[b]+6));K[np.ix_(d,d)]+=ke
    return v1.Core(K,ids,co,fr)

def _storey(layout_code,cfg,storey):
    layout=v1.parse_layout(layout_code)
    if len({p.orientation for p in layout})>1:specs,interfaces=_mixed_specs_interfaces(layout,cfg)
    else:specs=fp._specs(layout,cfg);interfaces=fp.identify_layout_interfaces(layout,config=cfg)
    ex=fp._extras(interfaces)
    cores=[_rv30_core(sp,{side:t for (mid,side),t in ex.items() if mid==sp.module_id},cfg) for sp in specs]
    sizes=[len(c.K) for c in cores];offs=np.cumsum([0]+sizes[:-1]).tolist();n=sum(sizes)+24*len(interfaces)+48*len(cores);K=np.zeros((n,n));coords={};dof={};top=[];bot=[];hlinks=[]
    zbase=(storey-1)*(cfg.clear_storey_height+2*cfg.column_end_offset)
    for off,sp,core in zip(offs,specs,cores):
        K[off:off+len(core.K),off:off+len(core.K)]=core.K
        for key,i in core.ids.items():
            lev=key[0];suffix=(key[2]+key[3] if key[1]=='C' else f'{key[2]}_T_{key[3]}');name=f'S{storey}_{sp.orientation}{sp.module_id:02d}_{suffix}_{lev}';coords[name]=core.coords[key]+(0,0,zbase);dof[name]=off+6*i
    cursor=sum(sizes);a=cfg.arm;armsec=mm.Section(2e6,2e6/(2*1.3),float(a['A_mm2']),float(a['Iy_mm4']),float(a['Iz_mm4']),float(a['J_mm4']));by={s.module_id:i for i,s in enumerate(specs)}
    for it in interfaces:
        ia,ib=by[it.module_a],by[it.module_b]
        for lev in ('FLOOR','CEIL'):
            ka=v1._corner_key(specs[ia],it,'a',lev,cfg);kb=v1._corner_key(specs[ib],it,'b',lev,cfg);xa=cores[ia].coords[ka];xb=cores[ib].coords[kb];fa=fp._face(it,True,lev,cfg);fb=fp._face(it,False,lev,cfg);aa,ab=cursor,cursor+6;cursor+=12
            for x0,x1,coff,aoff in ((xa,fa,offs[ia]+6*cores[ia].ids[ka],aa),(xb,fb,offs[ib]+6*cores[ib].ids[kb],ab)):
                ke=cfg._beam_function(x0,x1,armsec);dd=list(range(coff,coff+6))+list(range(aoff,aoff+6));K[np.ix_(dd,dd)]+=ke
            T=fp.connection_transformation(it);mode=getattr(cfg,'horizontal_connection_kinematics_mode',REFERENCE_PORT_DOF);dd=list(range(aa,aa+6))+list(range(ab,ab+6));K[np.ix_(dd,dd)]+=horizontal_link_matrix(fa,fb,cfg.horizontal_connection.matrix(),T,mode,xa,xb);hlinks.append({'id':f'S{storey}_H{it.index}_{lev}','i':aa,'j':ab,'x_i':fa+(0,0,zbase),'x_j':fb+(0,0,zbase),'p_i':xa+(0,0,zbase),'p_j':xb+(0,0,zbase),'K':cfg.horizontal_connection.matrix(),'T':T,'kinematics_mode':mode})
    for off,sp,core in zip(offs,specs,cores):
        for xs in ('W','E'):
            for ys in ('S','N'):
                for lev,z,struct in [('BOT',-cfg.column_end_offset,('FLOOR','C',xs,ys)),('TOP',cfg.clear_storey_height+cfg.column_end_offset,('CEIL','C',xs,ys))]:
                    base=cursor;cursor+=6;p=core.coords[struct].copy();p[2]=z;st=off+6*core.ids[struct]
                    # The element matrix is ordered by its geometric I/J ends.
                    # BOT is BOT->FLOOR, while TOP is CEIL->TOP.  Insert the
                    # corresponding global DOFs in exactly that same order.
                    if lev=='BOT':
                        x0,x1=p,core.coords[struct]
                        dd=list(range(base,base+6))+list(range(st,st+6))
                    else:
                        x0,x1=core.coords[struct],p
                        dd=list(range(st,st+6))+list(range(base,base+6))
                    ke=cfg._beam_function(x0,x1,cfg.sections()['column'])
                    K[np.ix_(dd,dd)]+=ke;name=f'S{storey}_{sp.orientation}{sp.module_id:02d}_{xs}{ys}_{lev}';coords[name]=p+(0,0,zbase);dof[name]=base;(bot if lev=='BOT' else top).append(name)
    return K,coords,dof,top,bot,hlinks,specs

def build_model(case,config,boundary_mode):
    mode=boundary_mode or v1.FREE_BARE_FRAME;config._beam_function=mm.beam3d_global_stiffness;codes=case['storey_layouts'];parts=[_storey(code,config,s+1) for s,code in enumerate(codes)];Ks=[p[0] for p in parts];K=block_diag(*Ks);offs=np.cumsum([0]+[len(x) for x in Ks[:-1]]);coords={};dof={};top={};bot={};hl=[];specall=[]
    for s,(off,p) in enumerate(zip(offs,parts),1):
        _,co,dm,tp,bt,links,ss=p;coords.update(co);dof.update({n:off+i for n,i in dm.items()});top[s]=tp;bot[s]=bt;specall+=ss
        for z in links:y=dict(z);y['i']+=off;y['j']+=off;hl.append(y)
    vl=[];vk=config.vertical_connection.matrix()
    for s in range(1,len(parts)):
        up={(round(coords[n][0],6),round(coords[n][1],6)):n for n in bot[s+1]}
        for a in top[s]:
            key=(round(coords[a][0],6),round(coords[a][1],6))
            if key in up:
                b=up[key];ia,ib=dof[a],dof[b];dd=list(range(ia,ia+6))+list(range(ib,ib+6));K[np.ix_(dd,dd)]+=v1.link_matrix(coords[a],coords[b],vk);vl.append({'id':f'V{s}_{a}_{b}','i':ia,'j':ib,'x_i':coords[a],'x_j':coords[b],'K':vk,'T':np.eye(6)})
    fixed=np.array([dof[n]+j for n in bot[1] for j in range(3)],int);return v1.Model(csc_matrix(K),coords,dof,fixed,top,bot,hl,vl,len(specall),sum(s.orientation=='H' for s in specall),sum(s.orientation=='V' for s in specall),codes,mode)

def solve_with_rv30_boundary(model,loads):
    """Project-side SAP Body(U1,U2,R3) equivalent; frozen core is untouched."""
    f=np.zeros(model.K.shape[0])
    for z in loads:
        i=model.dof[z['joint_name']];f[i:i+6]+=[z.get(k,0.) for k in ('Fx','Fy','Fz','Mx','My','Mz')]
    free=np.setdiff1d(np.arange(len(f)),model.fixed);pos={g:i for i,g in enumerate(free)};rows=[]
    for nodes in model.top.values():
        master=nodes[0];bm=model.dof[master];xm,ym,_=model.coords[master]
        for name in nodes[1:]:
            b=model.dof[name];x,y,_=model.coords[name]
            for terms in ({b:1.,bm:-1.,bm+5:y-ym},{b+1:1.,bm+1:-1.,bm+5:-(x-xm)},{b+5:1.,bm+5:-1.}):
                r=np.zeros(len(free))
                for g,v in terms.items():
                    if g in pos:r[pos[g]]=v
                rows.append(r)
    K=model.K[free][:,free].toarray();C=np.asarray(rows);A=np.block([[K,C.T],[C,np.zeros((len(C),len(C)))]]) if len(C) else K;rhs=np.r_[f[free],np.zeros(len(C))] if len(C) else f[free];z=np.linalg.solve(A,rhs);u=np.zeros(len(f));u[free]=z[:len(free)];res=np.linalg.norm(A@z-rhs)/max(np.linalg.norm(rhs),1e-30);return u,float(res)

def case_result(case,config,boundary_mode):
    t0=time.perf_counter();m=build_model(case,config,boundary_mode);responses={};F=[]
    for lc in ('TH_UX','TH_UY','TH_RZ'):
        u,res=solve_with_rv30_boundary(m,v1.top_loads(m,lc,case.get('reference_point')));responses[lc]={'u':u,'residual':res,'storeys':[v1.project(m,u,s,case.get('reference_point')) for s in range(1,len(m.top)+1)]};roof=responses[lc]['storeys'][-1];F.append([roof['ux_bar'],roof['uy_bar'],roof['theta_z_bar']])
    flex=np.column_stack(F);stiff=np.linalg.inv(flex);sym=np.linalg.norm(stiff-stiff.T)/max(np.linalg.norm(stiff),1.);return {'case_id':case['case_id'],'case_hash':v1.layout_hash(case),'model':m,'responses':responses,'projected_generalized_flexibility':flex,'projected_generalized_stiffness':stiff,'solve_seconds':time.perf_counter()-t0,'symmetry_error':sym,'geometry_kernel':'RV30_CONFIG_PARAMETRIC'}
