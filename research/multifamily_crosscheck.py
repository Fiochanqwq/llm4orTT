"""Independent tour formulation and explicit witnesses; raw experiment immutable."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import numpy as np
import multifamily as m

def directed_mtz(model):
    cities=sorted(set(v for name in model['names'] for v in name.split('--')))
    n=len(cities);cost={tuple(name.split('--')):c for name,c in zip(model['names'],model['c'])}
    h=m.solver();arcs=[(i,j) for i in range(n) for j in range(n) if i!=j]
    x={a:h.addVariable(lb=0,ub=1,type=m.hs.HighsVarType.kInteger,obj=cost[tuple(sorted((cities[a[0]],cities[a[1]])))]) for a in arcs}
    for i in range(n):
        h.addConstr(h.qsum(x[i,j] for j in range(n) if j!=i)==1)
        h.addConstr(h.qsum(x[j,i] for j in range(n) if j!=i)==1)
    u={i:h.addVariable(lb=1,ub=n-1) for i in range(1,n)}
    for i in range(1,n):
        for j in range(1,n):
            if i!=j:h.addConstr(u[i]-u[j]+n*x[i,j]<=n-1)
    m.certified(h)
    return h.getObjectiveValue()

def main():
    rows=[m.json.loads(line) for line in (m.ROOT/'datasets/mamo/mamo_complex_lp.jsonl').read_text(encoding='utf8').splitlines()]
    checks=[];unparsed=[]
    for row in rows:
        if not 60<=row['id']<=99:continue
        try:model=m.parse_tour(row)
        except ValueError as e:
            unparsed.append({'id':row['id'],'reason':str(e)});continue
        enumeration=m.solve(model,model['c'])[1];other=directed_mtz(model)
        assert abs(enumeration-other)<1e-6,(row['id'],enumeration,other)
        checks.append({'id':row['id'],'enumeration':enumeration,'directedMTZ':other,'publicAnswer':float(row['Answer']),'matchesPublic':abs(other-float(row['Answer']))<1e-6})
    result={'status':'passed','checks':checks,'unparsed':unparsed,'limitation':'Independent optimization formulation; shared text parser and HiGHS solver. Does not independently certify every text interpretation.'}
    # Preserve the original ad-hoc crosscheck alongside this reproducible rerun.
    m.save(m.OUT/'source-crosscheck-reproduced.json',result)
    record=m.read(m.OUT/'contexts/p44-s71.json')
    row=next(r for r in m.read(m.OUT/'rows/p44-s71.json')['rows'] if r['K']==20 and r['noise']==.1 and r['method']=='text_sparse_io')
    s=record['contexts'][24];F=np.array(s['F']);c=np.array(s['base'])+F@row['theta'];truec=np.array(s['base'])+F@record['truth']
    default,v,_=m.solve(s,c);worst,hv,_=m.solve(s,truec,cap_cost=c,cap=v,maximize=True)
    # Re-solve exact cap, with tighter solver tolerances, to rule out a tolerance-only explanation.
    h=m.solver();h.setOptionValue('primal_feasibility_tolerance',1e-9)
    x=h.addVariables(len(c),lb=0,obj=(-truec).tolist())
    for a,b in zip(s['A'],s['b']):h.addConstr(h.qsum(float(vv)*x[j] for j,vv in enumerate(a) if vv)>=b)
    h.addConstr(h.qsum(float(vv)*x[j] for j,vv in enumerate(c) if vv)<=v)
    m.certified(h);exact=np.array([h.val(x[j]) for j in range(len(c))])
    assert abs(float(c@exact)-v)<1e-5
    witness={'id':44,'seed':71,'context':s['context'],'method':'text_sparse_io','theta':row['theta'],'truth':record['truth'],'names':s['names'],'indices':record['indices'],
        'default':default.tolist(),'worstWithinTolerance':worst.tolist(),'worstExactCap':exact.tolist(),'predictedDefault':v,'predictedWorstExact':float(c@exact),
        'oracleCost':s['oracleObjective'],'trueDefault':float(truec@default),'trueWorstExact':float(truec@exact),
        'worstRegretExact':max(0,float(truec@exact)-s['oracleObjective'])/max(1,abs(s['oracleObjective'])),
        'minimumBalanceSlack':float(min(np.array(s['A'])@exact-s['b'])),'note':'Additional diagnostic after outcomes; does not alter primary metric, method or test contexts.'}
    m.save(m.OUT/'optimal-face-witness.json',witness)
    print(m.json.dumps({'crosschecked':len(checks),'publicDisagreements':sum(not c['matchesPublic'] for c in checks),'witnessWorstPercent':100*witness['worstRegretExact']}))

if __name__=='__main__':main()
