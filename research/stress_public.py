"""Frozen public benchmark stress test. No paid API and no execution of source text."""
import argparse,gzip,hashlib,itertools,json,math,os,random,statistics as st,sys,time
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import highspy as hs
ROOT=Path(__file__).resolve().parents[1];SRC=ROOT/'datasets/stress-public-v1'
OUT=Path(os.environ.get('STRESS_OUT',str(ROOT/'outputs/inverse/public-stress-20261020-v2')))
CFG=ROOT/'research/stress_protocol.json'
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def save(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def seedkey(s):return int(hashlib.sha256(s.encode()).hexdigest()[:12],16)
STATS=Counter();DEADLINE=math.inf
def hsolver():
 h=hs.Highs()
 for k,v in {'output_flag':False,'threads':1,'time_limit':5.,'mip_rel_gap':0.,'mip_abs_gap':0.,'random_seed':17,'primal_feasibility_tolerance':1e-7}.items():h.setOptionValue(k,v)
 return h
def tick():
 if time.perf_counter()>DEADLINE:raise TimeoutError('inverse wall budget90s')
def runh(h):
 tick();before=h.getRunTime();status=h.run();STATS['solverRuns']+=1;STATS['solverSeconds']+=max(0,h.getRunTime()-before)
 return h.getModelStatus()
def sparse(A):
 starts=[0];idx=[];vals=[]
 for row in A:
  for j,v in enumerate(row):
   if v:idx.append(j);vals.append(v)
  starts.append(len(idx))
 return starts,idx,vals
def lpmodel(m,c):
 lp=hs.HighsLp();lp.num_col_=len(c);lp.num_row_=len(m['A']);lp.col_cost_=c
 lp.col_lower_=m['lb'];lp.col_upper_=m['ub'];lp.row_lower_=m['rl'];lp.row_upper_=m['ru']
 a,idx,v=sparse(m['A']);lp.a_matrix_.format_=hs.MatrixFormat.kRowwise;lp.a_matrix_.start_=a;lp.a_matrix_.index_=idx;lp.a_matrix_.value_=v
 if m['integer']:lp.integrality_=[hs.HighsVarType.kInteger]*len(c)
 return lp
def feasible(m,x,tol=2e-5):
 x=np.asarray(x);a=np.asarray(m['A'])@x
 good=min(x-np.asarray(m['lb']))>=-tol and min(np.asarray(m['ub'])-x)>=-tol and min(a-np.asarray(m['rl']))>=-tol and min(np.asarray(m['ru'])-a)>=-tol
 if m['integer']:good=good and max(abs(x-np.round(x)))<=tol
 if m['family']=='TSPLIB':good=good and len(components(m,x))==1
 return bool(good)
def components(m,x):
 adj=[[] for _ in range(m['cities'])]
 for (i,j),v in zip(m['edges'],x):
  if v>.5:adj[i].append(j);adj[j].append(i)
 remain=set(range(m['cities']));groups=[]
 while remain:
  stack=[min(remain)];comp=set()
  while stack:
   i=stack.pop()
   if i in comp:continue
   comp.add(i);stack.extend(j for j in adj[i] if j not in comp)
  remain-=comp;groups.append(comp)
 return groups
def solve(m,c,capcost=None,cap=None,maximize=False,limit=5):
 STATS['forwardCalls']+=1;c=np.asarray(c,float);h=hsolver();h.passModel(lpmodel(m,(-c if maximize else c).tolist()))
 if cap is not None:
  ix=np.flatnonzero(np.abs(capcost)>0);h.addRow(-hs.kHighsInf,float(cap)+1e-7,len(ix),ix,np.asarray(capcost)[ix])
 start=time.perf_counter()
 try:
  for iteration in range(200):
   tick();remaining=limit-(time.perf_counter()-start)
   if remaining<=0:raise TimeoutError('forward wall budget '+str(limit))
   h.setOptionValue('time_limit',remaining)
   status=runh(h)
   if status==hs.HighsModelStatus.kUnbounded:return None,None,'unbounded'
   if status!=hs.HighsModelStatus.kOptimal:raise RuntimeError('forward '+str(status))
   x=np.array(h.getSolution().col_value)
   if m['integer']:x=np.round(x)
   if m['family']=='TSPLIB':
    comps=components(m,x)
    if len(comps)>1:
     for comp in comps:
      ix=[j for j,(u,v) in enumerate(m['edges']) if u in comp and v in comp]
      h.addRow(-hs.kHighsInf,len(comp)-1,len(ix),ix,[1.]*len(ix));STATS['subtourCuts']+=1
     continue
   if not feasible(m,x):raise ValueError('forward solution violates original constraints')
   if cap is not None and np.dot(capcost,x)>cap+1e-5:raise ValueError('forward cap violation')
   return x,float(c@x),'optimal'
  raise TimeoutError('subtour cut limit')
 finally:STATS['forwardWallSeconds']+=time.perf_counter()-start

def parse_knap():
 ts=iter((SRC/'mknap1.txt').read_text().split());count=int(next(ts));models=[]
 for i in range(count):
  n,r,opt=int(next(ts)),int(next(ts)),float(next(ts));c=[-float(next(ts)) for _ in range(n)]
  A=[[float(next(ts)) for _ in range(n)] for _ in range(r)];b=[float(next(ts)) for _ in range(r)]
  models.append({'id':f'mknap1-{i+1}','family':'ORLIB','c':c,'A':A,'rl':[-1e30]*r,'ru':b,'lb':[0.]*n,'ub':[1.]*n,'integer':True,'publishedOptimum':-opt,'sourceFile':'mknap1.txt','originalSense':'maximize profit, converted to minimization of negative profit'})
 try:next(ts);raise ValueError('trailing knapsack tokens')
 except StopIteration:pass
 return models
def parse_netlib(name):
 h=hsolver()
 # HiGHS on Windows cannot open this workspace's Unicode absolute directory.
 # A relative ASCII file path preserves the exact same source bytes and model.
 if h.readModel(os.path.relpath(SRC/(name+'.mps'),Path.cwd()))==hs.HighsStatus.kError:raise ValueError('MPS load failed')
 lp=h.getLp();mat=lp.a_matrix_;A=np.zeros((lp.num_row_,lp.num_col_))
 if mat.format_==hs.MatrixFormat.kColwise:
  for j in range(lp.num_col_):
   for q in range(mat.start_[j],mat.start_[j+1]):A[mat.index_[q],j]=mat.value_[q]
 else:
  for i in range(lp.num_row_):
   for q in range(mat.start_[i],mat.start_[i+1]):A[i,mat.index_[q]]=mat.value_[q]
 if lp.sense_!=hs.ObjSense.kMinimize or lp.offset_!=0:raise ValueError('unsupported source objective sense/offset')
 clamp=lambda v:[float(np.clip(z,-1e30,1e30)) for z in v]
 return {'id':name,'family':'NETLIB','c':list(lp.col_cost_),'A':A.tolist(),'rl':clamp(lp.row_lower_),'ru':clamp(lp.row_upper_),'lb':clamp(lp.col_lower_),'ub':clamp(lp.col_upper_),'integer':False,'publishedOptimum':{'afiro':-464.75314286,'adlittle':225494.96316,'blend':-30.812149846}[name],'sourceFile':name+'.mps','originalSense':'minimize'}
def parse_tsp(name):
 text=gzip.decompress((SRC/(name+'.tsp.gz')).read_bytes()).decode();head,body=text.split('EDGE_WEIGHT_SECTION',1)
 n=int(next(line.split(':')[1] for line in head.splitlines() if line.startswith('DIMENSION')))
 if 'LOWER_DIAG_ROW' not in head:raise ValueError('unsupported TSPLIB format')
 tokens=[float(v) for v in body.replace('EOF','').split()]
 if len(tokens)!=n*(n+1)//2:raise ValueError('wrong triangular entry count')
 M=np.zeros((n,n));q=0
 for i in range(n):
  for j in range(i+1):M[i,j]=M[j,i]=tokens[q];q+=1
 if np.any(np.diag(M)):raise ValueError('nonzero diagonal')
 edges=list(itertools.combinations(range(n),2));A=np.zeros((n,len(edges)))
 for k,(i,j) in enumerate(edges):A[i,k]=A[j,k]=1
 return {'id':name,'family':'TSPLIB','c':[M[i,j] for i,j in edges],'A':A.tolist(),'rl':[2.]*n,'ru':[2.]*n,'lb':[0.]*len(edges),'ub':[1.]*len(edges),'integer':True,'cities':n,'edges':edges,'publishedOptimum':{'gr17':2085,'gr21':2707,'gr24':1272,'fri26':937}[name],'sourceFile':name+'.tsp.gz','originalSense':'minimize closed Hamiltonian tour'}

def audit():
 OUT.mkdir(parents=True,exist_ok=True)
 if (OUT/'models.json').exists():return
 save(OUT/'protocol.json',read(CFG));save(OUT/'protocol-freeze.json',{'utc':datetime.now(timezone.utc).isoformat(),'sha256':sha(CFG),'stage':'before inverse results'})
 models=[];records=[];knaps=parse_knap()
 for family,ids in read(CFG)['datasets'].items():
  for name in ids:
   r={'id':name,'family':family};t=time.perf_counter()
   try:
    m=next(x for x in knaps if x['id']==name) if family=='ORLIB' else parse_netlib(name) if family=='NETLIB' else parse_tsp(name)
    x,val,status=solve(m,m['c'],limit=30)
    if status!='optimal':raise ValueError(status)
    r.update(originalObjective=val,publishedOptimum=m['publishedOptimum'],variables=len(m['c']),constraints=len(m['A']))
    if abs(val-m['publishedOptimum'])>1e-5*max(1,abs(val)):raise ValueError('published optimum mismatch')
    m['sourceSha256']=sha(SRC/m['sourceFile']);r.update(status='admitted');models.append(m)
   except Exception as e:r.update(status='unavailable',error=str(e))
   r['wallSeconds']=time.perf_counter()-t;records.append(r);print(json.dumps(r),flush=True)
 save(OUT/'models.json',models);save(OUT/'source-audit.json',records)

def prepare(m,seed):
 cfg=read(CFG);rng=random.Random(seedkey(m['id'])+cfg['maskSeed'])
 available=[i for i,c in enumerate(m['c']) if abs(c)>1e-10]
 if len(available)<2:raise ValueError('fewer than2 nonzero costs')
 hidden=sorted(rng.sample(available,2));rest=[i for i in range(len(m['c'])) if i not in hidden];indices=hidden+rng.sample(rest,3)
 scale=st.median(abs(c) for i,c in enumerate(m['c']) if i not in hidden and abs(c)>1e-10)
 F=np.zeros((len(m['c']),5))
 for j,i in enumerate(indices):F[i,j]=1 if m['c'][i]>=0 else -1
 truth=[abs(m['c'][i])/scale for i in hidden]+[0.]*3
 rng=random.Random(seedkey(m['id'])+seed*100001);contexts=[]
 for k in range(20):
  base=[0 if i in hidden else c/scale*rng.uniform(.5,1.5) for i,c in enumerate(m['c'])]
  contexts.append({'context':f'{m["id"]}-s{seed}-c{k}','base':base,'aux':[rng.uniform(.1,1) for _ in base]})
 return {'id':m['id'],'family':m['family'],'seed':seed,'model':m,'scale':scale,'indices':indices,'F':F.tolist(),'truth':truth,'contexts':contexts,
         'logs':[f'原目标第{i}项的单位系数遗漏，符号已知，不提供数值。' for i in hidden]+[f'第{indices[2]}项可能另有同号附加代价。'],
         'templateCaveat':'oracle-supported controlled structure, no free-text claim','truthOutsideBox':any(v>10 for v in truth)}
def freeze():
 audit()
 if (OUT/'freeze.json').exists():
  f=read(OUT/'freeze.json')
  if sha(CFG)!=f['protocolSha256'] or sha(__file__)!=f['implementationSha256']:raise ValueError('frozen code or protocol changed')
  for n,s in f['files'].items():
   if sha(OUT/n)!=s:raise ValueError('frozen input changed '+n)
  return
 files=['protocol.json','models.json','source-audit.json']
 for m in read(OUT/'models.json'):
  for seed in read(CFG)['seeds']:
   n=f'inputs/{m["id"]}-s{seed}.json';save(OUT/n,prepare(m,seed));files.append(n)
 save(OUT/'freeze.json',{'utc':datetime.now(timezone.utc).isoformat(),'protocolSha256':sha(CFG),'implementationSha256':sha(__file__),'files':{n:sha(OUT/n) for n in files},'python':sys.version,'numpy':np.__version__,'highspy':hs.Highs().version()})

class Inverse:
 def __init__(self,m,samples,F,allowed,lam=0):
  self.m=m;self.samples=samples;self.F=F;self.allowed=allowed;self.scale=max(1,st.mean(abs(float(np.dot(s['base'],s['decision']))) for s in samples))
  h=self.h=hsolver();self.t=h.addVariables(5,lb=0,ub=[10 if j in allowed else 0 for j in range(5)],obj=[lam/10]*5)
  self.e=h.addVariables(len(samples),lb=0,obj=[1/(len(samples)*self.scale)]*len(samples));self.rounds=0
 def fit(self):
  for _ in range(60):
   self.rounds+=1;status=runh(self.h)
   if status!=hs.HighsModelStatus.kOptimal:raise RuntimeError('inverse master '+str(status))
   theta=np.array([self.h.val(self.t[j]) for j in range(5)]);loss=[];cuts=0
   for k,s in enumerate(self.samples):
    c=np.array(s['base'])+self.F@theta;x,v,stat=solve(self.m,c)
    if stat!='optimal':raise ValueError('inverse separation '+stat)
    delta=np.array(s['decision'])-x;phi=self.F.T@delta;const=float(np.dot(s['base'],delta));res=const+float(phi@theta);loss.append(max(0,res))
    if res>self.h.val(self.e[k])+1e-6:
     keep=[j for j in range(5) if abs(phi[j])>1e-9];correction=10*sum(min(float(phi[j]),0) for j in range(5) if j not in keep)
     self.h.addConstr(self.e[k]>=const+correction+self.h.qsum(float(phi[j])*self.t[j] for j in keep));cuts+=1
   if not cuts:return theta,st.mean(loss)/self.scale
  raise TimeoutError('inverse cut limit60')
 def loss_cap(self,loss):self.h.addConstr(self.h.qsum(self.e[k] for k in range(len(self.samples)))<=len(self.samples)*self.scale*(loss+1e-6))
 def center(self):
  theta,loss=self.fit();self.loss_cap(loss);z=self.h.addVariables(5,lb=0);target=[1,1,0,0,0]
  for j in self.allowed:self.h.addConstr(z[j]>=self.t[j]-target[j]);self.h.addConstr(z[j]>=target[j]-self.t[j])
  self.h.setObjective(self.h.qsum(z[j] for j in self.allowed));return self.fit()
 def profiles(self):
  theta,loss=self.fit();self.loss_cap(loss);bounds=[]
  for j in range(2):
   ends=[]
   for sign in [1,-1]:
    self.h.setObjective(sign*self.t[j]);tt,l=self.fit();ends.append(float(tt[j]))
   bounds.append({'parameter':j,'lower':ends[0],'upper':ends[1],'width':ends[1]-ends[0],'hitsDeclaredUpper':ends[1]>9.99999})
  return {'minimumLoss':loss,'bounds':bounds}

def gradient(m,samples,F):
 theta=np.array([1,1,0,0,0.]);best=theta.copy();value=math.inf
 for step in range(51):
  if step%10==0:
   losses=[]
   for s in samples:
    c=np.array(s['base'])+F@theta;x,v,status=solve(m,c)
    if status!='optimal':raise ValueError('gradient loss '+status)
    losses.append(max(0,float(c@np.array(s['decision']))-v))
   if st.mean(losses)<value:value=st.mean(losses);best=theta.copy()
  if step==50:break
  s=samples[step%len(samples)];x,v,status=solve(m,np.array(s['base'])+F@theta)
  if status!='optimal':raise ValueError('gradient '+status)
  g=F.T@(np.array(s['decision'])-x);theta=np.clip(theta-10/math.sqrt(step+1)*g/max(1,float(np.linalg.norm(g))),0,10);theta[3:]=0
 return best
def peak_memory():
 if os.name!='nt':
  import resource
  return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
 import ctypes,ctypes.wintypes as w
 class Counters(ctypes.Structure):
  _fields_=[('cb',w.DWORD),('PageFaultCount',w.DWORD)]+[(n,ctypes.c_size_t) for n in ['PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage']]
 c=Counters();c.cb=ctypes.sizeof(c);k=ctypes.WinDLL('kernel32');p=ctypes.WinDLL('psapi')
 k.GetCurrentProcess.restype=w.HANDLE;p.GetProcessMemoryInfo.argtypes=[w.HANDLE,ctypes.POINTER(Counters),w.DWORD]
 return int(c.PeakWorkingSetSize) if p.GetProcessMemoryInfo(k.GetCurrentProcess(),ctypes.byref(c),c.cb) else None
def run(name,seed):
 global DEADLINE
 cfg=read(CFG);f=read(OUT/'freeze.json');inputname=f'inputs/{name}-s{seed}.json';path=OUT/f'jobs/{name}-s{seed}.json'
 if path.exists():return
 if sha(__file__)!=f['implementationSha256'] or sha(CFG)!=f['protocolSha256'] or sha(OUT/inputname)!=f['files'][inputname]:raise ValueError('frozen code/input mismatch')
 rec=read(OUT/inputname);m=rec['model'];F=np.array(rec['F']);truth=np.array(rec['truth']);start=time.perf_counter();cpu=time.process_time()
 derived=[];events=[];rows=[]
 for i,s in enumerate(rec['contexts']):
  d={**s}
  try:
   x,opt,status=solve(m,np.array(s['base'])+F@truth)
   if status!='optimal':raise ValueError('oracle '+status)
   d.update(oracle=x.tolist(),optimum=opt,status='optimal')
   if i<10:
    xn,_,ns=solve(m,s['aux'],capcost=np.array(s['base'])+F@truth,cap=opt+.1*max(1,abs(opt)))
    if ns!='optimal':raise ValueError('history '+ns)
    d['decisions']={'0':x.tolist(),'0.1':xn.tolist()}
  except Exception as e:d.update(status='failed',error=str(e));events.append({'stage':'history' if i<10 else 'test-oracle','context':s['context'],'error':str(e)})
  derived.append(d)
 save(OUT/f'derived/{name}-s{seed}.json',derived)
 for K,noise,method in itertools.product(cfg['K'],cfg['noiseCaps'],cfg['methods']):
  row={'id':name,'family':m['family'],'seed':seed,'K':K,'noise':noise,'method':method};t=time.perf_counter();ct=time.process_time();before=STATS.copy()
  try:
   if any(d['status']=='failed' or 'decisions' not in d for d in derived[:K]):raise ValueError('blocked by recorded history generation failure')
   samples=[{'base':s['base'],'decision':s['decisions'][str(noise)]} for s in derived[:K]]
   DEADLINE=time.perf_counter()+90
   if method in ['zero','unit','midpoint','random']:
    vals={'zero':[0,0],'unit':[1,1],'midpoint':[5,5]}
    rr=random.Random(seedkey(name)+seed*70001);theta=np.array(vals.get(method,[rr.uniform(0,10),rr.uniform(0,10)])+[0]*3,float)
   elif method=='subgradient':theta=gradient(m,samples,F)
   else:
    io=Inverse(m,samples,F,list(range(5)) if method=='full_l1' else [0,1,2],.01 if method in ['text_l1','full_l1'] else 0)
    theta,loss=io.center() if method=='center' else io.fit();row.update(trainingLoss=loss,cutRounds=io.rounds)
   DEADLINE=math.inf;row.update(theta=theta.tolist(),fitSeconds=time.perf_counter()-t,mae=float(np.mean(abs(theta[:2]-truth[:2]))),
       relativeMAE=float(np.mean(abs(theta[:2]-truth[:2])))/max(1e-12,float(np.mean(truth[:2]))),
       unusedHidden=sum(all(abs(s['decision'][rec['indices'][j]])<1e-8 for s in samples) for j in range(2)),truthOutsideBox=rec['truthOutsideBox'])
   details=[]
   for s in derived[10:]:
    detail={'context':s['context']}
    try:
     if s['status']!='optimal':raise ValueError('blocked by oracle failure')
     c=np.array(s['base'])+F@theta;truec=np.array(s['base'])+F@truth;x,val,status=solve(m,c)
     if status!='optimal':raise ValueError('prediction '+status)
     gap=max(0,float(truec@x)-s['optimum'])/max(1,abs(s['optimum']))
     detail.update(status='optimal',decision=x.tolist(),predictedObjective=val,regret=gap,trueObjective=float(truec@x),oracleObjective=s['optimum'])
     if K==10 and noise==.1:
      for tag,maximize in [('best',False),('worst',True)]:
       try:
        xx,v,stat=solve(m,truec,capcost=c,cap=val,maximize=maximize)
        detail[tag+'Status']=stat
        if stat=='optimal':
         detail[tag+'Regret']=max(0,v-s['optimum'])/max(1,abs(s['optimum']))
         detail[tag+'Decision']=xx.tolist();detail[tag+'DistanceL1']=float(np.sum(abs(xx-x)))
        else:detail[tag+'Regret']=None
       except Exception as e:detail[tag+'Status']='failed';detail[tag+'Error']=str(e);detail[tag+'Regret']=None
    except Exception as e:detail.update(status='failed',error=str(e))
    details.append(detail)
   row.update(testDetails=details,status='complete' if all(d['status']=='optimal' for d in details) else 'incomplete')
   row['meanRegret']=st.mean(d['regret'] for d in details) if row['status']=='complete' else None
   if K==10 and noise==.1:
    for tag in ['best','worst']:
     values=[d.get(tag+'Regret') for d in details]
     row[tag+'Mean']=st.mean(values) if all(v is not None for v in values) else None
  except Exception as e:row.update(status='failed',error=str(e),meanRegret=None)
  finally:DEADLINE=math.inf
  row.update(wallSeconds=time.perf_counter()-t,cpuSeconds=time.process_time()-ct,resources=dict(STATS-before),peakProcessRSSBytes=peak_memory());rows.append(row)
  save(path,{'id':name,'seed':seed,'stage':'running','rows':rows,'events':events})
 profile={}
 try:
  s=[{'base':x['base'],'decision':x['decisions']['0.1']} for x in derived[:10]];DEADLINE=time.perf_counter()+90
  profile=Inverse(m,s,F,[0,1,2]).profiles();profile['status']='complete'
  for b in profile['bounds']:b['truth']=float(truth[b['parameter']]);b['containsTruth']=b['lower']-1e-6<=b['truth']<=b['upper']+1e-6
 except Exception as e:profile={'status':'failed','error':str(e)}
 finally:DEADLINE=math.inf
 save(path,{'id':name,'family':m['family'],'seed':seed,'stage':'complete','rows':rows,'events':events,'profile':profile,'wallSeconds':time.perf_counter()-start,'cpuSeconds':time.process_time()-cpu,'resources':dict(STATS),'peakProcessRSSBytes':peak_memory()})
 print(json.dumps({'id':name,'seed':seed,'rows':len(rows),'failed':sum(r['status']!='complete' for r in rows),'seconds':time.perf_counter()-start}),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['audit','freeze','run']);p.add_argument('--id');p.add_argument('--seed',type=int);a=p.parse_args()
 if a.mode=='audit':audit()
 elif a.mode=='freeze':freeze()
 else:run(a.id,a.seed)
