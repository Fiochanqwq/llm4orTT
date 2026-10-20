"""Box-valid sparse cuts avoid a HiGHS high-level warning being raised as an error.

This is a separate post-hoc engineering repair. Frozen batch scores stay untouched.
"""
import sys,time,statistics as st
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
from llm_grounding import solver,certify,forward,phi,read,save,OUT,fit,score

def sparse_box_lower_cut(coefficients,upper=20.,tolerance=1e-9):
    """Drop tiny a_j theta_j while adding min_{0<=theta<=U} of dropped terms."""
    retained=[(j,float(v)) for j,v in enumerate(coefficients) if abs(v)>tolerance]
    correction=upper*sum(min(float(v),0.) for v in coefficients if abs(v)<=tolerance)
    return retained,correction

def fit_stable(m,samples,features,lam=.01):
    if not features:return fit(m,samples,features,lam)
    start=time.perf_counter();scale=max(1,st.mean(abs(np.dot(s['base'],s['decision'])) for s in samples))
    h=solver();n=len(features);t=h.addVariables(n,lb=0,ub=20,obj=[lam/20]*n)
    e=h.addVariables(len(samples),lb=0,obj=[1/len(samples)]*len(samples));removed=0
    for iteration in range(60):
        if time.perf_counter()-start>60:raise TimeoutError('inverse60seconds')
        certify(h);theta=np.array([h.val(t[j]) for j in range(n)]);cuts=0;losses=[]
        for k,s in enumerate(samples):
            x,_=forward(m,s['base'],features,theta)
            a=(phi(m,features,s['decision'])-phi(m,features,x))/scale
            b=float(np.dot(s['base'],np.array(s['decision'])-x))/scale
            loss=max(0,b+a@theta);losses.append(loss)
            if loss>h.val(e[k])+1e-6:
                kept,correction=sparse_box_lower_cut(a);removed+=sum(int(0<abs(v)<=1e-9) for v in a)
                h.addConstr(e[k]>=b+correction+h.qsum(v*t[j] for j,v in kept));cuts+=1
        if not cuts:return {'theta':theta.tolist(),'status':'optimal','loss':st.mean(losses),'iterations':iteration+1,'removedTinyCoefficients':removed,'seconds':time.perf_counter()-start}
    raise TimeoutError('inverse60iterations')

def recheck():
    rows=[]
    for folder in ['jobs','feedback-results','clarified-results']:
        for p in sorted((OUT/folder).glob('*.json')):
            rows.extend(r for r in read(p)['rows'] if r.get('error')=='Error adding constraint to the model.')
    result=[]
    for r in rows:
        item=read(OUT/'oracle'/f'{r["id"]}.json');ss=read(OUT/'contexts'/f'{r["id"]}-s{r["seed"]}.json')
        from llm_grounding import llm_record,compile_features
        mode={'ds_feedback':'feedback','ds_clarified_io':'clarified','no_logs_io':'no_logs'}.get(r['method'],'proposal')
        rid=f'{r["id"]}-s{r["seed"]}-n{r["noise"]}' if mode=='feedback' else r['id']
        fs=compile_features(item['public'],llm_record(mode,rid));samples=[{**s,'decision':s['decisions'][str(r['noise'])]} for s in ss[:r['K']]]
        row={k:r[k] for k in ['id','seed','noise','K','method']};row['originalFailure']=r['error']
        try:
            fitted=fit_stable(item['model'],samples,fs,lam=0 if r['method']=='ds_no_l1' else .01)
            row.update(repairStatus='complete',fit=fitted,score=score(item,ss[10:],fs,fitted['theta']))
        except Exception as e:row.update(repairStatus='failed',error=str(e))
        result.append(row)
    save(OUT/'solver-repair-checks.json',{'postHoc':True,'originalRowsReplaced':False,
         'rootCause':'HiGHS high-level addConstr treats a non-kOk addRow warning as an exception. A reproduced cut contained a coefficient around1e-16.',
         'repair':'Drop |a_j|<=1e-9 in normalized inverse cuts and add20*sum(min(a_j,0)) for dropped terms. This is a valid lower cut on the declared box; original full loss separation still certifies tolerance.',
         'results':result})
    print('engineering rechecks',len(result),[(x['id'],x['method'],x['repairStatus']) for x in result],flush=True)
if __name__=='__main__':recheck()
