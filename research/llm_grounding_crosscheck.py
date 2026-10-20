"""Independent vertices/MTZ checks of the new source adapters, preserving every status."""
import itertools,json,math,sys,time
from pathlib import Path
import numpy as np
import highspy as hs
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/inverse/deepseek-grounding-20261020-v1'
def read(p):return json.loads(p.read_text(encoding='utf8'))
def cost(m,base,fs,tt,x):
    v=float(np.dot(base,x))
    for f,t in zip(fs,tt):
        v+=t*(f['sign']*x[m['names'].index(f['variable'])] if f['kind']=='linear' else max(0,float(np.dot(m['monitors'][f['monitor']],x))-f['threshold']))
    return v
results=[];start=time.perf_counter()
for meta in read(OUT/'models.json'):
    item=read(OUT/'oracle'/f'{meta["id"]}.json');m=item['model'];rec={**meta}
    try:
        ss=read(OUT/'contexts'/f'{meta["id"]}-s19.json');s=ss[0]
        if m['collection']=='NL4Opt':
            if len(m['names'])!=2:raise ValueError('vertex checker requires2 variables')
            lines=[]
            for a,lo,hi in zip(m['A'],m['rl'],m['ru']):
                if lo>-1e29:lines.append((a,lo))
                if hi<1e29:lines.append((a,hi))
            lines.extend([([1,0],0),([0,1],0)])
            for f in item['trueFeatures']:
                if f['kind']=='excess':lines.append((m['monitors'][f['monitor']],f['threshold']))
            candidates=[]
            for (a,b),(aa,bb) in itertools.combinations(lines,2):
                mat=np.array([a,aa],float)
                if abs(np.linalg.det(mat))<1e-12:continue
                x=np.linalg.solve(mat,[b,bb]);ax=np.array(m['A'])@x
                if min(x)<-1e-7 or min(ax-np.array(m['rl']))< -1e-7 or min(np.array(m['ru'])-ax)<-1e-7:continue
                candidates.append(x)
            value=min(cost(m,s['base'],item['trueFeatures'],item['truth'],x) for x in candidates)
            assert abs(value-s['oracleObjective'])<1e-5*max(1,abs(value))
            rec.update(status='passed',method='all2D polygon/break-line vertex intersections; no solver',vertices=len(candidates),objective=value)
        elif m['kind']=='tour':
            h=hs.Highs()
            for k,v in {'output_flag':False,'threads':1,'time_limit':10.,'mip_rel_gap':0.}.items():h.setOptionValue(k,v)
            edges=[tuple(e) for e in m['edges']];n=len(set(i for i,j in edges))
            x=h.addVariables(len(edges),lb=0,ub=1,type=hs.HighsVarType.kInteger)
            u=h.addVariables(n-1,lb=1,ub=n-1)
            for i in range(n):
                h.addConstr(h.qsum(x[k] for k,(a,b) in enumerate(edges) if a==i)==1)
                h.addConstr(h.qsum(x[k] for k,(a,b) in enumerate(edges) if b==i)==1)
            for k,(i,j) in enumerate(edges):
                if i and j:h.addConstr(u[i-1]-u[j-1]+n*x[k]<=n-1)
            objective=h.qsum(float(v)*x[k] for k,v in enumerate(s['base']))
            for f,t in zip(item['trueFeatures'],item['truth']):
                if f['kind']=='linear':objective+=t*f['sign']*x[m['names'].index(f['variable'])]
                else:
                    z=h.addVariable(lb=0)
                    h.addConstr(z>=h.qsum(float(v)*x[k] for k,v in enumerate(m['monitors'][f['monitor']]))-f['threshold'])
                    objective+=t*z
            h.setObjective(objective);h.run()
            assert h.getModelStatus()==hs.HighsModelStatus.kOptimal,str(h.getModelStatus())
            value=h.getObjectiveValue();assert abs(value-s['oracleObjective'])<1e-5
            rec.update(status='passed',method='directed MTZ MILP vs complete tour enumeration',objective=value)
        else:
            # Every original nonnegative cost bounds feasible candidates below current optimum.
            fullc=np.array(s['base'])
            for f,t in zip(item['trueFeatures'],item['truth']):
                if f['kind']=='linear':fullc[m['names'].index(f['variable'])]+=t*f['sign']
            if min(fullc)<=0:raise ValueError('no finite positive-cost enumeration bounds')
            upper=[math.floor((s['oracleObjective']+1e-6)/v) for v in fullc];count=math.prod(v+1 for v in upper)
            if count>250000:
                rec.update(status='not_independently_enumerated',candidateVectors=count,reason='prespecified250000 enumeration cap; original source optimum separately matched');results.append(rec);continue
            best=math.inf;feasible=0
            for x in itertools.product(*[range(v+1) for v in upper]):
                if min(np.array(m['A'])@x-np.array(m['rl']))< -1e-7:continue
                feasible+=1;best=min(best,cost(m,s['base'],item['trueFeatures'],item['truth'],x))
            assert abs(best-s['oracleObjective'])<1e-5
            rec.update(status='passed',method='exhaustive nonnegative integer vectors under positive-cost bound',candidateVectors=count,feasibleVectors=feasible,objective=best)
    except Exception as e:rec.update(status='failed',error=str(e))
    results.append(rec)
data={'checks':results,'wallSeconds':time.perf_counter()-start,'scope':'One augmented context per source (seed19,c0). Vertex/MTZ/enumeration methods diversify numerical algorithms; all share source interpretation. No omitted-source replacement.'}
(OUT/'independent-checks.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'statuses':{s:sum(r['status']==s for r in results) for s in set(r['status'] for r in results)},'seconds':data['wallSeconds']}))
