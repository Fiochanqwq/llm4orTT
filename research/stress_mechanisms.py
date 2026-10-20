"""Post-outcome mechanism checks. Never change main methods, histories or scores."""
import sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import stress_public as s
import numpy as np
def empirical(m,derived,F,theta,cap):
 ss=[{'base':x['base'],'decision':x['decisions'][cap]} for x in derived[:10]]
 scale=max(1,np.mean([abs(np.dot(x['base'],x['decision'])) for x in ss]));loss=[]
 for d in ss:
  c=np.array(d['base'])+F@theta;x,val,status=s.solve(m,c)
  if status!='optimal':raise ValueError(status)
  loss.append(max(0,float(c@np.array(d['decision']))-val))
 return float(np.mean(loss)/scale)
def main():
 start=time.perf_counter();cpu=time.process_time();results=[]
 # AFIRO was identified in the first completed seed as zero regret / 100% price error.
 # Test the same prespecified source across all three seeds, both already-frozen noise levels.
 for seed in s.read(s.CFG)['seeds']:
  rec=s.read(s.OUT/f'inputs/afiro-s{seed}.json');derived=s.read(s.OUT/f'derived/afiro-s{seed}.json');job=s.read(s.OUT/f'jobs/afiro-s{seed}.json');F=np.array(rec['F']);m=rec['model']
  for cap in ['0','0.1']:
   r={'id':'afiro','seed':seed,'noise':float(cap),'truth':rec['truth'],'selection':'post-hoc AFIRO mechanism follow-up, all3 frozen seeds retained'}
   try:
    s.DEADLINE=time.perf_counter()+90
    ss=[{'base':d['base'],'decision':d['decisions'][cap]} for d in derived[:10]]
    io=s.Inverse(m,ss,F,[0,1,2]);theta,loss=io.fit();profile=s.Inverse(m,ss,F,[0,1,2]).profiles()
    change=-F@np.array(rec['truth'])
    lo=s.solve(m,change);hi=s.solve(m,change,maximize=True)
    geometry={'minimumZeroMinusTruthCost':lo[1],'maximumZeroMinusTruthCost':hi[1],'statuses':[lo[2],hi[2]],
      'testOracleActivationCounts':[sum(abs(d['oracle'][i])>1e-8 for d in derived[10:]) for i in rec['indices'][:2]],
      'trainingObservedActivationCounts':[sum(abs(d['decisions'][cap][i])>1e-8 for d in derived[:10]) for i in rec['indices'][:2]],
      'interpretation':'A nonconstant difference rules out a global additive-cost invariance; it does not imply these ten observed choices identify the hidden prices.'}
    r.update(status='complete',minimumLoss=loss,truthLoss=empirical(m,derived,F,np.array(rec['truth']),cap),zeroLoss=empirical(m,derived,F,np.zeros(5),cap),profile=profile,objectiveDifferenceOverFeasibleSet=geometry,
     methodResults=[{k:x.get(k) for k in ['method','theta','meanRegret','relativeMAE','status','trainingLoss']} for x in job['rows'] if x['K']==10 and x['noise']==float(cap)])
   except Exception as e:r.update(status='failed',error=str(e))
   finally:s.DEADLINE=float('inf')
   results.append(r)
 # Historical counterexample is explicitly kept separate from new benchmark evidence.
 old=s.ROOT/'outputs/inverse/multifamily-20261020-v1/optimal-face-witness.json'
 historical=s.read(old) if old.exists() else {'status':'historical artifact unavailable'}
 s.save(s.OUT/'mechanisms.json',{'postHoc':True,'afiroChecks':results,'historicalMamoWitness':historical,
   'historicalSource':'outputs/inverse/multifamily-20261020-v1/optimal-face-witness.json; not pooled with new datasets',
   'wallSeconds':time.perf_counter()-start,'cpuSeconds':time.process_time()-cpu,
   'interpretationLimits':'Profiles are near-minimum empirical-loss sets, not confidence intervals or all parameters compatible with bounded noise. A narrow set excluding truth can indicate loss mismatch under noise, not reliable identification.'})
 print(s.json.dumps({'mechanismChecks':len(results),'failed':sum(r['status']!='complete' for r in results),'seconds':time.perf_counter()-start}))
if __name__=='__main__':main()
