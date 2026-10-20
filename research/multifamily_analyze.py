"""Recompute published summaries from every frozen row; never alter raw results."""
import csv
import itertools
import json
import math
import statistics as st
from collections import Counter
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import numpy as np
import multifamily as m

OUT=m.OUT
def mean(v):return float(np.mean(v))
def paired(a,b):
    ids=sorted(set(a)&set(b))
    delta=np.array([a[i]-b[i] for i in ids])
    rng=np.random.default_rng(20261021)
    boots=np.mean(rng.choice(delta,(5000,len(delta)),replace=True),axis=1)
    return {'nSources':len(ids),'difference':mean(delta),'ci95':np.quantile(boots,[.025,.975]).tolist(),
            'wins':int(sum(delta < -1e-8)),'ties':int(sum(abs(delta)<=1e-8)),'losses':int(sum(delta>1e-8)),
            'unit':'normalized regret; negative favors first method','inference':'exploratory percentile bootstrap; no multiplicity correction'}

def main():
    cfg=m.read(OUT/'protocol.json');freeze=m.read(OUT/'freeze.json')
    checks=[]
    def check(ok,name):
        if not ok:raise AssertionError(name)
        checks.append(name)
    check(m.digest(m.CFG)==freeze['protocolSha256'],'protocol unchanged')
    check(m.digest(Path(m.__file__))==freeze['sourceSha256'],'experiment implementation unchanged since freeze')
    for name,sha in freeze['files'].items():check(m.digest(OUT/name)==sha,'frozen '+name)
    models=m.read(OUT/'models.json')
    rows=[r for p in sorted((OUT/'rows').glob('*.json')) for r in m.read(p)['rows']]
    keys=[(r['id'],r['seed'],r['K'],r['noise'],r['method']) for r in rows]
    expected=set(itertools.product([v['id'] for v in models],cfg['seeds'],cfg['K'],cfg['noise_gap_caps'],cfg['methods']))
    check(len(keys)==len(set(keys)) and set(keys)==expected,'complete unique scheduled rows including failures')
    for p in sorted((OUT/'contexts').glob('*.json')):
        rec=m.read(p);ss=rec['contexts']
        check(len(ss)==40 and len(set(s['context'] for s in ss))==40,'disjoint 20 training / 20 test '+p.name)
        for s in ss:
            truth=np.array(s['base'])+np.array(s['F'])@np.array(rec['truth'])
            opt=s['oracleObjective']
            check(abs(float(truth@np.array(s['oracleDecision']))-opt)<1e-5,'oracle recorded cost '+s['context'])
            if 'decisions' in s:
                for cap,x in s['decisions'].items():
                    xx=np.array(x)
                    feasible=(min(np.array(s['A'])@xx-s['b'])>=-1e-5 and min(xx)>=-1e-7) if s['family']=='relocation' else any(np.allclose(xx,y) for y in s['choices'])
                    check(feasible,'history feasible '+s['context']+' '+cap)
                    gap=(float(truth@xx)-opt)/max(1,abs(opt))
                    check(-1e-6<=gap<=float(cap)+1e-6,'history noise cap '+s['context']+' '+cap)
    for r in rows:
        if r['status']=='failed':continue
        ctx=m.read(OUT/f'contexts/p{r["id"]}-s{r["seed"]}.json')
        ss={s['context']:s for s in ctx['contexts'][20:]}
        check(set(d['context'] for d in r['testDetails'])==set(ss),'same test cohort '+str((r['id'],r['seed'],r['K'],r['noise'],r['method'])))
        vals=[]
        for d in r['testDetails']:
            s=ss[d['context']];x=np.array(d['decision'])
            feasible=(min(np.array(s['A'])@x-s['b'])>=-1e-5 and min(x)>=-1e-7) if s['family']=='relocation' else any(np.allclose(x,y) for y in s['choices'])
            check(feasible,'predicted decision feasible')
            truec=np.array(s['base'])+np.array(s['F'])@np.array(ctx['truth'])
            reg=max(0,float(truec@x)-s['oracleObjective'])/max(1,abs(s['oracleObjective']))
            check(abs(reg-d['regret'])<1e-7,'test regret recalculation')
            check(d['bestTieRegret']<=reg+1e-6 and (d['worstTieRegret'] is None or reg<=d['worstTieRegret']+1e-6),'optimal-face bounds contain default')
            vals.append(reg)
        check(abs(st.mean(vals)-r['normalizedRegret'])<1e-9,'20-context row mean')
    m.save(OUT/'all-results.json',rows)
    fields=['id','family','split','seed','K','noise','method','status','normalizedRegret','bestTieMean','worstTieMean','unboundedTieContexts','hiddenMAE','hiddenNormalizedMAE','unusedHiddenCount','error']
    with (OUT/'all-results.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fields,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
    source=[];summaries=[];comparisons=[]
    for family,K,noise,method in itertools.product(cfg['candidate_source_ids'],cfg['K'],cfg['noise_gap_caps'],cfg['methods']):
        selected=[r for r in rows if (r['family'],r['K'],r['noise'],r['method'],r['split'])==(family,K,noise,method,'evaluation')]
        groups=[]
        for pid in sorted(set(r['id'] for r in selected)):
            rr=[r for r in selected if r['id']==pid];valid=[r for r in rr if r['status']!='failed']
            record={'family':family,'id':pid,'K':K,'noise':noise,'method':method,'scheduled':len(rr),'failed':len(rr)-len(valid)}
            if len(valid)==len(rr):
                vals=[r['normalizedRegret'] for r in rr]
                record.update(mean=st.mean(vals),minimum=min(vals),median=st.median(vals),maximum=max(vals),
                    bestTie=st.mean(r['bestTieMean'] for r in rr),
                    worstTie=None if any(r['worstTieMean'] is None for r in rr) else st.mean(r['worstTieMean'] for r in rr),
                    unboundedContexts=sum(r['unboundedTieContexts'] for r in rr),hiddenMAE=st.mean(r['hiddenMAE'] for r in rr),
                    unusedHiddenMin=min(r['unusedHiddenCount'] for r in rr),unusedHiddenMax=max(r['unusedHiddenCount'] for r in rr))
            source.append(record);groups.append(record)
        summary={'family':family,'K':K,'noise':noise,'method':method,'sources':len(groups),'runs':len(selected),'failed':sum(g['failed'] for g in groups)}
        if summary['failed']==0:
            summary.update(mean=st.mean(g['mean'] for g in groups),medianSource=st.median(g['mean'] for g in groups),
                minimumSource=min(g['mean'] for g in groups),maximumSource=max(g['mean'] for g in groups),
                minimumRun=min(r['normalizedRegret'] for r in selected),medianRun=st.median(r['normalizedRegret'] for r in selected),maximumRun=max(r['normalizedRegret'] for r in selected),
                bestTie=st.mean(g['bestTie'] for g in groups),worstTie=None if any(g['worstTie'] is None for g in groups) else st.mean(g['worstTie'] for g in groups),
                unboundedContexts=sum(g['unboundedContexts'] for g in groups),hiddenMAE=st.mean(g['hiddenMAE'] for g in groups))
        summaries.append(summary)
    for family,K,noise,method,reference in itertools.product(cfg['candidate_source_ids'],cfg['K'],cfg['noise_gap_caps'],cfg['methods'],['fixed_midpoint','known_cost_median','text_sparse_io']):
        if method==reference:continue
        a={r['id']:r['mean'] for r in source if (r['family'],r['K'],r['noise'],r['method'])==(family,K,noise,method) and not r['failed']}
        b={r['id']:r['mean'] for r in source if (r['family'],r['K'],r['noise'],r['method'])==(family,K,noise,reference) and not r['failed']}
        comparisons.append({'family':family,'K':K,'noise':noise,'method':method,'reference':reference,**paired(a,b)})
    m.save(OUT/'analysis.json',{'scope':'exploratory frozen local extension; development sources excluded from all comparative summaries',
        'rows':len(rows),'failures':sum(r['status']=='failed' for r in rows),'summaries':summaries,'sourceSummaries':source,'comparisons':comparisons})
    m.save(OUT/'verification.json',{'status':'passed','checks':len(checks),'scheduledRows':len(expected),'failedRows':sum(r['status']=='failed' for r in rows),
        'details':dict(Counter(n.split(' ')[0] for n in checks)),'scope':'all input hashes, schedule, history feasibility/noise, predictions feasibility, score arithmetic and recorded envelope inequalities; independent optimization checks separate'})
    print(json.dumps({'verified':len(checks),'rows':len(rows),'failures':sum(r['status']=='failed' for r in rows)}))
    for c in comparisons:
        if c['K']==20 and c['noise']==.1 and c['method'] in ['projected_subgradient','prior_center_io','text_sparse_io'] and c['reference']=='fixed_midpoint':print(json.dumps(c))

if __name__=='__main__':main()
