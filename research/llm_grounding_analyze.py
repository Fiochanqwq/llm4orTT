"""Analyze every scheduled outcome and audit API/solver evidence; never retry failures."""
import csv,hashlib,itertools,json,math,statistics as st,sys
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/inverse/deepseek-grounding-20261020-v1'
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def save(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def fkey(f):return f'linear:{f["variable"]}:{f["sign"]}' if f['kind']=='linear' else f'excess:{f["monitor"]}:{float(f["threshold"]):.6f}'
def objective(m,base,features,theta,x):
    total=sum(a*b for a,b in zip(base,x))
    for f,t in zip(features,theta):
        v=f['sign']*x[m['names'].index(f['variable'])] if f['kind']=='linear' else max(0,sum(a*b for a,b in zip(m['monitors'][f['monitor']],x))-f['threshold'])
        total+=t*v
    return total
def close(x,y):
    if abs(x-y)>2e-5*max(1,abs(x),abs(y)):raise AssertionError((x,y))
def bootstrap(values):
    if not values:return None
    rng=np.random.default_rng(20261020);v=np.array(values);means=np.mean(v[rng.integers(0,len(v),(5000,len(v)))],axis=1)
    return np.quantile(means,[.025,.975]).tolist()
def main():
    cfg=read(OUT/'protocol.json');audit=read(OUT/'source-audit.json');models=read(OUT/'models.json')
    rows=[];jobs=[]
    for dirname in ['jobs','feedback-results','clarified-results']:
        for p in sorted((OUT/dirname).glob('*.json')):
            j=read(p);jobs.append(j);rows.extend(j['rows'])
    index={(r['id'],r['seed'],r['K'],r['noise'],r['method']):r for r in rows}
    assert len(index)==len(rows),'duplicate results'
    schedule=[]
    for source in audit:
        sid=source.get('id',('opt-' if source['collection']=='OptMATH' else 'mamo-')+str(source['sourceId']))
        for seed,K,noise in itertools.product(cfg['seeds'],cfg['K'],cfg['noiseCaps']):
            methods=[m for m in cfg['methods'] if K==10 or m!='ds_anchor']+(['ds_direct','ds_feedback','ds_clarified_io','clarified_no_logs_io','clarified_shuffled_io'] if K==10 else [])
            for method in methods:
                key=(sid,seed,K,noise,method)
                r=index.get(key)
                if r is None:
                    r={'id':sid,'collection':source['collection'],'seed':seed,'K':K,'noise':noise,'method':method,
                       'status':'blocked_source' if source['status']!='admitted' else 'not_completed',
                       'error':source.get('error','missing completed worker record')}
                schedule.append(r)
    rows=schedule
    methods=cfg['methods']+['ds_direct','ds_feedback','ds_clarified_io','clarified_no_logs_io','clarified_shuffled_io']
    summaries=[];source_summaries=[]
    for collection,K,noise,method in itertools.product(['NL4Opt','MAMO','OptMATH'],cfg['K'],cfg['noiseCaps'],methods):
        subset=[r for r in rows if (r['collection'],r['K'],r['noise'],r['method'])==(collection,K,noise,method)]
        if not subset:continue
        eligible=[r for r in subset if r['status']!='blocked_source'];valid=[r for r in eligible if r['status']=='complete']
        per=[]
        for sid in sorted({r['id'] for r in eligible}):
            sr=[r for r in eligible if r['id']==sid];vv=[r for r in sr if r['status']=='complete'];values=[r['meanRegret'] for r in vv]
            s={'id':sid,'collection':collection,'K':K,'noise':noise,'method':method,'scheduled':len(sr),'complete':len(vv),
               'mean':st.mean(values) if len(vv)==len(sr) else None,'successfulOnly':st.mean(values) if values else None,
               'min':min(values) if values else None,'median':st.median(values) if values else None,'max':max(values) if values else None}
            per.append(s);source_summaries.append(s)
        vals=[r['meanRegret'] for r in valid]
        summaries.append({'collection':collection,'K':K,'noise':noise,'method':method,'scheduled':len(eligible),'complete':len(valid),
                          'blockedSource':len(subset)-len(eligible),'mean':st.mean(s['mean'] for s in per) if per and all(s['mean'] is not None for s in per) else None,
                          'successfulOnlyMean':st.mean(vals) if vals else None,'min':min(vals) if vals else None,'median':st.median(vals) if vals else None,'max':max(vals) if vals else None,
                          'relativeMAE':st.mean(r['relativeMAE'] for r in valid) if valid else None,
                          'candidateF1':st.mean(r['structureBefore']['f1'] for r in valid) if valid else None,'prunedF1':st.mean(r['structureAfter']['f1'] for r in valid) if valid else None})
    contrasts=[]
    pairs=[('ds_io',m) for m in ['unit','all_io','no_logs_io','shuffled_io','ds_no_l1','ds_direct']]+[('ds_feedback','ds_io'),('ds_anchor','ds_io'),('subgradient','ds_io')]+[('ds_clarified_io',m) for m in ['ds_io','unit','all_io','clarified_no_logs_io','clarified_shuffled_io']]
    for collection,(left,right) in itertools.product(['NL4Opt','MAMO','OptMATH'],pairs):
        l={r['id']:r for r in source_summaries if (r['collection'],r['K'],r['noise'],r['method'])==(collection,10,.1,left)}
        rr={r['id']:r for r in source_summaries if (r['collection'],r['K'],r['noise'],r['method'])==(collection,10,.1,right)}
        ids=sorted(i for i in l if i in rr and l[i]['mean'] is not None and rr[i]['mean'] is not None)
        diffs=[l[i]['mean']-rr[i]['mean'] for i in ids]
        contrasts.append({'collection':collection,'left':left,'right':right,'sourceIds':ids,'omittedIds':sorted((set(l)|set(rr))-set(ids)),
                          'n':len(ids),'meanDifference':st.mean(diffs) if diffs else None,'ci95':bootstrap(diffs),
                          'wins':sum(d<-1e-8 for d in diffs),'ties':sum(abs(d)<=1e-8 for d in diffs),'losses':sum(d>1e-8 for d in diffs),
                          'scope':'unadjusted exploratory source-paired bootstrap; same model outputs shared across historical seeds'})
    raw=[read(p) for p in sorted((OUT/'llm/raw').glob('*.json'))]
    usage=Counter();api_status=Counter();models_returned=Counter();stage_usage=defaultdict(Counter)
    for r in raw:
        api_status[r['status']]+=1;models_returned[r.get('returnedModel','unknown')]+=1
        u=r.get('usage') or {}
        for name,field in [('input','prompt_tokens'),('output','completion_tokens'),('cacheHit','prompt_cache_hit_tokens')]:
            usage[name]+=u.get(field,0);stage_usage[r['stage']][name]+=u.get(field,0)
        stage_usage[r['stage']]['attempts']+=1;stage_usage[r['stage']][r['status']]+=1
    peak=(max(0,usage['input']-usage['cacheHit'])*2+usage['cacheHit']*.04+usage['output']*8)/1e6
    # Verify explicit arithmetic and feasibility without calling the inference implementation.
    checks=0;witnesses=[];tied=[];exposure=[]
    originals={m['id']:read(OUT/'oracle'/f'{m["id"]}.json') for m in models}
    contexts={(m['id'],seed):read(OUT/'contexts'/f'{m["id"]}-s{seed}.json') for m in models for seed in cfg['seeds']}
    for (sid,seed),ss in contexts.items():
        item=originals[sid];m=item['model']
        for s in ss:
            if s['status']!='complete':continue
            close(objective(m,s['base'],item['trueFeatures'],item['truth'],s['oracleDecision']),s['oracleObjective']);checks+=1
            for cap,x in s.get('decisions',{}).items():
                true=objective(m,s['base'],item['trueFeatures'],item['truth'],x)
                assert true-s['oracleObjective']<=float(cap)*max(1,abs(s['oracleObjective']))+1e-4;checks+=1
        active=[]
        for f in item['trueFeatures']:
            active.append(sum(abs(objective(m,[0]*len(m['names']),[f],[1],s['oracleDecision']))>1e-6 for s in ss[10:] if s['status']=='complete'))
        exposure.append({'id':sid,'seed':seed,'testActivationCounts':active})
    for r in rows:
        if r['status']!='complete':continue
        item=originals[r['id']];m=item['model'];cs={s['context']:s for s in contexts[r['id'],r['seed']]}
        for t in r['tests']:
            if t['status']!='complete':continue
            s=cs[t['context']];x=t['decision']
            close(objective(m,s['base'],r['features'],r['fit']['theta'],x),t['predictedCost'])
            close(objective(m,s['base'],item['trueFeatures'],item['truth'],x),t['trueCost'])
            assert t['trueCost']>=t['oracleCost']-1e-4
            close(max(0,t['trueCost']-t['oracleCost'])/max(1,abs(t['oracleCost'])),t['regret'])
            if m['kind']=='tour':assert any(np.max(abs(np.array(v)-x))<1e-5 for v in m['choices'])
            else:
                ax=np.array(m['A'])@x
                assert np.min(ax-np.array(m['rl']))>=-1e-4 and np.min(np.array(m['ru'])-ax)>=-1e-4
                assert min(np.array(x)-np.array(m['lb']))>=-1e-4 and min(np.array(m['ub'])-x)>=-1e-4
                if m['integer']:assert max(abs(np.array(x)-np.round(x)))<1e-5
            checks+=5
        close(st.mean(t['regret'] for t in r['tests']),r['meanRegret']);checks+=1
        if r['method'] in ['ds_io','ds_feedback','ds_anchor','ds_clarified_io'] and r['K']==10 and r['noise']==.1:
            witnesses.append({k:r[k] for k in ['id','collection','seed','method','meanRegret','relativeMAE','structureBefore','structureAfter','features','fit']})
    # Observable competing-plan ties: never call them a global worst-face bound.
    primary=[r for r in rows if r['K']==10 and r['noise']==.1 and r['status']=='complete']
    for r in [r for r in primary if r['method']=='ds_io']:
        item=originals[r['id']];m=item['model'];ss={s['context']:s for s in contexts[r['id'],r['seed']]}
        others=[q for q in primary if q['id']==r['id'] and q['seed']==r['seed']]
        for t in r['tests']:
            for q in others:
                alt=next((v for v in q['tests'] if v['context']==t['context'] and v['status']=='complete'),None)
                if alt is None:continue
                altpred=objective(m,ss[t['context']]['base'],r['features'],r['fit']['theta'],alt['decision'])
                diff=abs(altpred-t['predictedCost']);truegap=abs(alt['trueCost']-t['trueCost'])
                if diff<=1e-6*max(1,abs(t['predictedCost'])) and truegap>1e-5:
                    tied.append({'id':r['id'],'seed':r['seed'],'context':t['context'],'alternativeMethod':q['method'],
                                 'predictedA':t['predictedCost'],'predictedB':altpred,'trueA':t['trueCost'],'trueB':alt['trueCost'],
                                 'normalizedTrueGap':truegap/max(1,abs(t['oracleCost'])),'distanceL1':float(np.sum(abs(np.array(t['decision'])-alt['decision']))),
                                 'decisionA':t['decision'],'decisionB':alt['decision']})
    # Check frozen file hashes and API payload partition.
    for manifest in ['freeze.json','execution-code-freeze.json']:
        for rel,h in read(OUT/manifest)['files'].items():
            p=(OUT if manifest=='freeze.json' else ROOT)/rel
            assert hashlib.sha256(p.read_bytes()).hexdigest()==h;checks+=1
    forbidden={'truth','trueFeatures','sourceAnswer','oracleDecision','oracleObjective','testContexts'}
    def audit_keys(o):
        nonlocal checks
        if isinstance(o,dict):
            assert not forbidden.intersection(o);checks+=1
            for v in o.values():audit_keys(v)
        if isinstance(o,list):
            for v in o:audit_keys(v)
    for p in (OUT/'requests').glob('*.json'):audit_keys(read(p))
    # Generated logs are not independently verified natural human evidence.
    proposal_audit=[]
    for meta in models:
        item=originals[meta['id']]
        for mode in ['proposal','no_logs','shuffled','clarified','clarified_no_logs','clarified_shuffled']:
            p=OUT/'llm'/mode/f'{meta["id"]}.json'
            rr=read(p) if p.exists() else {'status':'missing'}
            try:
                sys.path.insert(0,str(ROOT/'research'))
                from llm_grounding import compile_features,structure
                fs=compile_features(item['public'],rr['value'])
                proposal_audit.append({'id':meta['id'],'collection':meta['collection'],'mode':mode,'status':'valid','features':fs,'structure':structure(fs,item['trueFeatures'])})
            except Exception as e:proposal_audit.append({'id':meta['id'],'collection':meta['collection'],'mode':mode,'status':'invalid','error':str(e)})
    ledger=read(OUT/'local-ledger.json');fl=read(OUT/'feedback-ledger.json')
    resources={'workerCPUSeconds':sum(j['cpuSeconds'] for j in jobs),'workerWallSecondsSum':sum(j['wallSeconds'] for j in jobs),
               'forwardCalls':sum(j['stats'].get('forwardCalls',0) for j in jobs),'solverSeconds':sum(j['stats'].get('solverSeconds',0) for j in jobs),
               'mainLedger':ledger,'feedbackLedger':fl,
               'scope':'Completed per-worker local evaluate stages, not API wait, history-preparation process, analysis or packaging; incomplete jobs retained separately. Whole-machine power not measured.'}
    analysis={'scheduled':len(rows),'originalScheduled':sum('clarified' not in r['method'] for r in rows),'postHocPromptScheduled':sum('clarified' in r['method'] for r in rows),'statusCounts':dict(Counter(r['status'] for r in rows)),
              'primarySummaries':[r for r in summaries if r['K']==10 and r['noise']==.1],'summaries':summaries,
              'sourceSummaries':source_summaries,'contrasts':contrasts,'proposalAudit':proposal_audit,
              'lowRegretWrongPrice':sorted([r for r in witnesses if r['meanRegret']<.01],key=lambda r:-r['relativeMAE'])[:12],
              'tieWitnesses':sorted(tied,key=lambda r:-r['normalizedTrueGap'])[:20],
              'exposure':exposure,'failures':[{k:r.get(k) for k in ['id','collection','seed','K','noise','method','status','error']} for r in rows if r['status']!='complete'],
              'api':{'attempts':len(raw),'status':dict(api_status),'tokens':dict(usage),'returnedModels':dict(models_returned),'byStage':{k:dict(v) for k,v in stage_usage.items()},
                     'tokenBasedCNYRange':[peak*.5,peak],'rangeAssumption':'all tokens billed at off-peak vs peak; not invoice','unknownUsageCalls':sum(not bool(r.get('usage')) for r in raw)},
              'resources':resources,'verificationAssertions':checks}
    save(OUT/'all-results.json',rows);save(OUT/'analysis.json',analysis)
    save(OUT/'verification.json',{'status':'passed','assertions':checks,'scope':'Frozen hashes, prompt key partition, original decision cost arithmetic, noise caps, test feasibility/integrality, score arithmetic. Independent source checks separately.'})
    fields=['id','collection','seed','K','noise','method','status','meanRegret','relativeMAE','priceMAE','nuisanceWeight','seconds','error']
    with (OUT/'all-results.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
    print(json.dumps({'scheduled':len(rows),'statuses':analysis['statusCounts'],'api':analysis['api'],'checks':checks},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
