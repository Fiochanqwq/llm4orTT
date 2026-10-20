"""Offline evidence verification, standard library only; no API or solver calls.

Run: python verify_bundle.py [extracted_bundle_directory]
"""
import hashlib,json,math,sys
from collections import Counter
from pathlib import Path

def main():
    root=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parent
    read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
    checks=0
    def close(a,b):
        nonlocal checks
        assert math.isfinite(a) and math.isfinite(b)
        assert abs(a-b)<=2e-5*max(1,abs(a),abs(b)),(a,b)
        checks+=1
    def objective(m,base,features,theta,x):
        total=sum(a*b for a,b in zip(base,x))
        for f,t in zip(features,theta):
            v=f['sign']*x[m['names'].index(f['variable'])] if f['kind']=='linear' else max(0,sum(a*b for a,b in zip(m['monitors'][f['monitor']],x))-f['threshold'])
            total+=t*v
        return total
    manifest=read(root/'CHECKSUMS.json')
    for name,digest in manifest['files'].items():
        p=(root/name).resolve()
        assert p.is_relative_to(root),'unsafe manifest path'
        assert hashlib.sha256(p.read_bytes()).hexdigest()==digest,'file hash changed: '+name
        checks+=1
    rows=read(root/'all-results.json');analysis=read(root/'analysis.json')
    assert len(rows)==analysis['scheduled']==2912
    assert dict(Counter(r['status'] for r in rows))==analysis['statusCounts']
    assert len({(r['id'],r['seed'],r['K'],r['noise'],r['method']) for r in rows})==len(rows)
    original={m['id']:read(root/'oracle'/f'{m["id"]}.json') for m in read(root/'models.json')}
    contexts={(sid,seed):read(root/'contexts'/f'{sid}-s{seed}.json') for sid in original for seed in [19,43]}
    for (sid,seed),ss in contexts.items():
        item=original[sid];m=item['model']
        assert len({s['context'] for s in ss})==20
        for s in ss:
            assert s['status']=='complete'
            close(objective(m,s['base'],item['trueFeatures'],item['truth'],s['oracleDecision']),s['oracleObjective'])
            for cap,x in s.get('decisions',{}).items():
                cost=objective(m,s['base'],item['trueFeatures'],item['truth'],x)
                assert cost-s['oracleObjective']<=float(cap)*max(1,abs(s['oracleObjective']))+1e-4
                checks+=1
    for r in rows:
        if r['status']!='complete':continue
        item=original[r['id']];m=item['model']
        cs={s['context']:s for s in contexts[r['id'],r['seed']][10:]}
        assert len(r['tests'])==10 and len({t['context'] for t in r['tests']})==10
        for t in r['tests']:
            assert t['status']=='complete';s=cs[t['context']];x=t['decision']
            assert len(x)==len(m['names'])
            close(objective(m,s['base'],r['features'],r['fit']['theta'],x),t['predictedCost'])
            close(objective(m,s['base'],item['trueFeatures'],item['truth'],x),t['trueCost'])
            close(s['oracleObjective'],t['oracleCost'])
            close(max(0,t['trueCost']-t['oracleCost'])/max(1,abs(t['oracleCost'])),t['regret'])
            if m['kind']=='tour':
                assert all(abs(v-round(v))<1e-5 and -.00001<=v<=1.00001 for v in x)
                selected=[tuple(edge) for edge,v in zip(m['edges'],x) if v>.5]
                vertices={i for i,j in m['edges']};assert len(selected)==len(vertices)
                assert set(i for i,j in selected)==vertices and set(j for i,j in selected)==vertices
                nextcity=dict(selected);visited=set();v=0
                for _ in vertices:visited.add(v);v=nextcity[v]
                assert v==0 and visited==vertices
            else:
                assert all(lo-1e-4<=v<=hi+1e-4 for v,lo,hi in zip(x,m['lb'],m['ub']))
                for coeff,lo,hi in zip(m['A'],m['rl'],m['ru']):
                    v=sum(a*b for a,b in zip(coeff,x));assert lo-1e-4<=v<=hi+1e-4
                if m['integer']:assert all(abs(v-round(v))<=1e-5 for v in x)
            checks+=1
        close(sum(t['regret'] for t in r['tests'])/10,r['meanRegret'])
    raw=[read(p) for p in (root/'llm/raw').glob('*.json')]
    assert len(raw)==397
    assert len({r['sequence'] for r in raw})==len(raw)
    for r in raw:
        assert hashlib.sha256(r['prompt'].encode()).hexdigest()==r['promptSha256']
        assert r['endpointOrigin']=='https://api.deepseek.com'
        checks+=1
    for name,field in [('input','prompt_tokens'),('output','completion_tokens'),('cacheHit','prompt_cache_hit_tokens')]:
        assert sum((r.get('usage') or {}).get(field,0) for r in raw)==analysis['api']['tokens'][name]
    print(json.dumps({'status':'passed','fileHashes':len(manifest['files']),'arithmeticAndEvidenceChecks':checks,
        'rows':len(rows),'apiRecords':len(raw),'paidAPICallsDuringVerification':0,
        'scope':'Hashes, prompt integrity, score arithmetic, feasibility, historical noise caps. Not an independent proof of every oracle optimum or semantic correctness.'}))
if __name__=='__main__':main()
