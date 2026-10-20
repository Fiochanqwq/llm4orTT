"""Audit all scheduled outcomes, including failures and blocked sources."""
import csv,itertools,json,statistics as st,sys
from collections import Counter
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import stress_public as s
import numpy as np
OUT=s.OUT
def summarize():
 cfg=s.read(OUT/'protocol.json');freeze=s.read(OUT/'freeze.json');audit=s.read(OUT/'source-audit.json')
 checks=0
 def check(ok,msg):
  nonlocal checks
  if not ok:raise AssertionError(msg)
  checks+=1
 check(s.sha(s.CFG)==freeze['protocolSha256'],'protocol hash')
 check(s.sha(Path(s.__file__))==freeze['implementationSha256'],'implementation hash')
 for name,h in freeze['files'].items():check(s.sha(OUT/name)==h,'input hash '+name)
 jobs=[s.read(p) for p in sorted((OUT/'jobs').glob('*.json'))]
 ledger=s.read(OUT/'execution-ledger.json');records={(j['id'],j['seed']):j for j in jobs}
 rows=[];profiles=[];events=[];exposure=[]
 for family,ids in cfg['datasets'].items():
  for name,seed,K,noise,method in itertools.product(ids,cfg['seeds'],cfg['K'],cfg['noiseCaps'],cfg['methods']):
   j=records.get((name,seed))
   found=[r for r in j['rows'] if (r['K'],r['noise'],r['method'])==(K,noise,method)] if j else []
   check(len(found)<=1,'unique result')
   reason=next(r for r in audit if r['id']==name)
   rows.append(found[0] if found else {'id':name,'family':family,'seed':seed,'K':K,'noise':noise,'method':method,'status':'blocked_source' if reason['status']!='admitted' else 'missing_after_process_exit','error':reason.get('error','No completed row; see execution ledger'),'meanRegret':None})
 for j in jobs:
  rec=s.read(OUT/f'inputs/{j["id"]}-s{j["seed"]}.json');derived=s.read(OUT/f'derived/{j["id"]}-s{j["seed"]}.json');m=rec['model'];F=np.array(rec['F']);truth=np.array(rec['truth'])
  check(len(derived)==20 and len(set(x['context'] for x in derived))==20,'10 disjoint train /10 test')
  for d in derived:
   if d['status']!='optimal':continue
   truec=np.array(d['base'])+F@truth
   check(s.feasible(m,d['oracle']),'oracle feasible')
   check(abs(float(truec@d['oracle'])-d['optimum'])<1e-5,'oracle cost')
   for cap,x in d.get('decisions',{}).items():
    check(s.feasible(m,x),'history feasible')
    gap=(float(truec@x)-d['optimum'])/max(1,abs(d['optimum']))
    check(-1e-6<=gap<=float(cap)+1e-5,'history cap')
  validtest=[d for d in derived[10:] if d['status']=='optimal']
  shares=[]
  for d in validtest:
   x=np.array(d['oracle']);truec=np.array(d['base'])+F@truth
   shares.append(float(np.sum(abs((F@truth)*x)))/max(1e-12,float(np.sum(abs(truec*x)))))
  exposure.append({'id':j['id'],'family':m['family'],'seed':j['seed'],'truth':rec['truth'],'knownOnlyScale':rec['scale'],'truthOutsideBox':rec['truthOutsideBox'],
    'testOracleHiddenAbsoluteCostShare':st.mean(shares) if shares else None,
    'testOracleInactiveHiddenCount':sum(all(abs(d['oracle'][rec['indices'][k]])<1e-8 for d in validtest) for k in range(2)) if validtest else None,
    'validOracleTests':len(validtest),'scope':'post-hoc mechanism diagnostic; absolute contribution share, not signed net objective share'})
  for r in j['rows']:
   vals=[]
   for detail in r.get('testDetails',[]):
    if detail['status']!='optimal':continue
    d=next(x for x in derived[10:] if x['context']==detail['context'])
    truec=np.array(d['base'])+F@truth;chat=np.array(d['base'])+F@np.array(r['theta']);x=np.array(detail['decision'])
    check(s.feasible(m,x),'test feasible')
    gap=max(0,float(truec@x)-d['optimum'])/max(1,abs(d['optimum']))
    check(abs(gap-detail['regret'])<1e-7,'regret arithmetic');vals.append(gap)
    for tag in ['best','worst']:
     if detail.get(tag+'Status')!='optimal':continue
     witness=np.array(detail[tag+'Decision']);check(s.feasible(m,witness),'face witness feasible')
     check(float(chat@witness)<=detail['predictedObjective']+1e-5,'face cost cap')
     g=max(0,float(truec@witness)-d['optimum'])/max(1,abs(d['optimum']))
     check(abs(g-detail[tag+'Regret'])<1e-7,'face regret arithmetic')
     check(g<=gap+1e-5 if tag=='best' else g>=gap-1e-5,'envelope inclusion')
   if r['status']=='complete':check(len(vals)==10 and abs(st.mean(vals)-r['meanRegret'])<1e-8,'complete mean')
  if 'profile' in j:profiles.append({'id':j['id'],'family':j['family'],'seed':j['seed'],**j['profile']})
  events.extend({'id':j['id'],'seed':j['seed'],**e} for e in j.get('events',[]))
 profilekeys={(p['id'],p['seed']) for p in profiles}
 for model in s.read(OUT/'models.json'):
  for seed in cfg['seeds']:
   if (model['id'],seed) not in profilekeys:profiles.append({'id':model['id'],'family':model['family'],'seed':seed,'status':'not_completed','error':'Worker ended before profile checkpoint; see execution ledger'})
 source=[];summary=[];comparisons=[]
 for family,K,noise,method in itertools.product(cfg['datasets'],cfg['K'],cfg['noiseCaps'],cfg['methods']):
  group=[r for r in rows if (r['family'],r['K'],r['noise'],r['method'])==(family,K,noise,method)]
  admitted=[a['id'] for a in audit if a['family']==family and a['status']=='admitted'];eligible=[r for r in group if r['id'] in admitted]
  valid=[r for r in eligible if r['status']=='complete']
  entries=[]
  for pid in admitted:
   rr=[r for r in eligible if r['id']==pid];vv=[r for r in rr if r['status']=='complete']
   e={'id':pid,'family':family,'method':method,'K':K,'noise':noise,'scheduled':len(rr),'completed':len(vv),'mean':None,'minimum':None,'median':None,'maximum':None}
   if len(vv)==len(rr):
    scores=[r['meanRegret'] for r in vv];e.update(mean=st.mean(scores),minimum=min(scores),median=st.median(scores),maximum=max(scores),relativeMAE=st.mean(r['relativeMAE'] for r in vv))
   source.append(e);entries.append(e)
  record={'family':family,'K':K,'noise':noise,'method':method,'candidateSources':len(cfg['datasets'][family]),'admittedSources':len(admitted),'scheduledEligible':len(eligible),'completeRuns':len(valid),'failedRuns':len(eligible)-len(valid),'blockedSourceRuns':len(group)-len(eligible),'completeSources':sum(e['mean'] is not None for e in entries),
   'fullCohortMean':st.mean(r['meanRegret'] for r in valid) if len(valid)==len(eligible) and valid else None,
   'successfulOnlyMean':st.mean(r['meanRegret'] for r in valid) if valid else None,
   'minimumRun':min((r['meanRegret'] for r in valid),default=None),'medianRun':st.median(r['meanRegret'] for r in valid) if valid else None,'maximumRun':max((r['meanRegret'] for r in valid),default=None),
   'meanLowerBound':sum(r['meanRegret'] for r in valid)/len(eligible) if eligible else None,'upperBound':'unbounded due to missing outcomes' if len(valid)!=len(eligible) else 'complete',
   'meanRelativeMAEOnSuccessful':st.mean(r['relativeMAE'] for r in valid) if valid else None}
  for tag in ['best','worst']:
   vv=[r.get(tag+'Mean') for r in eligible];record[tag+'FullMean']=st.mean(vv) if vv and all(v is not None for v in vv) else None
   record[tag+'FailedContexts']=sum(d.get(tag+'Status')=='failed' for r in eligible for d in r.get('testDetails',[]))
   record[tag+'UnboundedContexts']=sum(d.get(tag+'Status')=='unbounded' for r in eligible for d in r.get('testDetails',[]))
  summary.append(record)
 for family,K,noise,ref in itertools.product(cfg['datasets'],cfg['K'],cfg['noiseCaps'],['unit','midpoint','random','text_no_l1','full_l1']):
  aa={x['id']:x for x in source if (x['family'],x['K'],x['noise'],x['method'])==(family,K,noise,'text_l1')}
  bb={x['id']:x for x in source if (x['family'],x['K'],x['noise'],x['method'])==(family,K,noise,ref)}
  ids=sorted(i for i in aa if aa[i]['mean'] is not None and bb[i]['mean'] is not None)
  if not ids:
   comparisons.append({'family':family,'K':K,'noise':noise,'reference':ref,'n':0,'status':'insufficient_complete_sources'});continue
  delta=np.array([aa[i]['mean']-bb[i]['mean'] for i in ids]);rng=np.random.default_rng(20261022)
  boot=np.mean(rng.choice(delta,(5000,len(delta))),axis=1)
  comparisons.append({'family':family,'K':K,'noise':noise,'reference':ref,'n':len(ids),'sourceIds':ids,'omittedIncompleteIds':sorted(set(aa)-set(ids)),'meanDifference':float(np.mean(delta)),'ci95':np.quantile(boot,[.025,.975]).tolist(),'wins':int(sum(delta< -1e-8)),'ties':int(sum(abs(delta)<=1e-8)),'losses':int(sum(delta>1e-8)),'status':'exploratory_complete_source_pairs_only'})
 primary=[r for r in rows if r['K']==10 and r['noise']==.1 and r['method']=='text_l1' and r['status']=='complete']
 mismatch=sorted(primary,key=lambda r:(r['relativeMAE'] if r['meanRegret']<=.01 else -1),reverse=True)
 facecases=[]
 for r in primary:
  for d in r.get('testDetails',[]):
   if d.get('worstStatus')=='optimal':facecases.append({'id':r['id'],'family':r['family'],'seed':r['seed'],'theta':r['theta'],**d})
 facecases.sort(key=lambda d:d['worstRegret']-d['regret'],reverse=True)
 failures=[{'id':r['id'],'family':r['family'],'seed':r['seed'],'K':r['K'],'noise':r['noise'],'method':r['method'],'status':r['status'],'error':r.get('error'),'testErrors':[d for d in r.get('testDetails',[]) if d['status']!='optimal']} for r in rows if r['status']!='complete']
 diagfail=[{'id':r['id'],'seed':r['seed'],'method':r['method'],'context':d['context'],'side':tag,'error':d.get(tag+'Error',d.get(tag+'Status'))} for r in rows for d in r.get('testDetails',[]) for tag in ['best','worst'] if d.get(tag+'Status') in ['failed','unbounded']]
 facecounts=Counter(d[tag+'Status'] for r in rows for d in r.get('testDetails',[]) for tag in ['best','worst'] if tag+'Status' in d)
 facescheduled=sum(x['status']=='admitted' for x in audit)*len(cfg['seeds'])*len(cfg['methods'])*10*2
 facecounts['not_completed_or_not_attempted']=facescheduled-sum(facecounts.values())
 interruptions=[{'directory':p.parent.name,**s.read(p)} for p in sorted(OUT.glob('interrupted-v2-*/interruption.json'))]
 overlap=s.read(OUT/'overlapping-resume-discarded/incident.json') if (OUT/'overlapping-resume-discarded/incident.json').exists() else None
 resources={'wallSeconds':ledger['elapsedWallSeconds'],'wallScope':ledger.get('wallScope','uninterrupted elapsed wall'),'interruptions':interruptions,
  'interruptedCheckpointCPUSeconds':sum(x.get('recordedCPUSeconds',0) for x in interruptions[0].get('partial',[])) if interruptions else 0,
  'checkpointCPUScope':'First interruption only; overlapping resume snapshots are not additive and their total CPU is unknown.',
  'overlappingResumeIncident':overlap,
  'parallelWorkers':ledger['parallelWorkers'],'completedWorkerCPUSeconds':sum(j.get('cpuSeconds',0) for j in jobs),'CPUCompleteness':all(j['stage']=='complete' for j in jobs) and not interruptions,
  'unfinishedWorkerCheckpointCPUSeconds':sum(sum(r.get('cpuSeconds',0) for r in j['rows']) for j in jobs if j['stage']!='complete'),
  'peakWorkerRSSBytes':max((j.get('peakProcessRSSBytes') or 0 for j in jobs),default=0),'forwardCalls':sum(j.get('resources',{}).get('forwardCalls',0) for j in jobs),'solverSeconds':sum(j.get('resources',{}).get('solverSeconds',0) for j in jobs),'paidApiCalls':0,'apiCost':0,
  'scope':'Final v2 completed jobs; interrupted v2 checkpoint CPU reported separately and uncheckpointed work unknown. Download, analysis, independent checks and interrupted v1 separate. RSS is largest worker peak, not concurrent whole-machine memory or electricity.'}
 errors=Counter(r['status']+': '+str(r.get('error','per-test failure')) for r in failures if r['status']!='blocked_source')
 result={'schedule':len(rows),'statusCounts':dict(Counter(r['status'] for r in rows)),'executionStatusCounts':dict(Counter(j['status'] for j in ledger['jobs'])),'faceCheckStatusCounts':dict(facecounts),'faceChecksScheduled':facescheduled,'summaries':summary,'sourceSummaries':source,'comparisons':comparisons,'profiles':profiles,'exposure':exposure,'failures':failures,'failureKinds':dict(errors),'diagnosticFailures':diagfail,'events':events,'resources':resources,
  'lowRegretHighErrorExamples':[{k:r.get(k) for k in ['id','family','seed','theta','meanRegret','relativeMAE','mae','trainingLoss','unusedHidden']} for r in mismatch if r['meanRegret']<=.01][:8],
  'largestFaceGaps':facecases[:8],'exampleSelection':'post-hoc explanatory witnesses: relativeMAE descending among text_l1 primary regret<=1%; face gap descending; never remove these examples from aggregate'}
 s.save(OUT/'analysis.json',result);s.save(OUT/'all-results.json',rows)
 fields=['id','family','seed','K','noise','method','status','meanRegret','mae','relativeMAE','bestMean','worstMean','unusedHidden','fitSeconds','wallSeconds','cpuSeconds','error']
 with (OUT/'all-results.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
 s.save(OUT/'verification.json',{'status':'passed','assertions':checks,'scope':'input/code hashes, complete schedule representation including failures, feasibility, noise caps, score arithmetic and actual face witnesses; no independent re-solve here'})
 print(json.dumps({'rows':len(rows),'statuses':result['statusCounts'],'checks':checks,'resources':resources}))
 for r in summary:
  if r['K']==10 and r['noise']==.1:print(json.dumps({k:r[k] for k in ['family','method','completeRuns','failedRuns','fullCohortMean','successfulOnlyMean','meanRelativeMAEOnSuccessful','worstFullMean']}))
if __name__=='__main__':summarize()
