"""Local, frozen cross-family extension. Source text is data, never executable."""
import argparse
import hashlib
import itertools
import json
import math
import os
import random
import re
import statistics as st
import sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import highspy as hs

ROOT=Path(__file__).resolve().parents[1]
OUT=Path(os.environ.get('MULTIFAMILY_OUT',str(ROOT/'outputs/inverse/multifamily-20261020-v1')))
CFG=ROOT/'research/multifamily_protocol.json'
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def save(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def solver():
    h=hs.Highs()
    for k,v in {'output_flag':False,'threads':1,'time_limit':10.,'random_seed':17,'mip_rel_gap':0.,'mip_abs_gap':0.}.items():h.setOptionValue(k,v)
    return h
def certified(h):
    h.run()
    if h.getModelStatus()!=hs.HighsModelStatus.kOptimal:raise ValueError('uncertified solve '+str(h.getModelStatus()))


def parse_relocation(row):
    q=row['Question'].replace('**','');stocks={};needs={};costs={}
    for line in q.splitlines():
        if ':' in line:
            head,body=line.split(':',1)
            origin=re.search(r'(?:Warehouse|Region|Hospital|Clinic|City|District|Center)\s+(\d+)',head,re.I)
            if origin:
                pairs=re.findall(r'[Tt]o\s+(?:(?:Warehouse|Region|Hospital|Clinic|City|District|Center)\s+)?(\d+)\s+costs?\s+(\d+)',body)
                if pairs:
                    for j,c in pairs:costs[int(origin.group(1)),int(j)]=float(c)
        elif re.search(r'\b(?:needs?|requires?|demand)\b',line,re.I):
            numbers=re.findall(r'\d+',line)
            if len(numbers)==3 and re.search(r'(?:Warehouse|Region|Hospital|Clinic|City|District|Center)\s+\d+',line,re.I):
                i,s,d=map(int,numbers);stocks[i]=s;needs[i]=d
    n=len(stocks)
    if n<4 or sorted(stocks)!=list(range(1,n+1)):raise ValueError('incomplete stock/need rows')
    if len(costs)!=n*(n-1) or any((i,j) not in costs for i in stocks for j in stocks if i!=j):raise ValueError('incomplete directed cost matrix')
    if re.search(r'exactly what they need|exactly (?:the|their) required',q,re.I) and sum(stocks.values())!=sum(needs.values()):
        raise ValueError('exact final stock wording conflicts with excess total inventory; no disposal specified')
    arcs=[(i,j) for i in stocks for j in stocks if i!=j]
    A=np.zeros((n,len(arcs)))
    for k,(i,j) in enumerate(arcs):A[i-1,k]=-1;A[j-1,k]=1
    return {'id':row['id'],'family':'relocation','names':[f'{i}->{j}' for i,j in arcs],'c':[costs[e] for e in arcs],
            'A':A.tolist(),'b':[needs[i]-stocks[i] for i in stocks],'stocks':list(stocks.values()),'needs':list(needs.values()),
            'semantics':'nonnegative continuous transshipment flows; initial+inflow-outflow>=need; surplus retained; no artificial flow upper bounds'}


def parse_tour(row):
    q=row['Question'].replace('**','');matrix={}
    for line in q.splitlines():
        if not re.search(r'cost|units|expenses|takes',line,re.I):continue
        line=re.sub(r'\b(?:City|Location)\s+([A-FH-I1-6])\b',r'@\1',line)
        line=re.sub(r'\bShop([1-6])\b',r'@\1',line)
        line=re.sub(r'(?<![@\w])([A-I]|Alpha|Bravo|Charlie|Delta)(?!\w)',r'@\1',line)
        tokens=re.findall(r'@[A-Za-z0-9]+|\d+(?:\.\d+)?',line)
        if not tokens or not tokens[0].startswith('@') or len(tokens)<7:continue
        origin=tokens[0][1:];tail=tokens[1:]
        if len(tail)%2:continue
        pairs=[]
        for a,b in zip(tail[::2],tail[1::2]):
            if a.startswith('@') and not b.startswith('@'):pairs.append((a[1:],float(b)))
            elif b.startswith('@') and not a.startswith('@'):pairs.append((b[1:],float(a)))
            else:break
        else:
            for target,c in pairs:
                if target==origin:raise ValueError('self-loop in explicit row')
                if (origin,target) in matrix and matrix[origin,target]!=c:raise ValueError('conflicting explicit costs')
                matrix[origin,target]=c
    cities=sorted(set(i for i,j in matrix)|set(j for i,j in matrix))
    n=len(cities)
    if not 4<=n<=6 or len(matrix)!=n*(n-1):raise ValueError('incomplete directed tour costs')
    if any(matrix[i,j]!=matrix[j,i] for i,j in matrix):raise ValueError('this adapter supports explicitly symmetric tour costs only')
    edges=list(itertools.combinations(cities,2));cost=[matrix[i,j] for i,j in edges];tours=[]
    for tail in itertools.permutations(cities[1:]):
        if tail[0]>tail[-1]:continue
        route=(cities[0],)+tail+(cities[0],);x=[0]*len(edges)
        for i,j in zip(route,route[1:]):x[edges.index(tuple(sorted((i,j))))]=1
        tours.append(x)
    return {'id':row['id'],'family':'tour','names':[i+'--'+j for i,j in edges],'c':cost,'choices':tours,
            'semantics':'undirected Hamiltonian cycle, each city exactly once and return; complete enumeration of all cycles modulo reversal'}


def solve(model,c,cap_cost=None,cap=None,maximize=False):
    c=np.asarray(c,float)
    if model['family']=='tour':
        X=np.asarray(model['choices'],float);valid=np.ones(len(X),dtype=bool)
        if cap is not None:valid=(X@np.asarray(cap_cost)<=cap+1e-7)
        if not valid.any():raise ValueError('empty certified tour set')
        indices=np.flatnonzero(valid);values=X[indices]@c
        pos=int(np.argmax(values) if maximize else np.argmin(values));idx=indices[pos]
        return X[idx],float(values[pos]),'optimal'
    h=solver();x=h.addVariables(len(c),lb=0,obj=(-c if maximize else c).tolist())
    for a,b in zip(model['A'],model['b']):
        h.addConstr(h.qsum(float(v)*x[j] for j,v in enumerate(a) if v)>=float(b))
    if cap is not None:h.addConstr(h.qsum(float(v)*x[j] for j,v in enumerate(cap_cost) if v)<=float(cap)+1e-7)
    h.run();status=h.getModelStatus()
    if status==hs.HighsModelStatus.kUnbounded:return None,None,'unbounded'
    if status!=hs.HighsModelStatus.kOptimal:raise ValueError('forward '+str(status))
    xx=np.array([h.val(x[j]) for j in range(len(x))])
    if min(np.asarray(model['A'])@xx-model['b']) < -1e-5:raise ValueError('forward infeasible')
    return xx,float(c@xx),'optimal'


def audit():
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'source-audit.json').exists():return
    cfg=read(CFG);save(OUT/'protocol.json',cfg)
    save(OUT/'protocol-freeze.json',{'createdUtc':datetime.now(timezone.utc).isoformat(),'protocolSha256':digest(CFG),'stage':'before inverse outcomes; source parsing audit follows'})
    path=ROOT/'datasets/mamo/mamo_complex_lp.jsonl'
    source=[json.loads(line) for line in path.read_text(encoding='utf8').splitlines()]
    records=[];models=[];signatures={}
    for family,(lo,hi) in cfg['candidate_source_ids'].items():
        for row in [r for r in source if lo<=r['id']<=hi]:
            rec={'id':row['id'],'family':family,'sourceAnswer':float(row['Answer']),'questionSha256':hashlib.sha256(row['Question'].encode()).hexdigest()}
            try:
                m=(parse_tour if family=='tour' else parse_relocation)(row)
                _,objective,_=solve(m,m['c']);rec['reconstructedOptimum']=objective
                if abs(objective-float(row['Answer']))>1e-6:raise ValueError('explicit model optimum disagrees with public answer; retain discrepancy, no fitted-data selection')
                key=hashlib.sha256(json.dumps({k:v for k,v in m.items() if k not in ['id','names']},sort_keys=True).encode()).hexdigest()
                if key in signatures:raise ValueError('duplicate numerical instance of id '+str(signatures[key]))
                signatures[key]=row['id'];rec['status']='admitted';m['questionSha256']=rec['questionSha256'];m['sourceAnswer']=float(row['Answer']);models.append(m)
            except Exception as e:rec.update(status='excluded',reason=str(e))
            records.append(rec)
    save(OUT/'source-audit.json',{'sourceSha256':digest(path),'records':records,'sourceRevision':cfg['source_revision']})
    save(OUT/'models.json',models)
    print(json.dumps({'admitted':{f:sum(m['family']==f for m in models) for f in cfg['candidate_source_ids']},'excluded':[r for r in records if r['status']=='excluded']}),flush=True)


def contexts(m,seed):
    cfg=read(CFG);rng=random.Random(20261021+m['id']*1009)
    hidden=sorted(rng.sample(range(len(m['c'])),2));remaining=[j for j in range(len(m['c'])) if j not in hidden]
    nuisance=rng.sample(remaining,3);indices=hidden+nuisance
    F=np.zeros((len(m['c']),5))
    for j,v in enumerate(indices):F[v,j]=1
    truth=np.array([m['c'][v] for v in hidden]+[0,0,0],float)
    rng=random.Random(seed*100000+m['id']);out=[]
    for i in range(40):
        s={**m};base=np.array([0 if j in hidden else round(c*rng.uniform(.5,1.5),5) for j,c in enumerate(m['c'])])
        if m['family']=='relocation':
            factor=rng.uniform(.8,1.2);s['b']=[round(v*factor) for v in m['b']]
            if sum(s['b'])>0:raise ValueError('perturbed net balances infeasible')
        truec=base+F@truth;x,opt,status=solve(s,truec)
        s.update(context=f'p{m["id"]}-s{seed}-c{i}',base=base.tolist(),F=F.tolist(),truth=truth.tolist(),oracleDecision=x.tolist(),oracleObjective=opt)
        if i<20:
            auxrng=random.Random(555+seed*10000+m['id']*100+i);aux=[auxrng.uniform(.1,2) for _ in base]
            xn,_,_=solve(s,aux,cap_cost=truec,cap=opt+.1*max(1,abs(opt)))
            gap=float((truec@xn-opt)/max(1,abs(opt)))
            if gap>.100001 or gap< -1e-7:raise ValueError('noise gap invalid')
            s['decisions']={'0':x.tolist(),'0.1':xn.tolist()};s['realizedNoiseGap']=gap
        out.append(s)
    return out,truth.tolist(),indices


def fit(samples,F,U,allowed,lam=0,floor=False,center=False):
    n=5;scale=max(1,st.mean(float(np.dot(s['base'],s['decision'])) for s in samples))
    h=solver();theta=h.addVariables(n,lb=[1 if floor and j<2 else 0 for j in range(n)],ub=[U if j in allowed else 0 for j in range(n)],obj=[lam/U]*n)
    e=h.addVariables(len(samples),lb=0,obj=[1/(len(samples)*scale)]*len(samples));iterations=0
    def separate():
        nonlocal iterations
        for _ in range(100):
            iterations+=1;certified(h);tt=np.array([h.val(theta[j]) for j in range(n)]);cuts=0;losses=[]
            for k,s in enumerate(samples):
                x,val,status=solve(s,np.array(s['base'])+F@tt)
                delta=np.array(s['decision'])-x;phi=F.T@delta;const=float(np.dot(s['base'],delta));res=const+float(phi@tt);losses.append(max(0,res))
                if res>h.val(e[k])+1e-6:
                    kept=[j for j in range(n) if abs(phi[j])>1e-9];correction=U*sum(min(float(phi[j]),0) for j in range(n) if j not in kept)
                    h.addConstr(e[k]>=const+correction+h.qsum(float(phi[j])*theta[j] for j in kept));cuts+=1
            if not cuts:return tt,st.mean(losses)/scale
        raise ValueError('inverse cutting-plane iteration limit')
    tt,l=separate()
    if center:
        h.addConstr(h.qsum(e[k] for k in range(len(samples)))<=len(samples)*scale*(l+1e-6))
        targets=[U/2,U/2,0,0,0];z=h.addVariables(n,lb=0)
        for j in allowed:h.addConstr(z[j]>=theta[j]-targets[j]);h.addConstr(z[j]>=targets[j]-theta[j])
        h.setObjective(h.qsum(z[j] for j in allowed))
        tt,l=separate()
    return {'theta':tt.tolist(),'iterations':iterations,'trainingLoss':l,'status':'optimal','scale':scale}


def gradient_fit(samples,F,U):
    tt=np.array([U/2,U/2,0,0,0.]);best=tt.copy();bestloss=math.inf
    def loss(t):
        return st.mean(max(0,float((np.array(s['base'])+F@t)@np.array(s['decision']))-solve(s,np.array(s['base'])+F@t)[1]) for s in samples)
    for step in range(101):
        if step%10==0:
            value=loss(tt)
            if value<bestloss:bestloss=value;best=tt.copy()
        if step==100:break
        s=samples[step%len(samples)];x,_,_=solve(s,np.array(s['base'])+F@tt)
        grad=F.T@(np.array(s['decision'])-x)
        tt=np.clip(tt-U/math.sqrt(step+1)*grad/max(1,float(np.linalg.norm(grad))),0,U);tt[3:]=0
    return {'theta':best.tolist(),'iterations':100,'trainingLoss':bestloss/max(1,st.mean(float(np.dot(s['base'],s['decision'])) for s in samples)),'status':'budgeted','optimizationGuarantee':'none; retained best training-loss checkpoint'}


def score(test,F,truth,theta):
    regrets=[];best=[];worst=[];details=[]
    for s in test:
        c=np.array(s['base'])+F@theta;truec=np.array(s['base'])+F@truth
        x,v,status=solve(s,c);opt=s['oracleObjective'];den=max(1,abs(opt))
        lo,lv,ls=solve(s,truec,cap_cost=c,cap=v);hi,hv,us=solve(s,truec,cap_cost=c,cap=v,maximize=True)
        reg=max(0,float(truec@x)-opt)/den;lower=max(0,lv-opt)/den;upper=None if us=='unbounded' else max(0,hv-opt)/den
        if lower>reg+1e-6 or (upper is not None and reg>upper+1e-6):raise ValueError('tie envelope excludes predicted decision')
        regrets.append(reg);best.append(lower);worst.append(upper)
        details.append({'context':s['context'],'decision':x.tolist(),'predictedOptimum':v,'regret':reg,'bestTieRegret':lower,'worstTieRegret':upper,'worstTieStatus':us})
    return {'normalizedRegret':st.mean(regrets),'bestTieMean':st.mean(best),'worstTieMean':None if None in worst else st.mean(worst),
            'unboundedTieContexts':sum(v is None for v in worst),'testDetails':details,
            'hiddenMAE':float(np.mean(abs(np.array(theta[:2])-truth[:2]))),
            'hiddenNormalizedMAE':float(np.mean(abs(np.array(theta[:2])-truth[:2])))/max(1,float(np.mean(truth[:2])))}


def freeze():
    audit();cfg=read(CFG)
    if (OUT/'freeze.json').exists():
        f=read(OUT/'freeze.json')
        for name,d in f['files'].items():
            if digest(OUT/name)!=d:raise ValueError('Frozen input changed '+name)
        if digest(CFG)!=f['protocolSha256']:raise ValueError('Protocol changed')
        return
    files=['models.json','source-audit.json','protocol.json']
    for m in read(OUT/'models.json'):
        for seed in cfg['seeds']:
            ss,truth,indices=contexts(m,seed)
            path=f'contexts/p{m["id"]}-s{seed}.json'
            save(OUT/path,{'id':m['id'],'family':m['family'],'seed':seed,'contexts':ss,'truth':truth,'indices':indices,
                          'logs':[f'单位成本漏记：{m["names"][indices[j]]}，每单位需要付费。' for j in range(2)]+[f'{m["names"][indices[2]]}可能另有额外代价，尚未核实。'],
                          'textSelection':[0,1,2],'textProvider':'deterministic controlled template; not LLM'});files.append(path)
    save(OUT/'freeze.json',{'createdUtc':datetime.now(timezone.utc).isoformat(),'protocolSha256':digest(CFG),'sourceSha256':digest(__file__),'files':{n:digest(OUT/n) for n in files},'highspy':hs.Highs().version(),'numpy':np.__version__,'python':sys.version})
    print(json.dumps({'frozenContextFiles':len(files)-3}),flush=True)


def run(pid,seed):
    cfg=read(CFG);f=read(OUT/'freeze.json')
    if digest(CFG)!=f['protocolSha256']:raise ValueError('Protocol changed')
    dest=OUT/f'rows/p{pid}-s{seed}.json'
    if dest.exists():return
    name=f'contexts/p{pid}-s{seed}.json'
    if digest(OUT/name)!=f['files'][name]:raise ValueError('Context altered')
    record=read(OUT/name);ss=record['contexts'];F=np.array(ss[0]['F']);truth=np.array(record['truth']);U=cfg['parameter_upper'][record['family']]
    rows=[]
    for K in cfg['K']:
        for cap in cfg['noise_gap_caps']:
            # Learner sees feasible-set structure, known cost, feature bank, and decisions only.
            train=[{k:v for k,v in s.items() if k not in ['truth','oracleDecision','oracleObjective','decisions','realizedNoiseGap','c','sourceAnswer','questionSha256']}|{'decision':s['decisions'][str(cap)]} for s in ss[:K]]
            for method in cfg['methods']:
                row={'id':pid,'family':record['family'],'seed':seed,'K':K,'noise':cap,'method':method,'split':'development' if pid%5==0 else 'evaluation'}
                try:
                    if method=='fixed_midpoint':est={'theta':[U/2,U/2,0,0,0],'status':'fixed','iterations':0}
                    elif method=='known_cost_median':
                        median=st.median(v for s in train for v in s['base'] if v>0);est={'theta':[median,median,0,0,0],'status':'fixed','iterations':0}
                    elif method=='projected_subgradient':est=gradient_fit(train,F,U)
                    else:
                        allowed=[0,1] if method=='cost_only_io' else list(range(5)) if method=='full_bank_io' else [0,1,2]
                        lam=.01 if method in ['text_sparse_io','full_bank_io','positive_floor_io'] else 0
                        est=fit(train,F,U,allowed,lam,method=='positive_floor_io',method=='prior_center_io')
                    theta=np.array(est['theta']);row.update(est);row.update(score(ss[20:],F,truth,theta))
                    row['unusedHiddenCount']=sum(all(s['decision'][record['indices'][j]]<=1e-8 for s in train) for j in range(2))
                except Exception as e:row.update(status='failed',error=str(e))
                rows.append(row)
    save(dest,{'id':pid,'seed':seed,'rows':rows})
    print(json.dumps({'id':pid,'seed':seed,'rows':len(rows),'failed':sum(r['status']=='failed' for r in rows)}),flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['audit','freeze','run']);ap.add_argument('--id',type=int);ap.add_argument('--seed',type=int);args=ap.parse_args()
    if args.mode=='audit':audit()
    elif args.mode=='freeze':freeze()
    else:run(args.id,args.seed)
