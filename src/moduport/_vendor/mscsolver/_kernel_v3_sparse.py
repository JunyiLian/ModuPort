"""A18-E sparse backend for the validated bare-frame v1 formulation."""
from __future__ import annotations
import hashlib,json,time
from dataclasses import dataclass
from pathlib import Path
import numpy as np
from scipy.sparse import coo_matrix,csc_matrix,diags
from scipy.sparse.linalg import splu

from . import _kernel_v1 as v1
mm=v1.mm;fp=v1.fp
FREE_BARE_FRAME=v1.FREE_BARE_FRAME
RELEASE_NAME='bare_frame_solver_v3_sparse';MATRIX_BACKEND='SPARSE_COO_CSC';FORMULATION_CHANGED=False

@dataclass
class SparseModel:
 K:csc_matrix;coords:dict;dof:dict;fixed:np.ndarray;top:dict;bot:dict
 horizontal_links:list;vertical_links:list;module_count:int;H_count:int;V_count:int;layout_codes:list;boundary_mode:str
 frame_count:int;assembly_seconds:float

class Triplets:
 def __init__(self):self.r=[];self.c=[];self.v=[]
 def add(self,dofs,ke):
  z=np.asarray(ke,float);ii,jj=np.nonzero(z)
  d=np.asarray(dofs,int);self.r.extend(d[ii]);self.c.extend(d[jj]);self.v.extend(z[ii,jj])
 def matrix(self,n):
  K=coo_matrix((self.v,(self.r,self.c)),shape=(n,n)).tocsc();K.sum_duplicates();K.eliminate_zeros();return K

def _prepared_storey(code,cfg):
 layout=v1.parse_layout(code);specs=fp._specs(layout,cfg);interfaces=fp.identify_layout_interfaces(layout,config=cfg);ex=fp._extras(interfaces)
 cores=[v1._core(sp,{side:t for (mid,side),t in ex.items() if mid==sp.module_id},cfg) for sp in specs]
 sizes=[len(c.K) for c in cores];n=sum(sizes)+24*len(interfaces)+48*len(cores)
 return specs,interfaces,cores,sizes,n

def build_model(case,config=None,boundary_mode=None):
 if (boundary_mode or FREE_BARE_FRAME)!=FREE_BARE_FRAME:raise ValueError('v2 sparse formal release supports FREE_BARE_FRAME only')
 cfg=config
 if cfg is None:
  hv=lambda d,n:mm.ConnectionStiffness(n,*[float(d.get(k,0.)) for k in ('ku1','ku2','ku3','kr1','kr2','kr3')])
  cfg=mm.ModelConfig(grid_rows=int(case['grid_rows']),grid_cols=int(case['grid_cols']),storeys=int(case['storey_count']),horizontal_connection=hv(case['horizontal_link_stiffness'],'HORIZONTAL'),vertical_connection=hv(case['vertical_link_stiffness'],'VERTICAL'))
 cfg._beam_function=mm.beam3d_global_stiffness;t0=time.perf_counter();prep=[_prepared_storey(x,cfg) for x in case['storey_layouts']]
 sn=[x[4] for x in prep];so=np.cumsum([0]+sn[:-1]).tolist();N=sum(sn);A=Triplets();coords={};dof={};tops={};bots={};hl=[];vl=[];all_specs=[];frames=0
 armsec=mm.Section(2e6,2e6/(2*1.3),250000.,500**4/12,500**4/12,.1406*500**4)
 for storey,(g0,(specs,interfaces,cores,sizes,_)) in enumerate(zip(so,prep),1):
  offs=np.cumsum([0]+sizes[:-1]).tolist();cursor=sum(sizes);top=[];bot=[];all_specs+=specs;by={s.module_id:i for i,s in enumerate(specs)}
  for off,sp,c in zip(offs,specs,cores):
   A.add(np.arange(g0+off,g0+off+len(c.K)),c.K);frames+=len(c.frames)
   for key,i in c.ids.items():
    lev=key[0];suffix=(key[2]+key[3] if key[1]=='C' else f'{key[2]}_T_{key[3]}');name=f'S{storey}_{sp.orientation}{sp.module_id:02d}_{suffix}_{lev}'
    coords[name]=c.coords[key]+(0,0,(storey-1)*3157.);dof[name]=g0+off+6*i
  for it in interfaces:
   ia,ib=by[it.module_a],by[it.module_b]
   for lev in ('FLOOR','CEIL'):
    ka=v1._corner_key(specs[ia],it,'a',lev,cfg);kb=v1._corner_key(specs[ib],it,'b',lev,cfg);xa=cores[ia].coords[ka];xb=cores[ib].coords[kb]
    fa=fp._face(it,True,lev,cfg);fb=fp._face(it,False,lev,cfg);aa=g0+cursor;ab=aa+6;cursor+=12
    ca=g0+offs[ia]+6*cores[ia].ids[ka];cb=g0+offs[ib]+6*cores[ib].ids[kb]
    A.add(list(range(ca,ca+6))+list(range(aa,aa+6)),cfg._beam_function(xa,fa,armsec));frames+=1
    A.add(list(range(cb,cb+6))+list(range(ab,ab+6)),cfg._beam_function(xb,fb,armsec));frames+=1
    T=fp.connection_transformation(it);A.add(list(range(aa,aa+6))+list(range(ab,ab+6)),v1.link_matrix(fa,fb,cfg.horizontal_connection.matrix(),T))
    hl.append({'id':f'S{storey}_H{it.index}_{lev}','i':aa,'j':ab,'x_i':fa+(0,0,(storey-1)*3157.),'x_j':fb+(0,0,(storey-1)*3157.),'K':cfg.horizontal_connection.matrix(),'T':T})
  for off,sp,c in zip(offs,specs,cores):
   for xs in ('W','E'):
    for ys in ('S','N'):
     for lev,z,struct in [('BOT',-78.5,('FLOOR','C',xs,ys)),('TOP',3078.5,('CEIL','C',xs,ys))]:
      base=g0+cursor;cursor+=6;p=c.coords[struct].copy();p[2]=z;st=g0+off+6*c.ids[struct];a,b=p,c.coords[struct]
      A.add(list(range(base,base+6))+list(range(st,st+6)),cfg._beam_function(a,b,cfg.sections()['column']));frames+=1
      name=f'S{storey}_{sp.orientation}{sp.module_id:02d}_{xs}{ys}_{lev}';coords[name]=p+(0,0,(storey-1)*3157.);dof[name]=base;(bot if lev=='BOT' else top).append(name)
  if cursor!=sn[storey-1]:raise RuntimeError(f'DOF allocation mismatch storey {storey}: {cursor}!={sn[storey-1]}')
  tops[storey]=top;bots[storey]=bot
 vk=cfg.vertical_connection.matrix()
 for s in range(1,len(prep)):
  up={(round(coords[n][0],6),round(coords[n][1],6)):n for n in bots[s+1]}
  for a in tops[s]:
   key=(round(coords[a][0],6),round(coords[a][1],6))
   if key in up:
    b=up[key];ia,ib=dof[a],dof[b];A.add(list(range(ia,ia+6))+list(range(ib,ib+6)),v1.link_matrix(coords[a],coords[b],vk));vl.append({'id':f'V{s}_{a}_{b}','i':ia,'j':ib,'x_i':coords[a],'x_j':coords[b],'K':vk,'T':np.eye(6)})
 K=A.matrix(N);fixed=np.array([dof[n]+j for n in bots[1] for j in range(3)],int)
 return SparseModel(K,coords,dof,fixed,tops,bots,hl,vl,len(all_specs),sum(x.orientation=='H' for x in all_specs),sum(x.orientation=='V' for x in all_specs),case['storey_layouts'],FREE_BARE_FRAME,frames,time.perf_counter()-t0)

def load_vectors(model,case):
 F=np.zeros((model.K.shape[0],3));loadsets=[]
 for col,lc in enumerate(('TH_UX','TH_UY','TH_RZ')):
  L=v1.top_loads(model,lc,case.get('reference_point'));loadsets.append(L)
  for z in L:
   i=model.dof[z['joint_name']];F[i:i+6,col]+=[z.get(k,0.) for k in ('Fx','Fy','Fz','Mx','My','Mz')]
 return F,loadsets

def _matmat_longdouble(K,X):
 C=K.tocoo();Y=np.zeros((K.shape[0],X.shape[1]),dtype=np.longdouble);d=C.data.astype(np.longdouble)
 for j in range(X.shape[1]):np.add.at(Y[:,j],C.row,d*X[C.col,j].astype(np.longdouble))
 return Y

def solve_case(case,config=None):
 t0=time.perf_counter();m=build_model(case,config,FREE_BARE_FRAME);F,L=load_vectors(m,case);free=np.setdiff1d(np.arange(m.K.shape[0]),m.fixed);Kf=m.K[free][:,free].tocsc()
 ds=1./np.sqrt(np.maximum(Kf.diagonal(),np.finfo(float).tiny));D=diags(ds);Kscaled=(D@Kf@D).tocsc();Fs=D@F[free]
 tf=time.perf_counter();lu=splu(Kscaled,options={'Equil':True,'IterRefine':'DOUBLE'});factor=time.perf_counter()-tf;tb=time.perf_counter();Uf=D@lu.solve(Fs)
 back=time.perf_counter()-tb;U=np.zeros_like(F);U[free]=Uf
 responses={};G=[];qa=[]
 for col,lc in enumerate(('TH_UX','TH_UY','TH_RZ')):
  u=U[:,col];stores=[v1.project(m,u,s,case.get('reference_point')) for s in range(1,len(m.top)+1)];responses[lc]={'u':u,'storeys':stores};q=stores[-1];G.append([q['ux_bar'],q['uy_bar'],q['theta_z_bar']])
  rf=Kf@Uf[:,col]-F[free,col];rabs=float(np.linalg.norm(rf));rhs=rabs/(float(np.linalg.norm(F[free,col]))+np.finfo(float).eps)
  kn=float(np.max(np.asarray(abs(Kf).sum(axis=1)).ravel()));backerr=rabs/(kn*float(np.linalg.norm(Uf[:,col]))+float(np.linalg.norm(F[free,col]))+np.finfo(float).eps)
  strain=.5*float(u@(m.K@u));work=.5*float(u@F[:,col]);energy=abs(strain-work)/max(abs(strain),abs(work),np.finfo(float).eps);qa.append({'load_case':lc,'r_abs':rabs,'r_rhs':rhs,'r_back':backerr,'energy_error':energy})
 flex=np.column_stack(G);stiff=np.linalg.solve(flex,np.eye(3));sym=float(np.linalg.norm((m.K-m.K.T).data)/max(np.linalg.norm(m.K.data),1.))
 return {'case_id':case['case_id'],'case_hash':v1.layout_hash(case),'model':m,'responses':responses,'projected_generalized_flexibility':flex,'projected_generalized_stiffness':stiff,'qa':qa,'matrix_symmetry_error':sym,'factorization_reused':True,'rhs_count':3,'assembly_time':m.assembly_seconds,'factorization_time':factor,'backsolve_time':back,'total_runtime':time.perf_counter()-t0,'nnz':m.K.nnz,'fill_in_ratio':(lu.L.nnz+lu.U.nnz)/max(Kf.nnz,1),'diagonal_scaling':True}

def run_bare_frame_batch(cases,output_directory,resume=True):
 out=Path(output_directory);out.mkdir(parents=True,exist_ok=True);results=[];failed=[]
 for c in cases:
  p=out/(c['case_id']+'.json')
  if resume and p.exists():results.append(json.loads(p.read_text()));continue
  try:
   r=solve_case(c);z={k:v for k,v in r.items() if k not in ('model','responses','projected_generalized_flexibility','projected_generalized_stiffness')};z['flexibility']=r['projected_generalized_flexibility'].tolist();z['stiffness']=r['projected_generalized_stiffness'].tolist();p.write_text(json.dumps(z,separators=(',',':')),encoding='utf-8');results.append(z)
  except Exception as e:failed.append({'case_id':c.get('case_id'),'error':repr(e)})
 return results,failed
