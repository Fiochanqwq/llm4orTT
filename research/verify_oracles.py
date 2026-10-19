"""Independently certify all enumeration Oracles using the app's MILP solver."""
import math
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from pilot import OUT, BANK, read, save, history, fit, costs
from inverse import canonical, forward, recover


def as_app(samples):
    hypotheses=[{'id':h['id'],'lower':0,'upper':10} for h in BANK]
    data={'schema':'contextual-inverse.v1','hypotheses':hypotheses,'lambda':.01,'maxIterations':100,'samples':[]}
    for s in samples:
        names=[f'x{i}' for i in range(len(s['plans']))]
        features={}
        for h in BANK:
            f={'kind':'linear','terms':{n:p[h['id']] for n,p in zip(names,s['plans'])}}
            if h['kind']=='hinge':f.update(kind='soft',sense='<=',rhs=h['threshold'])
            features[h['id']]=f
        data['samples'].append({'id':s['id'],'model':{'sense':'minimize',
            'variables':[{'name':n,'type':'binary','lower':0,'upper':1} for n in names],
            'objective':{n:p['wage'] for n,p in zip(names,s['plans'])},
            'constraints':[{'terms':dict.fromkeys(names,1),'sense':'=','rhs':1}]},
            'features':features,'decision':{n:int(i==s['chosen']) for i,n in enumerate(names)}})
    return data


def run():
    records=[]; inverse_checks=[]
    for base in read(OUT/'oracle/private-bases.json'):
        data=as_app(base['contexts'])
        for original,s in zip(base['contexts'],data['samples']):
            x, optimum=forward(canonical(s,data['hypotheses']),base['truth'])
            reference=min(costs(original,BANK,base['truth']))
            assert math.isclose(optimum,reference,abs_tol=1e-6)
            assert abs(sum(x[f'x{i}'] for i in range(6))-1)<1e-6
            records.append({'base':base['id'],'context':s['id'],'enumerationObjective':reference,
                            'highsObjective':optimum,'difference':abs(optimum-reference),'status':'optimal'})
        for noise in (0,.15):
            samples=history(base,20,noise)
            direct=fit(samples,BANK,.01)
            cut=recover(as_app(samples))
            assert cut['status']=='optimal'
            assert abs(direct['objective']-cut['objective'])<1e-5
            inverse_checks.append({'base':base['id'],'noise':noise,'enumeratedObjective':direct['objective'],
                                   'cutObjective':cut['objective'],'cutGap':cut['trace'][-1]['gap'],
                                   'iterations':len(cut['trace'])})
        print(f"Certified {base['id']}: 50 forward MILPs + 2 inverse cross-checks",flush=True)
    save(OUT/'oracle-certification.json',{'status':'passed','forwardCount':len(records),
          'inverseCrossCheckCount':len(inverse_checks),'forward':records,'inverse':inverse_checks})


if __name__=='__main__':run()
