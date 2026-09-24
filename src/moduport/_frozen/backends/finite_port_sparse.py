from __future__ import annotations
from dataclasses import dataclass
from time import perf_counter
import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import LinearOperator,eigsh,lobpcg,splu

from .finite_port import _build_direct,_rotate_h_to_v,_link_B
from ..runtime import imports

def _connection_deformation(link,u):
    if 'endpoint_dofs' in link:
        value=np.zeros(6)
        for d,(i,j) in enumerate(zip(*link['endpoint_dofs'])):
            if i>=0 and j>=0:value[d]=u[j]-u[i]
        return value
    ids=np.r_[np.arange(link['i'],link['i']+6),np.arange(link['j'],link['j']+6)]
    return link['B']@u[ids]

@dataclass
class SparseFinitePortBuilding:
    K:sparse.csr_matrix;M:sparse.csr_matrix;constraint_transform:sparse.csr_matrix
    reduced_K:sparse.csr_matrix;reduced_M:sparse.csr_matrix;modules:list;module_offsets:list
    horizontal_links:list;vertical_links:list;fixed_dofs:np.ndarray;macro_dofs:np.ndarray
    module_recovery_local:list;module_storeys:list;diagnostics:dict

def _add(rows,cols,data,idx,block,tol=0.):
    b=np.asarray(block);ii,jj=np.nonzero(abs(b)>tol);rows.extend(np.asarray(idx)[ii]);cols.extend(np.asarray(idx)[jj]);data.extend(b[ii,jj])

def _storey(config,expression):
    _,adapter,_=imports();cfg=adapter.build_config(config.data);cfg._beam_function=adapter.beam3d_global_stiffness;fp=adapter.rvkernel.fp
    from mscsolver._layout_parser_legacy import parse_layout
    from types import SimpleNamespace
    layout=parse_layout(expression);mixed=len({p.orientation for p in layout})>1
    specs,interfaces=adapter.rvkernel._mixed_specs_interfaces(layout,cfg) if mixed else (fp._specs(layout,cfg),fp.identify_layout_interfaces(layout,config=cfg));extras=fp._extras(interfaces);mods=[]
    for sp in specs:
        ex={side:t for (mid,side),t in extras.items() if mid==sp.module_id}
        if sp.orientation=='H':m=_build_direct(sp,ex,cfg)
        else:
            reverse={'E':'S','W':'N','S':'W','N':'E'};hextras={}
            for side,values in ex.items():
                hside=reverse[side];hextras[hside]={float(t)-sp.y0 for t in values} if side in ('E','W') else {cfg.module_short_outer-(float(t)-sp.x0) for t in values}
            hs=fp.ModuleSpec(sp.module_id,'H',0.,0.,cfg.module_long_outer,cfg.module_short_outer);m=_rotate_h_to_v(_build_direct(hs,hextras,cfg),sp,cfg,ex)
        mods.append(m)
    return SimpleNamespace(cfg=cfg,fp=fp,specs=specs,interfaces=interfaces,mods=mods)

def build_sparse_building(config):
    from ..modal_solver import _beam_mass
    t0=perf_counter();stores=[_storey(config,x) for x in config.layout];cfg=stores[0].cfg
    offsets=[];module_offsets=[];module_storeys=[];modules=[];N=0
    for si,s in enumerate(stores,1):
        offsets.append(N)
        for m in s.mods:module_offsets.append(N);module_storeys.append(si);modules.append(m);N+=len(m.K_port)
        N+=24*len(s.interfaces)
    rK=[];cK=[];dK=[];rM=[];cM=[];dM=[];horizontal=[]
    module_cursor=0
    for si,(go,s) in enumerate(zip(offsets,stores),1):
        local_port=sum(len(m.K_port) for m in s.mods);moffs=[];q=go
        for m in s.mods:
            moffs.append(q);idx=np.arange(q,q+len(m.K_port));_add(rK,cK,dK,idx,m.K_port);_add(rM,cM,dM,idx,m.M_port_lumped);q+=len(m.K_port)
        cores=[type('Core',(),{'port':m.port_metadata,'coords':m.node_coordinates}) for m in s.mods];by={x.module_id:i for i,x in enumerate(s.specs)}
        expanded=[(it,lev) for it in s.interfaces for lev in ('FLOOR','CEIL')];armbase=go+local_port
        armsec=type(cfg.sections()['column'])(2e6,2e6/(2*1.3),cfg.arm['A_mm2'],cfg.arm['Iy_mm4'],cfg.arm['Iz_mm4'],cfg.arm['J_mm4']);rho=float(cfg.steel_density_kg_m3)*1e-9
        for h,(it,lev) in enumerate(expanded):
            aa=armbase+12*h;bb=aa+6;ia,ib=by[it.module_a],by[it.module_b]
            la,xa=s.fp._corner_port(cores[ia],s.specs[ia],it.side_a,it.tangent,it.endpoint_a,lev,cfg);lb,xb=s.fp._corner_port(cores[ib],s.specs[ib],it.side_b,it.tangent,it.endpoint_b,lev,cfg);fa=s.fp._face(it,True,lev,cfg);fb=s.fp._face(it,False,lev,cfg);T=s.fp.connection_transformation(it);k=cfg.horizontal_connection.matrix();B=_link_B(fa,fb,T);idx=np.r_[np.arange(aa,aa+6),np.arange(bb,bb+6)];_add(rK,cK,dK,idx,B.T@k@B)
            for x0,x1,co,ao in ((xa,fa,moffs[ia]+la,aa),(xb,fb,moffs[ib]+lb,bb)):
                ids=np.r_[np.arange(co,co+6),np.arange(ao,ao+6)];ke=cfg._beam_function(np.asarray(x0),np.asarray(x1),armsec);me=_beam_mass(np.asarray(x0),np.asarray(x1),rho,armsec.A,armsec.Iy,armsec.Iz,True);_add(rK,cK,dK,ids,ke);_add(rM,cM,dM,ids,me)
            dz=(si-1)*(cfg.clear_storey_height+2*cfg.column_end_offset);horizontal.append({'id':f'S{si}_H{it.index}_{lev}','i':aa,'j':bb,'x_i':np.asarray(fa)+[0,0,dz],'x_j':np.asarray(fb)+[0,0,dz],'K':k,'B':B})
        module_cursor+=len(s.mods)
    from ..connection_stiffness import resolve_vertical_connection
    vertical=[];vertical_assembly_audit=[];resolved_vertical=resolve_vertical_connection(config.vertical_link);vk=np.diag(resolved_vertical.values)
    if any(resolved_vertical.values[3:]):raise RuntimeError('legacy sparse builder is translational-only; use Option C production backend')
    starts=np.cumsum([0]+[len(s.mods) for s in stores])
    # Canonical owner lookup.  Parser/spec/module list ordering is explicitly
    # irrelevant from this point onward.
    module_by_id=[]
    for si,s in enumerate(stores):
        owner={}
        for local_index,module in enumerate(s.mods):
            if module.module_id in owner:raise RuntimeError('FAIL_VERTICAL_LINK_ASSEMBLY_IDENTITY: duplicate module id')
            owner[module.module_id]=(module,module_offsets[starts[si]+local_index])
        module_by_id.append(owner)
    for si in range(len(stores)-1):
        parser=__import__('mscsolver._layout_parser_legacy',fromlist=['parse_layout']).parse_layout
        lower_p=parser(config.layout[si]);upper_p=parser(config.layout[si+1]);upper_by={(frozenset(p.cells),p.orientation):p for p in upper_p}
        for p in lower_p:
            up=upper_by.get((frozenset(p.cells),p.orientation))
            if up is None:continue
            try:lm,lmo=module_by_id[si][p.module_id];um,umo=module_by_id[si+1][up.module_id]
            except KeyError as error:raise RuntimeError('FAIL_VERTICAL_LINK_ASSEMBLY_IDENTITY: unresolved module owner') from error
            if lm.module_id!=p.module_id or um.module_id!=up.module_id:raise RuntimeError('FAIL_VERTICAL_LINK_ASSEMBLY_IDENTITY: resolved owner mismatch')
            for xs in ('W','E'):
                for ys in ('S','N'):
                    lower_key=('TOP','C',xs,ys,0);upper_key=('BOT','C',xs,ys,0)
                    a=lmo+lm.port_metadata[lower_key];b=umo+um.port_metadata[upper_key]
                    step=stores[si].cfg.clear_storey_height+2*stores[si].cfg.column_end_offset
                    xa=np.asarray(lm.node_coordinates[lower_key[:-1]],float)+[0,0,si*step];xb=np.asarray(um.node_coordinates[upper_key[:-1]],float)+[0,0,(si+1)*step]
                    if np.linalg.norm(xa-xb)>1e-8:raise RuntimeError('FAIL_VERTICAL_LINK_ASSEMBLY_IDENTITY: endpoint coordinate mismatch')
                    lower_dofs=[a+d for d in range(3)];upper_dofs=[b+d for d in range(3)];ids=lower_dofs+upper_dofs;B3=np.c_[-np.eye(3),np.eye(3)];_add(rK,cK,dK,ids,B3.T@vk[:3,:3]@B3)
                    link_id=f'V{si+1}_{p.orientation}{p.module_id:02d}_{xs}{ys}';audit={'link_id':link_id,'lower_storey':si+1,'upper_storey':si+2,'lower_module_id':p.module_id,'upper_module_id':up.module_id,'corner_id':xs+ys,'lower_dof_indices':list(range(a,a+6)),'upper_dof_indices':list(range(b,b+6)),'lower_dof_owner':lm.module_id,'upper_dof_owner':um.module_id,'lower_port_role':'TOP','upper_port_role':'BOT','x_lower':xa.tolist(),'x_upper':xb.tolist()};vertical_assembly_audit.append(audit)
                    vertical.append({'id':link_id,'i':a,'j':b,'K':vk,'endpoint_dofs':(lower_dofs+[-1]*3,upper_dofs+[-1]*3),'identity':audit})
    K=sparse.coo_matrix((dK,(rK,cK)),shape=(N,N)).tocsr();M=sparse.coo_matrix((dM,(rM,cM)),shape=(N,N)).tocsr();K.sum_duplicates();M.sum_duplicates()
    fixed=[];top=[]
    for m,mo,si in zip(modules,module_offsets,module_storeys):
        for key,index in m.port_metadata.items():
            if si==1 and key[0]=='BOT':fixed.append(mo+index)
            if key[0]=='TOP' and key[-1] in (0,1):top.append((mo+index,m.node_coordinates[key[:-1]],key[-1],si))
    removed=set(fixed+[x[0] for x in top]);free=[i for i in range(N) if i not in removed];macro=np.arange(len(free),len(free)+3*config.storeys).reshape(config.storeys,3);ar=[];ac=[];ad=[]
    for j,i in enumerate(free):ar.append(i);ac.append(j);ad.append(1.)
    xref,yref=map(float,config.data['reference_point'])
    for i,p,d,si in top:
        ar.append(i);ac.append(int(macro[si-1,d]));ad.append(1.);ar.append(i);ac.append(int(macro[si-1,2]));ad.append(float(-(p[1]-yref) if d==0 else p[0]-xref))
    A=sparse.coo_matrix((ad,(ar,ac)),shape=(N,len(free)+3*config.storeys)).tocsr();Kr=(A.T@K@A).tocsr();Mr=(A.T@M@A).tocsr();corrections=[];rr=[];cc=[];dk=[];dm=[]
    for m,mo,si in zip(modules,module_offsets,module_storeys):
        Q=A[mo:mo+len(m.K_port)];cols=np.unique(Q.indices);Qloc=Q[:,cols].toarray();Kii=m.K_full[np.ix_(m.internal_dof_indices,m.internal_dof_indices)];inv=np.linalg.inv(Kii);keys=list(m.node_coordinates);topr=[6*i+5 for i,k in enumerate(keys) if k[0]=='TOP'];pos={int(v):i for i,v in enumerate(m.internal_dof_indices)};S=np.zeros((4,len(m.internal_dof_indices)))
        for row,index in enumerate(topr):S[row,pos[index]]=1.
        desired=np.zeros((4,len(cols)));rz=np.where(cols==macro[si-1,2])[0];desired[:,rz[0]]=1.;C=S@m.recovery_operator@Qloc-desired;W=np.linalg.inv(S@inv@S.T);internal=m.recovery_operator@Qloc-inv@S.T@W@C;Tm=np.zeros((len(m.K_full),len(cols)));Tm[m.retained_dof_indices]=Qloc;Tm[m.internal_dof_indices]=internal;deltaK=Tm.T@m.K_full@Tm-Qloc.T@m.K_port@Qloc;deltaM=Tm.T@m.M_full_lumped@Tm-Qloc.T@m.M_port_lumped@Qloc;_add(rr,cc,dk,cols,deltaK);_add([],[],dm,[],np.empty((0,0))) if False else None
        ii,jj=np.nonzero(deltaM);rMloc=np.asarray(cols)[ii];cMloc=np.asarray(cols)[jj];corrections.append((cols,Tm));dm.extend(deltaM[ii,jj]);
        if 'rm' not in locals():rm=[];cm=[]
        rm.extend(rMloc);cm.extend(cMloc)
    Kr=(Kr+sparse.coo_matrix((dk,(rr,cc)),shape=Kr.shape)).tocsr();Mr=(Mr+sparse.coo_matrix((dm,(rm,cm)),shape=Mr.shape)).tocsr();Kr.sum_duplicates();Mr.sum_duplicates()
    mem=lambda X:X.data.nbytes+X.indices.nbytes+X.indptr.nbytes
    diag={'global_dofs':N,'constrained_solve_dofs':Kr.shape[0],'nnz_K':Kr.nnz,'nnz_M':Mr.nnz,'density_K':Kr.nnz/(Kr.shape[0]**2),'density_M':Mr.nnz/(Mr.shape[0]**2),'csr_K_bytes':mem(Kr),'csr_M_bytes':mem(Mr),'estimated_dense_K_bytes':8*N*N,'ordinary_internal_building_dofs':0,'module_port_dofs':sum(len(m.K_port) for m in modules),'horizontal_links':len(horizontal),'vertical_links':len(vertical),'vertical_assembly_identity_mismatch_count':0,'vertical_assembly_audit':vertical_assembly_audit,'assembly_s':perf_counter()-t0}
    return SparseFinitePortBuilding(K,M,A,Kr,Mr,modules,module_offsets,horizontal,vertical,np.asarray(fixed,int),macro.reshape(-1),corrections,module_storeys,diag)

class SparseFinitePortGlobalBackend:
    name='finite_port';solver_backend='FINITE_PORT_SUPERELEMENT';global_storage='sparse'
    def __init__(self,config):self.config=config;self.timings={}
    def build_building(self):
        b=build_sparse_building(self.config);self.last_building=b;self.timings['global_assembly_s']=b.diagnostics['assembly_s'];return b
    def solve_static(self,load_cases=None):
        from ..result import StaticResult
        b=self.build_building();names=load_cases or list(self.config.load_cases);diagonal=np.asarray(b.reduced_K.diagonal(),float);scale=np.ones_like(diagonal) if b.reduced_K.shape[0]<5000 else 1./np.sqrt(np.maximum(abs(diagonal),np.max(abs(diagonal))*1e-30));D=sparse.diags(scale);Ks=(D@b.reduced_K@D).tocsc();t=perf_counter();lu=splu(Ks,permc_spec='COLAMD' if b.reduced_K.shape[0]<5000 else 'MMD_AT_PLUS_A',diag_pivot_thresh=1. if b.reduced_K.shape[0]<5000 else 0.,options={'SymmetricMode':b.reduced_K.shape[0]>=5000});self.timings['static_factorization_s']=perf_counter()-t;mac=b.macro_dofs.reshape(self.config.storeys,3);storey={};disp={};hf={};vf={};react={};energy={};red={};res={};t=perf_counter()
        backward={};scaled_residuals={};stability={};refinement_history={}
        Kinf=float(np.max(np.asarray(abs(b.reduced_K).sum(axis=1)).ravel()))
        for name in names:
            j=('TH_UX','TH_UY','TH_RZ').index(name);f=np.zeros(b.reduced_K.shape[0]);f[mac[-1,j]]=1.;q=scale*lu.solve(scale*f);history=[q.copy()]
            for _ in range(3):q+=scale*lu.solve(scale*(f-b.reduced_K@q));history.append(q.copy())
            r=f-b.reduced_K@q;raw=float(np.linalg.norm(r)/np.linalg.norm(f));res[name]=raw
            backward[name]=float(np.linalg.norm(r,np.inf)/max(Kinf*np.linalg.norm(q,np.inf)+np.linalg.norm(f,np.inf),1e-300))
            y=np.divide(q,scale,out=np.zeros_like(q),where=scale!=0);fhat=scale*f
            scaled_residuals[name]=float(np.linalg.norm(Ks@y-fhat)/max(np.linalg.norm(fhat),1e-300))
            qa0,qb0=history[-2],history[-1];ua=b.constraint_transform@qa0;ub=b.constraint_transform@qb0
            dua=qa0[mac[-1]];dub=qb0[mac[-1]];ea=.5*qa0@(b.reduced_K@qa0);eb=.5*qb0@(b.reduced_K@qb0)
            force_a=[];force_b=[]
            for link in b.horizontal_links+b.vertical_links:
                force_a.extend(link['K']@_connection_deformation(link,ua));force_b.extend(link['K']@_connection_deformation(link,ub))
            force_a=np.asarray(force_a);force_b=np.asarray(force_b);link_change=float(np.linalg.norm(force_b-force_a)/max(np.linalg.norm(force_b),np.linalg.norm(f),1e-300))
            stability[name]=max(float(np.linalg.norm(dub-dua)/max(np.linalg.norm(dub),1e-300)),float(abs(eb-ea)/max(abs(eb),1e-300)),link_change)
            refinement_history[name]=[float(np.linalg.norm(f-b.reduced_K@x)/np.linalg.norm(f)) for x in history]
            u=b.constraint_transform@q;red[name]=q;disp[name]=u;storey[name]=[{'ux_bar':float(q[x[0]]),'uy_bar':float(q[x[1]]),'theta_z_bar':float(q[x[2]]),'distortion_norm':0.,'distortion_ratio':0.} for x in mac];energy[name]=float(.5*q@(b.reduced_K@q));react[name]=(b.K@u)[b.fixed_dofs];res[name]=float(np.linalg.norm(b.reduced_K@q-f)/np.linalg.norm(f));hf[name]={x['id']:x['K']@_connection_deformation(x,u) for x in b.horizontal_links};vf[name]={x['id']:x['K']@_connection_deformation(x,u) for x in b.vertical_links}
        self.timings['static_3rhs_s']=perf_counter()-t;self.last_reduced_static=red
        qa=dict(b.diagnostics,static_residuals=res,raw_relative_residuals=res,normwise_backward_errors=backward,scaled_system_residuals=scaled_residuals,solution_stability=stability,refinement_raw_residual_history=refinement_history,numerical_qa_thresholds={'normwise_backward_error':1e-10,'solution_stability':1e-6},passed=max(backward.values())<=1e-10 and max(stability.values())<=1e-6)
        return StaticResult(storey,disp,hf,vf,react,energy,qa)
    def solve_modal(self,num_modes=3,mass_model='lumped'):
        from ..result import ModalResult
        b=self.build_building();t=perf_counter()
        diag=np.asarray(abs(b.reduced_M).sum(axis=1)).ravel();D=np.where(diag>max(diag.max()*1e-14,1e-18))[0];Z=np.where(diag<=max(diag.max()*1e-14,1e-18))[0]
        modal_path='explicit_sparse_schur';estimated_entries=0
        if len(Z):
            Kdd=b.reduced_K[D][:,D];Kdz=b.reduced_K[D][:,Z];Kzd=b.reduced_K[Z][:,D];Kzz=b.reduced_K[Z][:,Z].tocsr();Meff=b.reduced_M[D][:,D]
            ncomp,labels=connected_components(Kzz,directed=False);parts=[]
            for component in range(ncomp):
                zi=np.where(labels==component)[0];local_zd=Kzd[zi].tocsr();di=np.unique(local_zd.indices)
                if len(di):parts.append((zi,di));estimated_entries+=len(di)**2
            zdiag=np.asarray(abs(Kzz.diagonal()),float);zscale=1./np.sqrt(np.maximum(zdiag,max(zdiag.max(),1.)*1e-30));Zs=sparse.diags(zscale);zlu=splu((Zs@Kzz@Zs).tocsc())
            def zsolve(rhs):
                rhs=np.asarray(rhs)
                return zscale*zlu.solve(zscale*rhs) if rhs.ndim==1 else zscale[:,None]*zlu.solve(zscale[:,None]*rhs)
            full_diag=np.asarray(abs(b.reduced_K.diagonal()),float);positive_diag=full_diag[full_diag>0];diagonal_dynamic_range=float(positive_diag.max()/positive_diag.min())
            if estimated_entries<=5_000_000 and diagonal_dynamic_range<=1e12:
                correction=sparse.csr_matrix(Kdd.shape)
                for zi,di in parts:
                    azd=Kzd[zi][:,di].toarray();azz=Kzz[zi][:,zi].toarray();local=azd.T@np.linalg.solve(azz,azd);correction+=sparse.coo_matrix((local.ravel(),(np.repeat(di,len(di)),np.tile(di,len(di)))),shape=Kdd.shape).tocsr()
                Keff=(Kdd-correction).tocsr();Keff.eliminate_zeros()
                def keff_action(x):return Keff@x
                scale_diagonal=Keff.diagonal();keff_nnz=Keff.nnz
            else:
                modal_path='matrix_free_exact_schur'
                def keff_action(x):return Kdd@x-Kdz@zsolve(Kzd@x)
                Keff=LinearOperator(Kdd.shape,matvec=keff_action,matmat=keff_action,dtype=float);scale_diagonal=Kdd.diagonal();keff_nnz=None
        else:
            Keff=b.reduced_K;Meff=b.reduced_M
            def keff_action(x):return Keff@x
            scale_diagonal=Keff.diagonal();keff_nnz=Keff.nnz
        scale=1./np.sqrt(np.maximum(abs(scale_diagonal),1e-300));S=sparse.diags(scale);Ms=(S@Meff@S).tocsr()
        if modal_path=='matrix_free_exact_schur':
            def scaled_action(x):
                x=np.asarray(x);return scale[:,None]*keff_action(scale[:,None]*x) if x.ndim==2 else scale*keff_action(scale*x)
            Ks=LinearOperator(Kdd.shape,matvec=scaled_action,matmat=scaled_action,dtype=float);full_scale=1./np.sqrt(np.maximum(full_diag,max(full_diag.max(),1.)*1e-30));Fs=sparse.diags(full_scale);flu=splu((Fs@b.reduced_K@Fs).tocsc(),permc_spec='MMD_AT_PLUS_A',diag_pivot_thresh=0.,options={'SymmetricMode':True});invscale=1./scale
            def inverse(x):
                x=np.asarray(x)
                if x.ndim==1:
                    rhs=np.zeros(b.reduced_K.shape[0]);rhs[D]=invscale*x;q=full_scale*flu.solve(full_scale*rhs);return invscale*q[D]
                rhs=np.zeros((b.reduced_K.shape[0],x.shape[1]));rhs[D]=invscale[:,None]*x;q=full_scale[:,None]*flu.solve(full_scale[:,None]*rhs);return invscale[:,None]*q[D]
            OP=LinearOperator(Kdd.shape,matvec=inverse,matmat=inverse,dtype=float);candidate_values,candidate_y=eigsh(Ks,k=max(num_modes+6,9),M=Ms,sigma=0.,which='LM',OPinv=OP,tol=1e-11,maxiter=10000,ncv=min(max(4*(num_modes+6)+1,40),len(D)-1))
        else:
            Ks=(S@Keff@S).tocsr();candidate_values,candidate_y=eigsh(Ks,k=max(num_modes+6,9),M=Ms,sigma=0.,which='LM',tol=1e-11,maxiter=10000,ncv=min(max(4*(num_modes+6)+1,40),len(D)-1))
        order=np.argsort(candidate_values);candidate_values=candidate_values[order];candidate_v=scale[:,None]*candidate_y[:,order];accepted=[];candidate_residuals=[]
        for i,value in enumerate(candidate_values):
            v0=candidate_v[:,i];kv=keff_action(v0);mv=Meff@v0;r=float(np.linalg.norm(kv-value*mv)/max(np.linalg.norm(kv)+abs(value)*np.linalg.norm(mv),1e-30));candidate_residuals.append(r)
            if value>0 and r<1e-4:accepted.append(i)
        if len(accepted)<num_modes:raise RuntimeError(f'sparse modal returned only {len(accepted)} numerically physical modes; residuals={candidate_residuals}')
        take=accepted[:num_modes];values=candidate_values[take];v=candidate_v[:,take];q=np.zeros((b.reduced_K.shape[0],num_modes));q[D]=v
        if len(Z):q[Z]=-zsolve(Kzd@v)
        phi=b.constraint_transform@q;macro=q[b.macro_dofs];types=[];L=float(self.config.module_geometry['long_outer_mm'])
        for x in macro.T:types.append(('X-dominant','Y-dominant','RZ-dominant')[int(np.argmax((np.linalg.norm(x[0::3]),np.linalg.norm(x[1::3]),np.linalg.norm(x[2::3])*L)))])
        w=np.sqrt(values);self.timings['modal_solve_s']=perf_counter()-t;res=[]
        for i in range(num_modes):
            kq=b.reduced_K@q[:,i];mq=b.reduced_M@q[:,i];res.append(float(np.linalg.norm(kq-values[i]*mq)/max(np.linalg.norm(kq)+abs(values[i])*np.linalg.norm(mq),1e-30)))
        gram=q.T@(b.reduced_M@q);qa=dict(b.diagnostics,zero_mass_dofs=len(Z),K_eff_dofs=len(D),K_eff_nnz=keff_nnz,K_eff_estimated_entries=estimated_entries,modal_path=modal_path,diagonal_dynamic_range=diagonal_dynamic_range if len(Z) else float(np.max(abs(scale_diagonal))/max(np.min(abs(scale_diagonal)),1e-300)),modal_candidate_residuals=candidate_residuals,modal_residuals=res,M_orthogonality_error=float(np.linalg.norm(gram-np.eye(num_modes))),passed=np.all(np.isfinite(values)) and max(res)<1e-4);return ModalResult(values,w,w/(2*np.pi),2*np.pi/w,phi,macro,types,mass_model,qa)
