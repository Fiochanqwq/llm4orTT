"""Independent formulations for source models and a fully enumerated inverse LP."""
import itertools,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import stress_public as s
import numpy as np
OUT=s.OUT
def mtz(m):
 n=m['cities'];cost={tuple(e):c for e,c in zip(m['edges'],m['c'])};h=s.hsolver();h.setOptionValue('time_limit',30.)
 x={(i,j):h.addVariable(lb=0,ub=1,type=s.hs.HighsVarType.kInteger,obj=cost[tuple(sorted((i,j)))]) for i in range(n) for j in range(n) if i!=j}
 for i in range(n):
  h.addConstr(h.qsum(x[i,j] for j in range(n) if j!=i)==1);h.addConstr(h.qsum(x[j,i] for j in range(n) if j!=i)==1)
 u={i:h.addVariable(lb=1,ub=n-1) for i in range(1,n)}
 for i,j in itertools.permutations(range(1,n),2):h.addConstr(u[i]-u[j]+n*x[i,j]<=n-1)
 h.run()
 if h.getModelStatus()!=s.hs.HighsModelStatus.kOptimal:raise RuntimeError(str(h.getModelStatus()))
 return h.getObjectiveValue()
def exhaustive_inverse(rec,derived):
 m=rec['model'];F=np.array(rec['F']);n=len(m['c']);X=np.array(list(itertools.product([0.,1.],repeat=n)))
 valid=np.all(X@np.array(m['A']).T<=np.array(m['ru'])+1e-7,axis=1);X=X[valid]
 ss=[{'base':d['base'],'decision':d['decisions']['0.1']} for d in derived[:10]];scale=max(1,np.mean([abs(np.dot(d['base'],d['decision'])) for d in ss]))
 h=s.hsolver();tt=h.addVariables(5,lb=0,ub=[10,10,10,0,0]);e=h.addVariables(10,lb=0,obj=[1/(10*scale)]*10)
 for k,d in enumerate(ss):
  for x in X:
   delta=np.array(d['decision'])-x;phi=F.T@delta;const=float(np.dot(d['base'],delta))
   h.addConstr(e[k]>=const+h.qsum(float(phi[j])*tt[j] for j in range(3)))
 h.run()
 if h.getModelStatus()!=s.hs.HighsModelStatus.kOptimal:raise ValueError('enumerated inverse failed')
 loss=h.getObjectiveValue();h.addConstr(h.qsum(e[k] for k in range(10))<=10*scale*(loss+1e-6));bounds=[]
 for j in range(2):
  v=[]
  for sign in [1,-1]:
   h.setObjective(sign*tt[j]);h.run()
   if h.getModelStatus()!=s.hs.HighsModelStatus.kOptimal:raise ValueError('enumerated profile failed')
   v.append(h.val(tt[j]))
  bounds.append(v)
 return {'feasibleDecisions':len(X),'minimumLoss':loss,'bounds':bounds}
def main():
 start=time.perf_counter();cpu=time.process_time();checks=[]
 for m in s.read(OUT/'models.json'):
  record={'id':m['id'],'family':m['family']}
  try:
   if m['family']=='TSPLIB':v=mtz(m);method='independent directed MTZ MILP; shared HiGHS'
   elif m['family']=='NETLIB':
    h=s.hsolver();h.setOptionValue('solver','ipm');h.setOptionValue('run_crossover','off');h.passModel(s.lpmodel(m,m['c']));h.run()
    if h.getModelStatus()!=s.hs.HighsModelStatus.kOptimal:raise ValueError(str(h.getModelStatus()))
    v=h.getObjectiveValue();method='interior point without crossover; same linear matrix'
   elif len(m['c'])<=15:
    X=np.array(list(itertools.product([0.,1.],repeat=len(m['c']))));valid=np.all(X@np.array(m['A']).T<=np.array(m['ru'])+1e-7,axis=1)
    v=float(np.min(X[valid]@np.array(m['c'])));method='exhaustive binary enumeration independent of optimizer'
   else:
    record.update(status='not_independently_recomputed',reason='More than15 binary variables; original certified optimum checked against published answer during admission');checks.append(record);continue
   if abs(v-m['publishedOptimum'])>1e-5*max(1,abs(v)):raise ValueError('published optimum mismatch')
   record.update(status='passed',objective=v,published=m['publishedOptimum'],method=method)
  except Exception as e:record.update(status='failed',error=str(e))
  checks.append(record)
 rec=s.read(OUT/'inputs/mknap1-1-s19.json');derived=s.read(OUT/'derived/mknap1-1-s19.json');cert=exhaustive_inverse(rec,derived)
 stored=s.read(OUT/'jobs/mknap1-1-s19.json')['profile'];equal=stored['status']=='complete' and abs(cert['minimumLoss']-stored['minimumLoss'])<1e-6 and np.allclose(cert['bounds'],[[b['lower'],b['upper']] for b in stored['bounds']],atol=1e-4)
 cert.update(status='passed' if equal else 'failed',scope='mknap1-1 seed19 K10 gapcap0.1; every feasible competitor constrained at once, compared to separated LP')
 s.save(OUT/'independent-checks.json',{'sourceChecks':checks,'enumeratedInverse':cert,'wallSeconds':time.perf_counter()-start,'cpuSeconds':time.process_time()-cpu,'limits':'Same source parser for all checks; MTZ and IPM still use HiGHS; this is formulation/algorithm diversity, not independent human data interpretation.'})
 print(json.dumps({'sourceStatuses':dict(s.Counter(c['status'] for c in checks)),'inverse':cert,'seconds':time.perf_counter()-start}))
if __name__=='__main__':main()
