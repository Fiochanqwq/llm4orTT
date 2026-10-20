"""Executable evidence checks for the forensic audit, independent of plotting."""
import json
import statistics as st
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import mamo_audit as a
import numpy as np


def main():
    checks=[]
    def ck(name,ok,detail=None):
        checks.append({'name':name,'passed':bool(ok),'detail':detail})
        if not ok:raise AssertionError(name)
    ck('original evidence unchanged',a.verify_old()>0,a.verify_old())
    rows,problems,truth,primary=a.data();d=a.read(a.OUT/'descriptive.json')
    ck('original complete row count',len(rows)==4274,len(rows))
    ck('primary complete and no failed cases',len(primary)==341 and all(r['status']=='optimal' for r in primary))
    for method,summary in d['methods'].items():
        rr=[r for r in primary if r['method']==method]
        ck('all 31 cases:'+method,len(rr)==31 and len({r['id'] for r in rr})==31)
        ck('mean recomputation:'+method,abs(st.mean(r['normalizedRegret'] for r in rr)-summary['mean'])<1e-12)
    for n in d['noise']:
        ck('noise contribution identity:'+str((n['K'],n['low'])),abs(sum(v['contributionToMean'] for v in n['pairs'])-(n['highMean']-n['lowMean']))<1e-12)
    act={r['id']:r for r in d['activation']};profiles=[];witnesses=[]
    for pid in sorted(problems):
        p=problems[pid];r=a.read(a.OUT/f'profiles/problem-{pid}.json');profiles.append(r)
        samples=p['histories']['0.1'][:10]
        ck('profile empirical minimum:'+str(pid),r['minimum']>=-1e-8)
        for v in r['parameters']:
            j=v['feature'];lo,hi=v['lower']['bound'],v['upper']['bound']
            ck('profile ordered bounded:'+str((pid,j)),-1e-7<=lo<=hi+1e-7 and hi<=20+1e-7)
            for side in ['lower','upper']:
                w=v[side];actual=a.exp.loss(samples,p['bank'],w['witness'])/r['scale']
                ck('profile witness loss:'+str((pid,j,side)),abs(actual-w['normalizedLoss'])<1e-7 and actual<=w['lossCap']+1e-6)
                ck('profile target witness:'+str((pid,j,side)),abs(w['witness'][j]-w['bound'])<1e-7)
            if act[pid]['hidden'][j]['positiveHistories']==0:
                tt=v['upper']['witness'].copy();tt[j]=100
                actual=a.exp.loss(samples,p['bank'],tt)/r['scale']
                ck('inactive upper bound is artificial:'+str((pid,j)),hi>=20-1e-7 and actual<=v['upper']['lossCap']+1e-6)
                witnesses.append({'id':pid,'feature':j,'theta':tt,'normalizedLoss':actual,'lossCap':v['upper']['lossCap'],
                    'meaning':'outside original estimation box, diagnostic only; monotonicity proves no finite data-derived upper bound'})
        rr=a.read(a.OUT/f'order/problem-{pid}.json')
        ck('all methods in order sensitivity:'+str(pid),len(rr)==11)
        for row in rr:
            original=next(v for v in primary if v['id']==pid and v['method']==row['method'])
            ck('all original decisions rescored:'+str((pid,row['method'])),len(row['contexts'])==20 and abs(st.mean(v['originalRegret'] for v in row['contexts'])-original['normalizedRegret'])<1e-7)
            ck('equal predicted optimum under permutation:'+str((pid,row['method'])),max(abs(v['originalPredictedObjective']-v['reversedPredictedObjective']) for v in row['contexts'])<1e-5)
            ck('reversed score recomputation:'+str((pid,row['method'])),abs(st.mean(v['reversedRegret'] for v in row['contexts'])-row['reversedRegret'])<1e-12)
    rays=a.read(a.OUT/'tie-certificates.json')
    for r in rays:
        p=problems[r['id']];s=p['testContexts'][0];t=np.array(r['theta']);x=np.array(r['x']);direction=np.array(r['direction'])
        ck('unbounded optimal-ray witness:'+str((r['id'],r['method'])),
           min(direction)>=0 and min(np.asarray(s['A'])@direction)>=0 and np.max(abs(direction-np.round(direction)))<1e-9
           and abs(np.dot(s['base'],direction)+np.dot(t,a.exp.features(s,p['bank'],x+direction)-a.exp.features(s,p['bank'],x)))<1e-7
           and r['trueCostSlope']>0 and max(abs(v) for v in t[2:])<1e-12)
    for r in a.read(a.OUT/'history-sensitivity.json'):
        p=problems[r['id']];t=truth[r['id']]
        for k,s in enumerate(r['samples']):
            original=p['histories']['0.1'][k]
            ck('unchanged training context:'+str((r['id'],r['noise'],r['seed'],k)),all(s[f]==original[f] for f in ['id','A','b','base']))
            x=np.array(s['decision']);cost=float(np.dot(s['base'],x)+np.dot(t['truth'],a.exp.features(s,p['bank'],x)));opt=t['oracles'][k]['objective']
            ck('new history feasible and inside declared cap:'+str((r['id'],r['noise'],r['seed'],k)),min(np.asarray(s['A'])@x-s['b'])>=-1e-6 and max(abs(x-np.round(x)))<1e-8 and -1e-7<=(cost-opt)/max(1,abs(opt))<=r['noise']+1e-6)
        rescored=a.exp.score(p,t,r)
        ck('same held-out test set and metric:'+str((r['id'],r['noise'],r['seed'])),abs(rescored['normalizedRegret']-r['normalizedRegret'])<1e-8)
    a.save(a.OUT/'inactive-unbounded-price-witnesses.json',witnesses)
    a.save(a.OUT/'verification.json',{'status':'passed','count':len(checks),'checks':checks,'originalFilesUnchanged':a.verify_old(),'paidCalls':0})
    print(json.dumps({'status':'passed','checks':len(checks),'inactivePriceWitnesses':len(witnesses)}))


if __name__=='__main__':main()
