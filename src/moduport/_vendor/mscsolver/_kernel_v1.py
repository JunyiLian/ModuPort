"""A18-D formal bare modular frame solver release v1.

Default boundary: FREE_BARE_FRAME.  Nonzero two-joint Links always use the
finite-length rigid-chord mapping d_J-H(r_IJ)d_I.  No SAP dependency.
"""
from __future__ import annotations
import csv,hashlib,json,time,warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import numpy as np
from scipy.linalg import block_diag
from scipy.sparse import csc_matrix
from scipy.sparse.linalg import spsolve

from . import _module_layout as mm
from . import _finite_port as fp
from ._layout_parser_legacy import parse_layout

FREE_BARE_FRAME='FREE_BARE_FRAME';IN_PLANE_RIGID_BODY='IN_PLANE_RIGID_BODY'
BOUNDARY_MODES=(FREE_BARE_FRAME,IN_PLANE_RIGID_BODY)
RELEASE_NAME='bare_frame_solver_v1';LINK_MAPPING='FINITE_LENGTH_RIGID_CHORD'

def skew(r):
 x,y,z=map(float,r);return np.array(((0.,-z,y),(z,0.,-x),(-y,x,0.)))
def H(r):
 z=np.eye(6);z[:3,3:]=-skew(r);return z
def link_B(x_i,x_j,T=None):
 """Return 6x12 map for d_J-H(r_IJ)d_I in Link local axes."""
 T=np.eye(6) if T is None else np.asarray(T,float);B=np.zeros((6,12));B[:,:6]=-T@H(np.asarray(x_j)-np.asarray(x_i));B[:,6:]=T;return B
def link_matrix(x_i,x_j,k,T=None):
 B=link_B(x_i,x_j,T);return B.T@np.asarray(k,float)@B
def layout_hash(case):return hashlib.sha256(json.dumps(case,sort_keys=True,separators=(',',':')).encode()).hexdigest()

@dataclass
class Core:
 K:np.ndarray; ids:dict; coords:dict; frames:list
@dataclass
class Model:
 K:csc_matrix; coords:dict; dof:dict; fixed:np.ndarray; top:dict; bot:dict
 horizontal_links:list;vertical_links:list;module_count:int;H_count:int;V_count:int;layout_codes:list;boundary_mode:str

def _core(sp,extras,cfg):
 sec=cfg.sections();nodes=[];ids={};co={}
 def add(k,p):ids[k]=len(nodes);co[k]=np.asarray(p,float);nodes.append(co[k])
 for lev,z in (('FLOOR',0.),('CEIL',cfg.clear_storey_height)):
  for xs in ('W','E'):
   for ys in ('S','N'):add((lev,'C',xs,ys),tuple(fp._corner(sp,xs,ys,cfg))+(z,))
 for side,tans in extras.items():
  for t in sorted(tans):
   for lev,z in (('FLOOR',0.),('CEIL',cfg.clear_storey_height)):add((lev,'B',side,round(t,6)),fp._extra_xyz(sp,side,t,z,cfg))
 fr=[]
 for xs in ('W','E'):
  for ys in ('S','N'):fr.append((('FLOOR','C',xs,ys),('CEIL','C',xs,ys),sec['column'],'MAIN_COLUMN'))
 sides=(('S',('W','S'),('E','S')),('E',('E','S'),('E','N')),('N',('W','N'),('E','N')),('W',('W','S'),('W','N')))
 for lev in ('FLOOR','CEIL'):
  for side,a,b in sides:
   q=[(lev,'C',*a)]+[(lev,'B',side,round(t,6)) for t in sorted(extras.get(side,()))]+[(lev,'C',*b)]
   fr += [(i,j,fp._section_for_side(sp,lev,side,sec),lev+'_BEAM') for i,j in zip(q,q[1:])]
 K=np.zeros((6*len(nodes),6*len(nodes)))
 for a,b,s,_ in fr:
  ke=cfg._beam_function(co[a],co[b],s);d=list(range(6*ids[a],6*ids[a]+6))+list(range(6*ids[b],6*ids[b]+6));K[np.ix_(d,d)]+=ke
 return Core(K,ids,co,fr)

def _corner_key(sp,it,which,lev,cfg):
 side=getattr(it,'side_'+which);t=it.tangent;end=getattr(it,'endpoint_'+which)
 if end=='BEAM':return (lev,'B',side,round(t,6))
 if side in ('W','E'):return (lev,'C',side,'S' if abs(t-(sp.y0+cfg.column_half_mm))<1e-6 else 'N')
 return (lev,'C','W' if abs(t-(sp.x0+cfg.column_half_mm))<1e-6 else 'E',side)

def _storey(layout_code,cfg,storey):
 layout=parse_layout(layout_code);specs=fp._specs(layout,cfg);interfaces=fp.identify_layout_interfaces(layout,config=cfg);ex=fp._extras(interfaces);cores=[_core(sp,{side:t for (mid,side),t in ex.items() if mid==sp.module_id},cfg) for sp in specs]
 sizes=[len(c.K) for c in cores];offs=np.cumsum([0]+sizes[:-1]).tolist();n=sum(sizes)+24*len(interfaces)+48*len(cores);K=np.zeros((n,n));coords={};dof={};top=[];bot=[];hlinks=[]
 for off,sp,c in zip(offs,specs,cores):
  K[off:off+len(c.K),off:off+len(c.K)]=c.K
  for key,i in c.ids.items():
   lev=key[0];suffix=(key[2]+key[3] if key[1]=='C' else f'{key[2]}_T_{key[3]}');name=f'S{storey}_{sp.orientation}{sp.module_id:02d}_{suffix}_{lev}';coords[name]=c.coords[key]+(0,0,(storey-1)*3157.);dof[name]=off+6*i
 cursor=sum(sizes);armsec=mm.Section(2e6,2e6/(2*1.3),250000.,500**4/12,500**4/12,.1406*500**4);by={s.module_id:i for i,s in enumerate(specs)}
 for it in interfaces:
  ia,ib=by[it.module_a],by[it.module_b]
  for lev in ('FLOOR','CEIL'):
   ka=_corner_key(specs[ia],it,'a',lev,cfg);kb=_corner_key(specs[ib],it,'b',lev,cfg);xa=cores[ia].coords[ka];xb=cores[ib].coords[kb];fa=fp._face(it,True,lev,cfg);fb=fp._face(it,False,lev,cfg);aa,ab=cursor,cursor+6;cursor+=12
   for x0,x1,coff,aoff in ((xa,fa,offs[ia]+6*cores[ia].ids[ka],aa),(xb,fb,offs[ib]+6*cores[ib].ids[kb],ab)):
    ke=cfg._beam_function(x0,x1,armsec);dd=list(range(coff,coff+6))+list(range(aoff,aoff+6));K[np.ix_(dd,dd)]+=ke
   T=fp.connection_transformation(it);dd=list(range(aa,aa+6))+list(range(ab,ab+6));K[np.ix_(dd,dd)]+=link_matrix(fa,fb,cfg.horizontal_connection.matrix(),T)
   hlinks.append({'id':f'S{storey}_H{it.index}_{lev}','i':aa,'j':ab,'x_i':fa+(0,0,(storey-1)*3157.),'x_j':fb+(0,0,(storey-1)*3157.),'K':cfg.horizontal_connection.matrix(),'T':T})
 for off,sp,c in zip(offs,specs,cores):
  for xs in ('W','E'):
   for ys in ('S','N'):
    for lev,z,struct in [('BOT',-78.5,('FLOOR','C',xs,ys)),('TOP',3078.5,('CEIL','C',xs,ys))]:
     base=cursor;cursor+=6;p=c.coords[struct].copy();p[2]=z;st=off+6*c.ids[struct];a,b=(p,c.coords[struct]) if lev=='BOT' else (c.coords[struct],p);ke=cfg._beam_function(a,b,cfg.sections()['column']);dd=list(range(base,base+6))+list(range(st,st+6));K[np.ix_(dd,dd)]+=ke;name=f'S{storey}_{sp.orientation}{sp.module_id:02d}_{xs}{ys}_{lev}';coords[name]=p+(0,0,(storey-1)*3157.);dof[name]=base;(bot if lev=='BOT' else top).append(name)
 return K,coords,dof,top,bot,hlinks,specs

def build_model(case,config=None,boundary_mode=None):
 mode=boundary_mode or FREE_BARE_FRAME
 if mode not in BOUNDARY_MODES:raise ValueError('unsupported boundary_mode')
 if mode==IN_PLANE_RIGID_BODY:warnings.warn('Historical rigid-floor limiting mode; exclude from bare-frame studies',RuntimeWarning)
 cfg=config or mm.ModelConfig();cfg._beam_function=mm.beam3d_global_stiffness
 codes=case['storey_layouts'];parts=[_storey(code,cfg,s+1) for s,code in enumerate(codes)];Ks=[p[0] for p in parts];K=block_diag(*Ks);offs=np.cumsum([0]+[len(x) for x in Ks[:-1]]);coords={};dof={};top={};bot={};hl=[];specall=[]
 for s,(off,p) in enumerate(zip(offs,parts),1):
  _,co,dm,tp,bt,links,ss=p;coords.update(co);dof.update({n:off+i for n,i in dm.items()});top[s]=tp;bot[s]=bt;specall+=ss
  for z in links:y=dict(z);y['i']+=off;y['j']+=off;hl.append(y)
 vl=[];vk=cfg.vertical_connection.matrix()
 for s in range(1,len(parts)):
  up={(round(coords[n][0],6),round(coords[n][1],6)):n for n in bot[s+1]}
  for a in top[s]:
   key=(round(coords[a][0],6),round(coords[a][1],6))
   if key in up:
    b=up[key];ia,ib=dof[a],dof[b];dd=list(range(ia,ia+6))+list(range(ib,ib+6));K[np.ix_(dd,dd)]+=link_matrix(coords[a],coords[b],vk);vl.append({'id':f'V{s}_{a}_{b}','i':ia,'j':ib,'x_i':coords[a],'x_j':coords[b],'K':vk,'T':np.eye(6)})
 fixed=np.array([dof[n]+j for n in bot[1] for j in range(3)],int)
 return Model(csc_matrix(K),coords,dof,fixed,top,bot,hl,vl,len(specall),sum(s.orientation=='H' for s in specall),sum(s.orientation=='V' for s in specall),codes,mode)

def top_loads(model,case_name,reference_point=None):
 s=max(model.top);nodes=model.top[s];x0,y0=reference_point or tuple(np.mean([model.coords[n][:2] for n in nodes],axis=0));R=np.zeros((2*len(nodes),3))
 for i,n in enumerate(nodes):x,y,_=model.coords[n];R[2*i]=(1,0,-(y-y0));R[2*i+1]=(0,1,x-x0)
 v={'TH_UX':(1,0,0),'TH_UY':(0,1,0),'TH_RZ':(0,0,1)}[case_name];q=R@np.linalg.solve(R.T@R,np.asarray(v,float));return [{'joint_name':n,'Fx':q[2*i],'Fy':q[2*i+1],'Fz':0.,'Mx':0.,'My':0.,'Mz':0.} for i,n in enumerate(nodes)]
def solve(model,loads):
 f=np.zeros(model.K.shape[0])
 for z in loads:
  i=model.dof[z['joint_name']];f[i:i+6]+=[z.get(k,0.) for k in ('Fx','Fy','Fz','Mx','My','Mz')]
 free=np.setdiff1d(np.arange(len(f)),model.fixed);u=np.zeros(len(f));K=model.K[free][:,free]
 if model.boundary_mode==FREE_BARE_FRAME:u[free]=spsolve(K,f[free]);res=np.linalg.norm((model.K@u-f)[free])/max(np.linalg.norm(f[free]),1e-30)
 else:
  pos={g:i for i,g in enumerate(free)};rows=[]
  for nodes in model.top.values():
   master=nodes[0];bm=model.dof[master];xm,ym,_=model.coords[master]
   for n in nodes[1:]:
    b=model.dof[n];x,y,_=model.coords[n]
    for terms in ({b:1.,bm:-1.,bm+5:y-ym},{b+1:1.,bm+1:-1.,bm+5:-(x-xm)}):
     r=np.zeros(len(free))
     for g,v in terms.items():
      if g in pos:r[pos[g]]=v
     rows.append(r)
  C=np.asarray(rows);A=np.block([[K.toarray(),C.T],[C,np.zeros((len(C),len(C)))]]) if len(C) else K.toarray();rhs=np.r_[f[free],np.zeros(len(C))] if len(C) else f[free];z=np.linalg.solve(A,rhs);u[free]=z[:len(free)];res=np.linalg.norm(A@z-rhs)/max(np.linalg.norm(rhs),1e-30)
 return u,float(res)
def project(model,u,storey,reference_point=None):
 n=model.top[storey];return fp_result(np.array([model.coords[x] for x in n]),np.array([u[model.dof[x]:model.dof[x]+3] for x in n]),reference_point)
def fp_result(coords,disp,reference_point=None):
 x0,y0=reference_point or tuple(coords[:,:2].mean(axis=0));A=np.zeros((2*len(coords),3));v=np.zeros(2*len(coords))
 for i,((x,y,_),d) in enumerate(zip(coords,disp)):A[2*i]=(1,0,-(y-y0));A[2*i+1]=(0,1,x-x0);v[2*i:2*i+2]=d[:2]
 q=np.linalg.lstsq(A,v,rcond=None)[0];r=v-A@q;dn=np.linalg.norm(v);return {'ux_bar':q[0],'uy_bar':q[1],'theta_z_bar':q[2],'distortion_norm':np.linalg.norm(r),'distortion_ratio':np.linalg.norm(r)/max(dn,1e-30),'RMS_projection_residual':np.sqrt(np.mean(r*r)),'max_projection_residual':np.max(abs(r))}
def case_result(case,config=None,boundary_mode=None):
 if config is None:
  hk=case.get('horizontal_link_stiffness',{});vk=case.get('vertical_link_stiffness',{});hv=lambda d,n:mm.ConnectionStiffness(n,*[float(d.get(k,0.)) for k in ('ku1','ku2','ku3','kr1','kr2','kr3')]);config=mm.ModelConfig(grid_rows=int(case['grid_rows']),grid_cols=int(case['grid_cols']),storeys=int(case['storey_count']),horizontal_connection=hv(hk,'HORIZONTAL'),vertical_connection=hv(vk,'VERTICAL'))
 t0=time.perf_counter();m=build_model(case,config,boundary_mode);responses={};F=[]
 for lc in ('TH_UX','TH_UY','TH_RZ'):
  u,res=solve(m,top_loads(m,lc,case.get('reference_point')));responses[lc]={'u':u,'residual':res,'storeys':[project(m,u,s,case.get('reference_point')) for s in range(1,len(m.top)+1)]};roof=responses[lc]['storeys'][-1];F.append([roof['ux_bar'],roof['uy_bar'],roof['theta_z_bar']])
 flex=np.column_stack(F);stiff=np.linalg.inv(flex);sym=np.linalg.norm(stiff-stiff.T)/max(np.linalg.norm(stiff),1.);return {'case_id':case['case_id'],'case_hash':layout_hash(case),'model':m,'responses':responses,'projected_generalized_flexibility':flex,'projected_generalized_stiffness':stiff,'solve_seconds':time.perf_counter()-t0,'symmetry_error':sym}
def validate_case(case):
 req=('case_id','grid_rows','grid_cols','occupied_cells','module_orientations','storey_count','storey_layouts','horizontal_link_stiffness','vertical_link_stiffness','material_properties','section_properties','load_cases','reference_point','output_options');missing=[x for x in req if x not in case]
 if missing:raise ValueError('missing fields '+','.join(missing))
 if any(x not in ('H','V') for x in case['module_orientations']):raise ValueError('module orientation must be H or V')
 if len(case['storey_layouts'])!=int(case['storey_count']):raise ValueError('storey_layouts length mismatch')
 return True
def run_bare_frame_batch(case_database,solver_config,output_directory,parallel=False,resume=True,random_seed=None):
 """Run JSON/CSV/list cases; isolate failures and skip completed case hashes."""
 if parallel:warnings.warn('v1 uses deterministic serial execution; parallel flag accepted but disabled')
 if isinstance(case_database,(str,Path)):
  p=Path(case_database);cases=json.loads(p.read_text()) if p.suffix.lower()=='.json' else list(csv.DictReader(p.open(encoding='utf-8-sig')))
  if p.suffix.lower()=='.csv':
   nested=('occupied_cells','module_orientations','storey_layouts','horizontal_link_stiffness','vertical_link_stiffness','material_properties','section_properties','load_cases','reference_point','output_options')
   for c in cases:
    for k in nested:
     if k in c and isinstance(c[k],str):c[k]=json.loads(c[k])
    for k in ('grid_rows','grid_cols','storey_count'):c[k]=int(c[k])
 else:cases=list(case_database)
 out=Path(output_directory);out.mkdir(parents=True,exist_ok=True);donefile=out/'batch_state.json';done=json.loads(donefile.read_text()) if resume and donefile.exists() else {};results=[];fail=[]
 for case in cases:
  try:
   validate_case(case);h=layout_hash(case)
   if h in done:results.append(done[h]);continue
   r=case_result(case,boundary_mode=solver_config.get('boundary_mode',FREE_BARE_FRAME));z={'case_id':case['case_id'],'case_hash':h,'solve_status':'SUCCESS','global_DOF_count':r['model'].K.shape[0],'module_count':r['model'].module_count,'H_count':r['model'].H_count,'V_count':r['model'].V_count,'solve_seconds':r['solve_seconds'],'random_seed':random_seed};done[h]=z;results.append(z);donefile.write_text(json.dumps(done,indent=2))
  except Exception as e:fail.append({'case_id':case.get('case_id','UNKNOWN'),'error':repr(e)})
 return results,fail
