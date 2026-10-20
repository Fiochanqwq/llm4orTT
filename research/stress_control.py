"""Additional information-parity constant control; main schedule stays unchanged."""
import json,sys,time,statistics as st
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import stress_public as s
import numpy as np
def main():
 s.freeze()
 start=time.perf_counter();cpu=time.process_time();rows=[]
 spec=s.ROOT/'research/stress_control_addendum.json'
 s.save(s.OUT/'control-addendum.json',s.read(spec))
 for m in s.read(s.OUT/'models.json'):
  for seed in s.read(s.CFG)['seeds']:
   rec=s.read(s.OUT/f'inputs/{m["id"]}-s{seed}.json');derived=s.read(s.OUT/f'derived/{m["id"]}-s{seed}.json')
   r={'id':m['id'],'family':m['family'],'seed':seed,'method':'unit_selected3','theta':[1,1,1,0,0],'testDetails':[]}
   for d in derived[10:]:
    try:
     if d['status']!='optimal':raise ValueError('original test oracle unavailable')
     x,v,status=s.solve(m,np.array(d['base'])+np.array(rec['F'])@np.array(r['theta']))
     if status!='optimal':raise ValueError(status)
     cost=float((np.array(d['base'])+np.array(rec['F'])@np.array(rec['truth']))@x)
     r['testDetails'].append({'context':d['context'],'status':'complete','decision':x.tolist(),'regret':max(0,cost-d['optimum'])/max(1,abs(d['optimum']))})
    except Exception as e:r['testDetails'].append({'context':d['context'],'status':'failed','error':str(e)})
   r['status']='complete' if all(d['status']=='complete' for d in r['testDetails']) else 'incomplete'
   r['meanRegret']=st.mean(d['regret'] for d in r['testDetails']) if r['status']=='complete' else None
   rows.append(r)
 primary=s.read(s.OUT/'all-results.json');summary=[]
 for f in s.read(s.CFG)['datasets']:
  rr=[r for r in rows if r['family']==f];valid=[r for r in rr if r['status']=='complete'];delta=[];ids=[];omitted=[]
  for name in sorted({r['id'] for r in rr}):
   aa=[r for r in primary if r['id']==name and r['K']==10 and r['noise']==.1 and r['method']=='text_l1' and r['status']=='complete']
   bb=[r for r in valid if r['id']==name]
   if len(aa)==len(bb)==3:delta.append(st.mean(r['meanRegret'] for r in aa)-st.mean(r['meanRegret'] for r in bb));ids.append(name)
   else:omitted.append(name)
  rng=np.random.default_rng(20261022)
  ci=np.quantile(np.mean(rng.choice(delta,(5000,len(delta))),axis=1),[.025,.975]).tolist() if delta else None
  summary.append({'family':f,'scheduled':len(rr),'complete':len(valid),'fullCohortMean':st.mean(r['meanRegret'] for r in valid) if len(valid)==len(rr) else None,'successfulOnlyMean':st.mean(r['meanRegret'] for r in valid) if valid else None,'pairedSourceIds':ids,'omittedIds':omitted,'textMinusConstantMean':st.mean(delta) if delta else None,'ci95':ci})
 s.save(s.OUT/'additional-control.json',{'specificationSha256':s.sha(spec),'rows':rows,'summary':summary,'wallSeconds':time.perf_counter()-start,'cpuSeconds':time.process_time()-cpu,'resources':dict(s.STATS),'paidApiCalls':0})
 print(json.dumps({'summary':summary,'seconds':time.perf_counter()-start}))
if __name__=='__main__':main()
