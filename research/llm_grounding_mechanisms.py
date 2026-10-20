"""Post-hoc mechanisms, never merged into frozen benchmark scores.

Oracle sign is deliberately supplied ONLY in a labeled diagnostic intervention.
Feature inactivity is descriptive and is not a proof of unidentifiability.
"""
import sys, time, copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from llm_grounding import OUT,read,save,phi,compile_features,score
from llm_grounding_stable_fit import fit_stable

def main():
    dest=OUT/'mechanism-diagnostics.json'
    if dest.exists():raise RuntimeError('Do not overwrite completed diagnostics')
    started=time.perf_counter();cpu=time.process_time()
    config=read(OUT/'protocol.json');records=[];interventions=[]
    original=read(OUT/'all-results.json')
    for meta in read(OUT/'models.json'):
        item=read(OUT/'oracle'/f'{meta["id"]}.json');m=item['model']
        fs=compile_features(item['public'],read(OUT/'llm/clarified'/f'{meta["id"]}.json')['value'])
        truth={f['variable']:f['sign'] for f in item['trueFeatures'] if f['kind']=='linear'}
        corrected=copy.deepcopy(fs)
        altered=[]
        for f in corrected:
            if f['kind']=='linear' and f['variable'] in truth and f['sign']!=truth[f['variable']]:
                altered.append(f['variable']);f['sign']=truth[f['variable']]
        for seed in config['seeds']:
            ss=read(OUT/'contexts'/f'{meta["id"]}-s{seed}.json')
            record={'id':meta['id'],'collection':meta['collection'],'seed':seed,'trueFeatures':item['trueFeatures']}
            for name,samples,xkey in [('trainOracle',ss[:10],'oracleDecision'),('testOracle',ss[10:],'oracleDecision')]:
                record[name+'Activation']=[sum(int(abs(phi(m,[f],s[xkey])[0])>1e-6) for s in samples) for f in item['trueFeatures']]
            record['trainNoisyActivation']=[sum(int(abs(phi(m,[f],s['decisions']['0.1'])[0])>1e-6) for s in ss[:10]) for f in item['trueFeatures']]
            records.append(record)
            if not altered:continue
            for noise in config['noiseCaps']:
                row={'id':meta['id'],'seed':seed,'noise':noise,'K':10,'changedVariables':altered,
                     'informationAdded':'oracle sign of the missing original unit cost; not LLM performance'}
                before=next(r for r in original if r['id']==meta['id'] and r['seed']==seed and r['noise']==noise and r['K']==10 and r['method']=='ds_clarified_io')
                row['originalStatus']=before['status'];row['originalMeanRegret']=before.get('meanRegret')
                samples=[{**s,'decision':s['decisions'][str(noise)]} for s in ss[:10]]
                try:
                    fitted=fit_stable(m,samples,corrected)
                    row.update(status='complete',features=corrected,fit=fitted,score=score(item,ss[10:],corrected,fitted['theta']))
                except Exception as e:row.update(status='failed',error=str(e))
                interventions.append(row)
    save(dest,{'postHoc':True,'originalResultsReplaced':False,
               'selection':'All clarified proposals whose missing-cost linear sign disagrees with oracle, both seeds and noise caps. No test-score selection.',
               'intervention':'Only sign is corrected; same observations, split, theta box and lambda. Stable sparse cut implementation used for diagnostic fits.',
               'inactivityCaution':'Zero activation on observed decisions does not imply zero activation on alternatives or formal unidentifiability.',
               'activation':records,'signInterventions':interventions,
               'wallSeconds':time.perf_counter()-started,'cpuSeconds':time.process_time()-cpu})
    print('mechanism diagnostic completed:',len(records),'activation records;',len(interventions),'sign interventions')
if __name__=='__main__':main()
