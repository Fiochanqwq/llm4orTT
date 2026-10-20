"""Control the solver implementation in the oracle-sign diagnostic."""
import sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from llm_grounding import OUT,read,save,compile_features,score
from llm_grounding_stable_fit import fit_stable

def main():
    dest=OUT/'mechanism-control.json'
    if dest.exists():raise RuntimeError('Completed diagnostic must not be overwritten')
    started=time.perf_counter();cpu=time.process_time();result=[]
    for intervention in read(OUT/'mechanism-diagnostics.json')['signInterventions']:
        sid=intervention['id'];seed=intervention['seed'];noise=intervention['noise']
        item=read(OUT/'oracle'/f'{sid}.json');ss=read(OUT/'contexts'/f'{sid}-s{seed}.json')
        features=compile_features(item['public'],read(OUT/'llm/clarified'/f'{sid}.json')['value'])
        samples=[{**s,'decision':s['decisions'][str(noise)]} for s in ss[:10]]
        row={'id':sid,'seed':seed,'noise':noise,'K':10,'frozenMeanRegret':intervention['originalMeanRegret'],
             'signCorrectedMeanRegret':intervention.get('score',{}).get('meanRegret')}
        try:
            fitted=fit_stable(item['model'],samples,features)
            row.update(status='complete',originalFeaturesStableFit=fitted,originalFeaturesStableScore=score(item,ss[10:],features,fitted['theta']))
        except Exception as e:row.update(status='failed',error=str(e))
        result.append(row)
    save(dest,{'scope':'Original wrong-sign and oracle-corrected-sign candidates are now compared using the SAME stable cut implementation; main batch unchanged.',
               'postHoc':True,'results':result,'cpuSeconds':time.process_time()-cpu,'wallSeconds':time.perf_counter()-started})
    print('same-solver mechanism controls',len(result))
if __name__=='__main__':main()
