from __future__ import annotations
import numpy as np
from scipy.linalg import eigh,null_space
from .result import ModalResult
from .runtime import imports
from .exceptions import ModalSolveError

def _beam_mass(x1,x2,rho,A,Iy,Iz,lumped):
    d=x2-x1;L=float(np.linalg.norm(d));ex=d/L;ref=np.array([0.,0.,1.]) if abs(ex[2])<.9 else np.array([0.,1.,0.]);ey=np.cross(ref,ex);ey/=np.linalg.norm(ey);ez=np.cross(ex,ey);R=np.vstack((ex,ey,ez));T=np.zeros((12,12))
    for i in (0,3,6,9):T[i:i+3,i:i+3]=R
    M=np.zeros((12,12));mu=rho*A
    if lumped:
        for i in (0,1,2,6,7,8):M[i,i]=mu*L/2
    else:
        M[0,0]=M[6,6]=mu*L/3;M[0,6]=M[6,0]=mu*L/6
        for a,b in ((1,5),(2,4)):
            ids=(a,b,a+6,b+6);Q=mu*L/420*np.array(((156,22*L,54,-13*L),(22*L,4*L*L,13*L,-3*L*L),(54,13*L,156,-22*L),(-13*L,-3*L*L,-22*L,4*L*L)))
            M[np.ix_(ids,ids)]+=Q
        for a,b in ((3,9),):M[a,a]=M[b,b]=rho*(Iy+Iz)*L/3;M[a,b]=M[b,a]=rho*(Iy+Iz)*L/6
    return T.T@M@T

def _frames(data,cfg,adapter,n):
    from mscsolver import _kernel_v1 as v1
    from mscsolver import _finite_port as fp
    frames=[];go=0
    for si,code in enumerate(data["storey_layouts"],1):
        layout=v1.parse_layout(code);specs,ints=adapter.rvkernel._mixed_specs_interfaces(layout,cfg) if len({p.orientation for p in layout})>1 else (fp._specs(layout,cfg),fp.identify_layout_interfaces(layout,config=cfg));ex=fp._extras(ints);cores=[adapter.rvkernel._rv30_core(sp,{side:t for (mid,side),t in ex.items() if mid==sp.module_id},cfg) for sp in specs];sizes=[len(x.K) for x in cores];offs=np.cumsum([0]+sizes[:-1]).tolist();cursor=sum(sizes);by={s.module_id:i for i,s in enumerate(specs)};dz=(si-1)*(cfg.clear_storey_height+2*cfg.column_end_offset)
        for off,core in zip(offs,cores):
            for a,b,s,_ in core.frames:frames.append((core.coords[a]+[0,0,dz],core.coords[b]+[0,0,dz],go+off+6*core.ids[a],go+off+6*core.ids[b],s,si))
        arm=cfg.arm;arms=type(cfg.sections()["column"])(2e6,2e6/(2*1.3),arm["A_mm2"],arm["Iy_mm4"],arm["Iz_mm4"],arm["J_mm4"])
        for it in ints:
            ia,ib=by[it.module_a],by[it.module_b]
            for lev in ("FLOOR","CEIL"):
                ka=v1._corner_key(specs[ia],it,"a",lev,cfg);kb=v1._corner_key(specs[ib],it,"b",lev,cfg);xa=cores[ia].coords[ka]+[0,0,dz];xb=cores[ib].coords[kb]+[0,0,dz];fa=fp._face(it,True,lev,cfg)+[0,0,dz];fb=fp._face(it,False,lev,cfg)+[0,0,dz];aa,ab=cursor,cursor+6;cursor+=12;frames.extend(((xa,fa,go+offs[ia]+6*cores[ia].ids[ka],go+aa,arms,si),(xb,fb,go+offs[ib]+6*cores[ib].ids[kb],go+ab,arms,si)))
        for off,sp,core in zip(offs,specs,cores):
            for xs in ("W","E"):
                for ys in ("S","N"):
                    for lev,z,key in (("BOT",-cfg.column_end_offset,("FLOOR","C",xs,ys)),("TOP",cfg.clear_storey_height+cfg.column_end_offset,("CEIL","C",xs,ys))):
                        p=core.coords[key].copy();p[2]=z;p+=np.array((0,0,dz));st=off+6*core.ids[key];base=cursor;cursor+=6;x0,x1=(p,core.coords[key]+[0,0,dz]) if lev=="BOT" else (core.coords[key]+[0,0,dz],p);i,j=(base,st) if lev=="BOT" else (st,base);frames.append((x0,x1,go+i,go+j,cfg.sections()["column"],si))
        go+=cursor
    if go!=n:raise ModalSolveError(f"mass registry size mismatch: {go}/{n}")
    return frames

def _macro(model,u,ref):
    out=[]
    for s in sorted(model.top):
        A=[];b=[]
        for p in model.top[s]:
            x,y,_=model.coords[p];i=model.dof[p];A.extend(((1,0,-(y-ref[1])),(0,1,x-ref[0])));b.extend((u[i],u[i+1]))
        out.extend(np.linalg.lstsq(np.asarray(A),np.asarray(b),rcond=None)[0])
    return np.asarray(out)

def solve_modal(config,num_modes=3,mass_model="lumped"):
    _,adapter,_=imports();built=adapter.solve_rv30_config(config.source);cfg=built["config"];model=built["result"]["model"];K=model.K.toarray();n=len(K);M=np.zeros((n,n));rho=float(config.material.get("density_kg_m3",7850))*1e-9;mass=0.;mom=np.zeros(3)
    for x1,x2,i,j,s,_ in _frames(config.data,cfg,adapter,n):
        ix=list(range(i,i+6))+list(range(j,j+6));M[np.ix_(ix,ix)]+=_beam_mass(np.asarray(x1),np.asarray(x2),rho,s.A,s.Iy,s.Iz,mass_model=="lumped");mm=rho*s.A*np.linalg.norm(x2-x1);mass+=mm;mom+=mm*(x1+x2)/2
    C=[]
    for q in model.fixed:r=np.zeros(n);r[q]=1;C.append(r)
    for nodes in model.top.values():
        master=nodes[0];bm=model.dof[master];xm,ym,_=model.coords[master]
        for name in nodes[1:]:
            b=model.dof[name];x,y,_=model.coords[name]
            for terms in ({b:1,bm:-1,bm+5:y-ym},{b+1:1,bm+1:-1,bm+5:-(x-xm)},{b+5:1,bm+5:-1}):
                r=np.zeros(n)
                for q,v in terms.items():r[q]=v
                C.append(r)
    Z=null_space(np.asarray(C));Kr=Z.T@K@Z;Q=Z.T@M@Z;mq,U=np.linalg.eigh((Q+Q.T)/2);tol=max(mq.max()*1e-11,1e-14);P=U[:,mq>tol];N=U[:,mq<=tol]
    try:T=P+N@(-np.linalg.pinv(N.T@Kr@N,rcond=1e-12)@(N.T@Kr@P)) if N.shape[1] else P;ev,V=eigh(T.T@Kr@T,T.T@Q@T,subset_by_index=(0,min(max(num_modes,6)-1,T.shape[1]-1)))
    except Exception as e:raise ModalSolveError(str(e)) from e
    keep=ev>1e-8;ev=ev[keep][:num_modes];phi=(Z@T@V[:,keep])[:,:num_modes];w=np.sqrt(ev);macro=np.column_stack([_macro(model,phi[:,i],config.data["reference_point"]) for i in range(len(ev))]);types=[]
    for q in macro.T:
        amp=np.array([np.linalg.norm(q[0::3]),np.linalg.norm(q[1::3]),np.linalg.norm(q[2::3])*float(config.module_geometry["long_outer_mm"])]);types.append(("X-dominant","Y-dominant","RZ-dominant")[int(np.argmax(amp))])
    negative=bool(np.any(mq < -tol));qa={"M_symmetry":float(np.linalg.norm(M-M.T)/max(np.linalg.norm(M),1e-30)),"minimum_effective_mass_eigenvalue":float(mq[mq>tol].min()),"negative_mass_eigenvalue":negative,"pseudo_zero_mode":bool(np.any(ev<=1e-8)),"total_mass_kg":mass,"center_of_mass_mm":(mom/mass).tolist(),"passed":not negative and not np.any(ev<=1e-8)}
    return ModalResult(ev,w,w/(2*np.pi),2*np.pi/w,phi,macro,types,mass_model,qa)
