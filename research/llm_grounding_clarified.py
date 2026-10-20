"""Evaluate a single clarified-prompt proposal per source, separate from original outcomes."""
import sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from llm_grounding import read,save,OUT,CFG,verify,compile_features,llm_record,fit,score,STATS
def run():
    verify();cfg=read(CFG)
    for meta in read(OUT/'models.json'):
        sid=meta['id'];item=read(OUT/'oracle'/f'{sid}.json')
        for seed in cfg['seeds']:
            dest=OUT/'clarified-results'/f'{sid}-s{seed}.json'
            if dest.exists():continue
            start=time.perf_counter();cpu=time.process_time();stats_before=dict(STATS);rows=[]
            ss=read(OUT/'contexts'/f'{sid}-s{seed}.json')
            for cap,mode in [(c,m) for c in cfg['noiseCaps'] for m in ['clarified','clarified_no_logs','clarified_shuffled']]:
                method='ds_clarified_io' if mode=='clarified' else mode+'_io'
                r={'id':sid,'collection':meta['collection'],'seed':seed,'K':10,'noise':cap,'method':method,'exploratoryPromptAmendment':True};tic=time.perf_counter()
                try:
                    features=compile_features(item['public'],llm_record(mode,sid))
                    samples=[{**s,'decision':s.get('decisions',{}).get(str(cap))} for s in ss[:10]]
                    if any(s['decision'] is None for s in samples):raise ValueError('missing training history')
                    fitted=fit(item['model'],samples,features,lam=.01)
                    r.update(features=features,fit=fitted,**score(item,ss[10:],features,fitted['theta']))
                except Exception as e:r.update(status='failed',error=str(e))
                r['seconds']=time.perf_counter()-tic;rows.append(r)
            save(dest,{'id':sid,'seed':seed,'rows':rows,'wallSeconds':time.perf_counter()-start,'cpuSeconds':time.process_time()-cpu,'stats':{k:v-stats_before.get(k,0) for k,v in STATS.items()}})
            print(sid,seed,','.join(r['status'] for r in rows),flush=True)
if __name__=='__main__':run()
