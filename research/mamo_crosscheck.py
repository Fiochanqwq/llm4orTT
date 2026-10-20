"""Independent modeling implementation check: app Pyomo versus research highspy.
Both use HiGHS, so this checks formulations/implementations, not solver diversity.
"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from mamo_experiment import OUT,ROOT,read,save,fit
sys.path.insert(0,str(ROOT/'solver'))
import inverse


def main():
    problems=read(OUT/'public/problems.json')
    records=[]
    for p in problems[:2]:
        for lam in [0,.01]:
            samples=p['histories']['0.1'][:5]
            bank=p['bank'];allowed=[0,1,2]
            expected=fit(samples,bank,allowed,lam)
            scale=expected['scale']
            data={'schema':'contextual-inverse.v1','lambda':lam*scale/20,'maxIterations':80,
                  'tolerance':1e-6,'seconds':10,'hypotheses':[
                      {'id':f['id'],'lower':0,'upper':20 if j in allowed else 0} for j,f in enumerate(bank)],'samples':[]}
            for s in samples:
                n=len(s['base']);names=['x'+str(i) for i in range(n)]
                fs={}
                for f in bank:
                    if f['kind']=='cost':fs[f['id']]={'kind':'linear','terms':{names[f['variable']]:1}}
                    else:
                        i=f['nutrient'];fs[f['id']]={'kind':'soft','terms':{names[j]:v/s['b'][i] for j,v in enumerate(s['A'][i])},'sense':'<=','rhs':1.2}
                data['samples'].append({'id':s['id'],'model':{'variables':[{'name':name,'type':'integer','lower':0,'upper':None} for name in names],
                    'objective':dict(zip(names,s['base'])),'constraints':[{'terms':dict(zip(names,a)),'sense':'>=','rhs':b} for a,b in zip(s['A'],s['b'])]},
                    'decision':dict(zip(names,s['decision'])),'features':fs})
            canonical=[inverse.canonical(s,data['hypotheses']) for s in inverse.validate(data)['samples']]
            actual=inverse.fit(data,canonical)
            gap=abs(actual['objective']/scale-expected['objective'])
            if actual['status']!='optimal' or gap>2e-6:raise ValueError('Independent formulation disagreement')
            records.append({'id':p['id'],'lambda':lam,'K':5,'noise':.1,'absoluteObjectiveDifference':gap,
                            'pyomoStatus':actual['status'],'researchStatus':expected['status']})
    save(OUT/'formulation-crosscheck.json',{'status':'passed','checks':records,'note':'Two independently coded formulations; common HiGHS solver. Weight vectors may differ under nonidentifiability.'})
    print('Four independent formulation checks passed',flush=True)

if __name__=='__main__':main()
