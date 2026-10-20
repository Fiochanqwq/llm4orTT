"""Post-result forensic audit; NEVER writes the frozen v2 experiment.

Run with the repository's embedded Python. All supplemental solves use the
original evaluation contexts, metric, and 31 source IDs. No paid API calls.
"""
import argparse
import hashlib
import json
import os
import random
import statistics as st
import sys
from datetime import datetime, timezone
from pathlib import Path

import highspy as hs
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mamo_experiment as exp

ROOT = exp.ROOT
OLD = exp.OUT
OUT = Path(os.environ.get('MAMO_AUDIT_OUT',str(ROOT / 'outputs/inverse/mamo-audit-20261020-v1')))
read, save = exp.read, exp.save


def seal():
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / 'audit-protocol.json'
    if path.exists():
        verify_old()
        return
    files = {str(p.relative_to(OLD)).replace('\\', '/'): exp.digest(p)
             for p in sorted(OLD.rglob('*')) if p.is_file()}
    save(OUT/'original-seal.json', {'source':str(OLD), 'files':files})
    save(path, {
        'createdUtc':datetime.now(timezone.utc).isoformat(),
        'phase':'post-result diagnostic audit, NOT preregistered confirmation',
        'primary':{'K':10,'noise':0.1,'split':'evaluation','n':31},
        'unchanged':'All original rows, test contexts, source IDs, metric, fit algorithm and version 0.1 remain unchanged.',
        'metric':'mean over the same 20 test contexts of max(0,true_cost-optimum)/max(1,abs(optimum)); then equal mean over 31 source problems',
        'influence':'top one and two loss shares; leave-one-out means are diagnostics only, never replacement scores',
        'noise':'decompose every source contribution for every adjacent noise cap; detailed 0.10 to 0.15 at K=10',
        'baseline':'existing fixed [10,10,0,0,0], no new constants selected on test performance',
        'bootstrap':{'unit':'source problem','paired':True,'draws':5000,'seed':20261020,'scope':'same family descriptive, unadjusted 95%, no cross-domain inference'},
        'profile':{'allowedFeatures':[0,1,2],'domain':[0,20],'criterion':'mean training suboptimality / original scale <= minimum unregularized criterion + 1e-6','tolerance':1e-6,'cutTolerance':1e-7,'iterations':200,'meaning':'coordinate projection of empirical near-minimum loss set, not confidence intervals or structural/population identification'},
        'catastropheThreshold':'normalized regret > 1 (more than 100% extra cost)',
        'solverSensitivity':{'seeds':[0,1,17,42,20261020],'orders':['original','reverse variables and constraints'],'targets':'primary text_sparse catastrophes plus each LLM control worst case'},
        'historySensitivity':{'ids':[2,39],'noiseCaps':[0.10,0.15],'seeds':[101,202,303,404,505],'K':10,'scope':'new auxiliary noise draws on the SAME training contexts, original 20 test contexts unchanged; diagnostic selected cases, not new main results'},
        'tieAudit':'construct nonnegative integer feasible rays with zero estimated marginal cost and positive true cost; also best true-cost tie as oracle-only diagnostic, never a deployable policy',
        'paidCalls':0,
    })


def verify_old():
    seal_data=read(OUT/'original-seal.json')
    bad=[f for f,d in seal_data['files'].items() if not (OLD/f).is_file() or exp.digest(OLD/f)!=d]
    if bad: raise ValueError('Original evidence changed: '+str(bad))
    return len(seal_data['files'])


def data():
    rows=read(OLD/'all-results.json')
    p={v['id']:v for v in read(OLD/'public/problems.json') if v['split']=='evaluation'}
    t={v['id']:v for v in read(OLD/'oracle/truth.json')}
    primary=[r for r in rows if r['id'] in p and r['K']==10 and r['noise']==.1]
    return rows,p,t,primary


def contrast(primary, a, b):
    aa={r['id']:r for r in primary if r['method']==a}
    bb={r['id']:r for r in primary if r['method']==b}
    ids=sorted(aa.keys() & bb.keys())
    delta=np.array([aa[i]['normalizedRegret']-bb[i]['normalizedRegret'] for i in ids])
    rng=np.random.default_rng(20261020)
    boot=delta[rng.integers(0,len(ids),(5000,len(ids)))].mean(axis=1)
    return {'left':a,'right':b,'n':len(ids),'meanDifference':float(delta.mean()),
            'ci95':np.quantile(boot,[.025,.975]).tolist(),
            'wins':int(sum(delta < -1e-8)),'ties':int(sum(abs(delta)<=1e-8)),'losses':int(sum(delta>1e-8)),
            'pairs':[{'id':i,'difference':float(d)} for i,d in zip(ids,delta)]}


def descriptive():
    seal()
    rows,problems,truth,primary=data()
    methods={}
    for method in sorted({r['method'] for r in primary}):
        rr=sorted([r for r in primary if r['method']==method],key=lambda r:-r['normalizedRegret'])
        total=sum(r['normalizedRegret'] for r in rr)
        methods[method]={'mean':total/len(rr),'median':st.median(r['normalizedRegret'] for r in rr),
            'catastropheIds':[r['id'] for r in rr if r['normalizedRegret']>1],
            'top1Share':rr[0]['normalizedRegret']/total if total else 0,
            'top2Share':sum(r['normalizedRegret'] for r in rr[:2])/total if total else 0,
            'withoutTop1DiagnosticMean':sum(r['normalizedRegret'] for r in rr[1:])/(len(rr)-1),
            'withoutTop2DiagnosticMean':sum(r['normalizedRegret'] for r in rr[2:])/(len(rr)-2),
            'ranked':[{'id':r['id'],'regret':r['normalizedRegret'],'theta':r['theta']} for r in rr]}
    contrasts=[contrast(primary,'text_sparse',m) for m in ['midpoint','no_text_sparse','text_no_l1','llm_guess','llm_single']]
    contrasts.append(contrast(primary,'local_feedback','missing_text'))
    noise=[]
    for k in [5,10,20]:
        for low,high in zip([0,.05,.1],[.05,.1,.15]):
            a={r['id']:r for r in rows if r['id'] in problems and r['K']==k and r['noise']==low and r['method']=='text_sparse'}
            b={r['id']:r for r in rows if r['id'] in problems and r['K']==k and r['noise']==high and r['method']=='text_sparse'}
            pairs=[{'id':i,'low':a[i]['normalizedRegret'],'high':b[i]['normalizedRegret'],
                    'delta':b[i]['normalizedRegret']-a[i]['normalizedRegret'],
                    'contributionToMean':(b[i]['normalizedRegret']-a[i]['normalizedRegret'])/31,
                    'thetaLow':a[i]['theta'],'thetaHigh':b[i]['theta']} for i in sorted(a)]
            noise.append({'K':k,'low':low,'high':high,'lowMean':st.mean(v['low'] for v in pairs),
                          'highMean':st.mean(v['high'] for v in pairs),
                          'pairs':sorted(pairs,key=lambda v:v['delta'])})
    activation=[]
    for i,p in problems.items():
        samples=p['histories']['0.1'][:10]
        hidden=[]
        for j,f in enumerate(p['bank'][:2]):
            v=f['variable'];counts=[s['decision'][v] for s in samples]
            hidden.append({'feature':j,'variable':v,'name':p['names'][v],'truth':truth[i]['truth'][j],
                           'positiveHistories':sum(x>0 for x in counts),'totalQuantity':sum(counts),
                           'testOraclePositiveContexts':sum(o['x'][v]>0 for o in truth[i]['oracles'][20:])})
        activation.append({'id':i,'hidden':hidden,'knownCostActiveHistories':int(sum(np.dot(s['base'],s['decision'])>1e-8 for s in samples)),
                           'scale':max(1,st.mean(float(np.dot(s['base'],s['decision'])) for s in samples))})
    llm={}
    for m in ['llm_guess','llm_single']:
        rr=[r for r in primary if r['method']==m]
        llm[m]={'n':len(rr),'hiddenBoundaryCount':sum(v<=1e-8 or v>=20-1e-8 for r in rr for v in r['theta'][:2]),
                'hiddenCount':2*len(rr),'allZeroIds':[r['id'] for r in rr if max(r['theta'])<1e-8],
                'allTwentyHiddenIds':[r['id'] for r in rr if min(r['theta'][:2])>=20-1e-8],
                'rows':[{'id':r['id'],'theta':r['theta'],'regret':r['normalizedRegret']} for r in rr]}
    batch={r['id']:r for r in primary if r['method']=='llm_guess'}
    single={r['id']:r for r in primary if r['method']=='llm_single'}
    llm['changedIds']=[i for i in batch if batch[i]['theta']!=single[i]['theta']]
    result={'methods':methods,'contrasts':contrasts,'noise':noise,'activation':activation,'llm':llm,
            'summaryActivation':{'problemsWithNeverUsedHidden':[r['id'] for r in activation if any(h['positiveHistories']==0 for h in r['hidden'])],
             'neverUsedParameters':sum(h['positiveHistories']==0 for r in activation for h in r['hidden']),
             'noKnownCostActivationIds':[r['id'] for r in activation if r['knownCostActiveHistories']==0]},
            'originalFileCount':verify_old()}
    save(OUT/'descriptive.json',result)
    print(json.dumps({'text':methods['text_sparse'], 'midpointContrast':contrasts[0],
        'noiseJump':next(r for r in noise if r['K']==10 and r['low']==.1),
        'activation':result['summaryActivation'],'llm':{m:{k:v for k,v in llm[m].items() if k!='rows'} for m in ['llm_guess','llm_single']}},ensure_ascii=False),flush=True)


def profile(samples, bank, target, maximum, minimum, scale):
    """Cutting-plane coordinate bound with a verified suboptimality cap.

    Master is a relaxation: its optimum bounds every feasible original theta.
    Once exact forward separation finds no violated residual cut, its theta
    is also feasible up to tolerance, closing the lower/upper bound gap.
    """
    h=exp.solver()
    theta=h.addVariables(5,lb=0,ub=[20,20,20,0,0],obj=[(-1 if maximum else 1) if j==target else 0 for j in range(5)])
    e=h.addVariables(len(samples),lb=0)
    cap=minimum+1e-6
    h.addConstr(h.qsum(e[k] for k in range(len(samples))) <= len(samples)*scale*cap)
    observed=[exp.features(s,bank,s['decision']) for s in samples]
    for iteration in range(200):
        exp.certified(h)
        tt=np.array([h.val(theta[j]) for j in range(5)])
        actual=[];cuts=0
        for k,s in enumerate(samples):
            x,v=exp.forward(s,bank,tt)
            delta=observed[k]-exp.features(s,bank,x)
            constant=float(np.dot(s['base'],np.asarray(s['decision'])-x))
            residual=float(constant+np.dot(tt,delta));actual.append(max(0,residual))
            if residual>h.val(e[k])+1e-7:
                kept=[j for j in range(5) if abs(delta[j])>1e-9]
                correction=20*sum(min(float(delta[j]),0) for j in range(5) if j not in kept)
                h.addConstr(e[k]>=constant+correction+h.qsum(float(delta[j])*theta[j] for j in kept));cuts+=1
        if not cuts:
            verified=st.mean(actual)/scale
            if verified>cap+1e-6:raise ValueError('Profile cap violated')
            return {'bound':float(tt[target]),'witness':tt.tolist(),'normalizedLoss':verified,'lossCap':cap,
                    'masterObjective':h.getObjectiveValue(),'iterations':iteration+1,'status':'certified_to_tolerance'}
    raise ValueError('Profile iteration limit')


def profiles(pid):
    seal();_,problems,truth,primary=data();p=problems[pid]
    dest=OUT/f'profiles/problem-{pid}.json'
    if dest.exists():return
    base=next(r for r in primary if r['id']==pid and r['method']=='text_no_l1')
    samples=p['histories']['0.1'][:10]
    minimum=exp.loss(samples,p['bank'],base['theta'])/base['scale']
    if abs(minimum-base['objective'])>1e-6:raise ValueError('Unregularized optimum not reproduced')
    result={'id':pid,'minimum':minimum,'scale':base['scale'],'parameters':[]}
    for j in [0,1]:
        result['parameters'].append({'feature':j,'truth':truth[pid]['truth'][j],
            'lower':profile(samples,p['bank'],j,False,minimum,base['scale']),
            'upper':profile(samples,p['bank'],j,True,minimum,base['scale'])})
    save(dest,result);print(json.dumps({'profile':pid}),flush=True)


def permute(s,bank,seed,reverse):
    """Same mathematical model with an explicitly changed variable/row order."""
    n=len(s['base']);order=list(reversed(range(n))) if reverse else list(range(n))
    rows=list(reversed(range(3))) if reverse else list(range(3))
    ss={**s,'base':[s['base'][j] for j in order], 'b':[s['b'][j] for j in rows],
        'A':[[s['A'][i][j] for j in order] for i in rows]}
    bb=[{**f,**({'variable':order.index(f['variable'])} if f['kind']=='cost' else {'nutrient':rows.index(f['nutrient'])})} for f in bank]
    return ss,bb,order


def sensitivity():
    seal();_,problems,truth,primary=data()
    selected=[r for r in primary if r['method']=='text_sparse' and r['normalizedRegret']>1]
    selected += [max([r for r in primary if r['method']==m],key=lambda r:r['normalizedRegret']) for m in ['llm_guess','llm_single']]
    original_solver=exp.solver
    results=[]
    for r in selected:
        p=problems[r['id']];t=truth[r['id']];variants=[]
        for seed in [0,1,17,42,20261020]:
            def seeded():
                h=original_solver();h.setOptionValue('random_seed',seed);return h
            exp.solver=seeded
            for reverse in [False,True]:
                vals=[];decisions=[]
                for k,s in enumerate(p['testContexts']):
                    ss,bb,order=permute(s,p['bank'],seed,reverse)
                    xx,_=exp.forward(ss,bb,r['theta']);x=np.zeros(len(order))
                    for j,v in enumerate(order):x[v]=xx[j]
                    c=float(np.dot(s['base'],x)+np.dot(t['truth'],exp.features(s,p['bank'],x)))
                    opt=t['oracles'][20+k]['objective'];vals.append(max(0,c-opt)/max(1,abs(opt)));decisions.append(x.tolist())
                variants.append({'seed':seed,'reverseOrder':reverse,'meanRegret':st.mean(vals),'testRegrets':vals,'decisions':decisions})
        exp.solver=original_solver
        results.append({'id':r['id'],'method':r['method'],'originalRegret':r['normalizedRegret'],'theta':r['theta'],'variants':variants})
    rays=[]
    for r in primary:
        p=problems[r['id']];t=truth[r['id']]
        free=[f['variable'] for j,f in enumerate(p['bank'][:2]) if abs(r['theta'][j])<1e-12]
        if not free or max(abs(v) for v in r['theta'][2:])>1e-12:continue
        s=p['testContexts'][0];x,pred=exp.forward(s,p['bank'],r['theta'])
        j=free[0];direction=np.zeros(len(x));direction[j]=1
        cost=np.asarray(s['base'],float).copy()
        for k,f in enumerate(p['bank'][:2]):cost[f['variable']]+=t['truth'][k]
        best,bpred=exp.forward(s,p['bank'],r['theta'],auxiliary=cost,cap=pred)
        witness=x+100*direction
        assert min(np.asarray(s['A'])@direction)>=0 and cost[j]>0 and s['base'][j]==0
        assert abs(float(np.dot(s['base'],witness)+np.dot(r['theta'],exp.features(s,p['bank'],witness)))-pred)<1e-6
        rays.append({'id':r['id'],'method':r['method'],'context':s['id'],'variable':j,'food':p['names'][j],
            'theta':r['theta'],'x':x.tolist(),'direction':direction.tolist(),'xPlus100':witness.tolist(),
            'estimatedObjective':pred,'trueCost':float(cost@x),'trueCostPlus100':float(cost@witness),
            'trueCostSlope':float(cost[j]),'bestTrueCostAmongEstimatedTies':float(cost@best),'bestTieDecision':best.tolist(),
            'oracleCost':t['oracles'][20]['objective'],'worstTieRegret':'unbounded',
            'certificate':'A d >= 0, d integral and nonnegative, estimated cost slope = 0, true cost slope > 0; no variable upper bound; nuisance weights zero'})
    save(OUT/'solver-sensitivity.json',results);save(OUT/'tie-certificates.json',rays)
    histories=[]
    for pid in [2,39]:
        p=problems[pid];t=truth[pid]
        for noise in [.1,.15]:
            for seed in [101,202,303,404,505]:
                samples=[];gaps=[]
                for i,s in enumerate(p['histories']['0.1'][:10]):
                    rng=random.Random(seed+pid*10000+i*100)
                    aux=[rng.uniform(.1,2) for _ in s['base']]
                    opt=t['oracles'][i]['objective']
                    x,v=exp.forward(s,p['bank'],t['truth'],auxiliary=aux,cap=opt+noise*max(1,abs(opt)))
                    samples.append({**s,'decision':x.tolist()});gaps.append((v-opt)/max(1,abs(opt)))
                estimate=exp.fit(samples,p['bank'],[0,1,2],.01)
                histories.append({'id':pid,'noise':noise,'seed':seed,'samples':samples,'actualGaps':gaps,
                                  **estimate,**exp.score(p,t,estimate)})
    save(OUT/'history-sensitivity.json',histories)
    save(OUT/'original-verified-after-solves.json',{'filesUnchanged':verify_old()})
    print(json.dumps({'solverTargets':[(r['id'],r['method']) for r in results],'tieCertificates':len(rays),'historyRefits':len(histories)}),flush=True)


def order_audit(pid):
    seal();_,problems,truth,primary=data();p=problems[pid];t=truth[pid]
    dest=OUT/f'order/problem-{pid}.json'
    if dest.exists():return
    results=[]
    for r in [v for v in primary if v['id']==pid]:
        cases=[]
        for k,s in enumerate(p['testContexts']):
            x,v=exp.forward(s,p['bank'],r['theta'])
            ss,bb,order=permute(s,p['bank'],17,True)
            xx,vv=exp.forward(ss,bb,r['theta']);rev=np.zeros(len(order))
            for j,col in enumerate(order):rev[col]=xx[j]
            if abs(v-vv)>1e-5:raise ValueError('Reordering changed optimal predicted objective')
            opt=t['oracles'][20+k]['objective']
            original_cost=float(np.dot(s['base'],x)+np.dot(t['truth'],exp.features(s,p['bank'],x)))
            reversed_cost=float(np.dot(s['base'],rev)+np.dot(t['truth'],exp.features(s,p['bank'],rev)))
            cases.append({'context':s['id'],'originalDecision':x.tolist(),'reversedDecision':rev.tolist(),
                'originalPredictedObjective':v,'reversedPredictedObjective':vv,'oracleObjective':opt,
                'originalRegret':max(0,original_cost-opt)/max(1,abs(opt)),
                'reversedRegret':max(0,reversed_cost-opt)/max(1,abs(opt))})
        if abs(st.mean(c['originalRegret'] for c in cases)-r['normalizedRegret'])>1e-7:raise ValueError('Original score not reproduced')
        results.append({'id':pid,'method':r['method'],'originalRegret':r['normalizedRegret'],
                        'reversedRegret':st.mean(c['reversedRegret'] for c in cases),'contexts':cases})
    save(dest,results);print(json.dumps({'order':pid}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['describe','profile','sensitivity','order','verify']);parser.add_argument('--id',type=int);a=parser.parse_args()
    if a.mode=='describe':descriptive()
    elif a.mode=='profile':profiles(a.id)
    elif a.mode=='sensitivity':sensitivity()
    elif a.mode=='order':order_audit(a.id)
    else:print(json.dumps({'unchanged':verify_old()}))
