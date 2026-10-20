"""Real API hypotheses + local inverse LP/MILP. Source text is never executable."""
from __future__ import annotations
import argparse, hashlib, itertools, json, math, os, random, re, statistics as st, sys, time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import highspy as hs
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
from mamo_experiment import parse_diet, original_solve

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/inverse/deepseek-grounding-20261020-v1'
CFG=ROOT/'research/llm_grounding_protocol.json'
STATS=Counter()
def read(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def save(p,d):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def key(s): return int(hashlib.sha256(s.encode()).hexdigest()[:12],16)
def solver():
    h=hs.Highs()
    for k,v in {'output_flag':False,'threads':1,'time_limit':5.,'mip_rel_gap':0.,'mip_abs_gap':0.,'random_seed':17}.items():h.setOptionValue(k,v)
    return h
def certify(h):
    h.run();STATS['solverRuns']+=1;STATS['solverSeconds']+=h.getRunTime()
    if h.getModelStatus()!=hs.HighsModelStatus.kOptimal:raise RuntimeError('uncertified '+str(h.getModelStatus()))
def fkey(f):
    if f['kind']=='linear':return f'linear:{f["variable"]}:{f["sign"]}'
    return f'excess:{f["monitor"]}:{float(f["threshold"]):.6f}'
def compile_features(public,value):
    fs=value.get('features')
    if not isinstance(fs,list) or len(fs)>8:raise ValueError('features must be array with at most8 expressions')
    result=[]
    for f in fs:
        if not isinstance(f,dict):raise ValueError('feature is not object')
        if f.get('kind')=='linear':
            if f.get('variable') not in public['variables'] or f.get('sign') not in [-1,1]:raise ValueError('invalid linear expression')
            v={'kind':'linear','variable':f['variable'],'sign':int(f['sign'])}
        elif f.get('kind')=='excess':
            t=f.get('threshold')
            if f.get('monitor') not in public['monitors'] or isinstance(t,bool) or not isinstance(t,(int,float)) or not math.isfinite(t) or not 0<=t<=3:raise ValueError('invalid excess expression')
            v={'kind':'excess','monitor':f['monitor'],'threshold':float(t)}
        else:raise ValueError('unsupported expression kind')
        if fkey(v) in [fkey(x) for x in result]:raise ValueError('duplicate expression')
        result.append(v)
    return result
def phi(m,features,x):
    ans=[]
    for f in features:
        ans.append(f['sign']*x[m['names'].index(f['variable'])] if f['kind']=='linear'
                   else max(0,float(np.dot(m['monitors'][f['monitor']],x))-f['threshold']))
    return np.array(ans)
def value(m,base,features,theta,x):return float(np.dot(base,x)+np.dot(theta,phi(m,features,x)))
def forward(m,base,features,theta,aux=None,cap=None,capfeatures=None,captheta=None):
    STATS['forwardCalls']+=1
    if m['kind']=='tour':
        X=np.asarray(m['choices']);cost=X@base
        def column(f):
            return f['sign']*X[:,m['names'].index(f['variable'])] if f['kind']=='linear' else np.maximum(0,X@np.asarray(m['monitors'][f['monitor']])-f['threshold'])
        for f,t in zip(features,theta):
            if t:cost+=t*column(f)
        valid=np.ones(len(X),bool)
        if cap is not None:
            c=X@base
            for f,t in zip(capfeatures,captheta):
                c+=t*column(f)
            valid=c<=cap+1e-7
        indices=np.flatnonzero(valid)
        if not len(indices):raise ValueError('no feasible tour under cap')
        vals=cost if aux is None else X@aux
        i=indices[np.argmin(vals[indices])]
        return X[i].astype(float),float(cost[i])
    h=solver();n=len(base)
    x=h.addVariables(n,lb=m['lb'],ub=m['ub'],type=hs.HighsVarType.kInteger if m['integer'] else hs.HighsVarType.kContinuous)
    for a,lo,hi in zip(m['A'],m['rl'],m['ru']):
        expr=h.qsum(float(v)*x[j] for j,v in enumerate(a) if v)
        if lo>-1e29:h.addConstr(expr>=lo)
        if hi<1e29:h.addConstr(expr<=hi)
    def expr(fs,tt):
        terms=[h.qsum(float(v)*x[j] for j,v in enumerate(base) if v)]
        for f,t in zip(fs,tt):
            if abs(t)<1e-14:continue
            if f['kind']=='linear':terms.append(float(t*f['sign'])*x[m['names'].index(f['variable'])])
            else:
                if t<0:raise ValueError('negative convex penalty')
                z=h.addVariable(lb=0);a=m['monitors'][f['monitor']]
                h.addConstr(z>=h.qsum(float(v)*x[j] for j,v in enumerate(a) if v)-f['threshold'])
                terms.append(float(t)*z)
        return h.qsum(terms)
    if cap is not None:h.addConstr(expr(capfeatures,captheta)<=float(cap)+1e-7)
    h.setObjective(expr(features,theta) if aux is None else h.qsum(float(v)*x[j] for j,v in enumerate(aux)))
    certify(h);xx=np.array([h.val(x[j]) for j in range(n)])
    if m['integer']:
        if max(abs(xx-np.round(xx)))>1e-5:raise ValueError('nonintegral decision')
        xx=np.round(xx)
    if not feasible(m,xx):raise ValueError('forward infeasible')
    if cap is not None and value(m,base,capfeatures,captheta,xx)>cap+1e-5:raise ValueError('cost cap violation')
    return xx,value(m,base,features,theta,xx)
def feasible(m,x):
    if m['kind']=='tour':return any(np.max(abs(np.array(v)-x))<1e-6 for v in m['choices'])
    ax=np.array(m['A'])@x
    return bool(min(x-np.array(m['lb']))>=-1e-5 and min(np.array(m['ub'])-x)>=-1e-5 and min(ax-np.array(m['rl']))>=-1e-5 and min(np.array(m['ru'])-ax)>=-1e-5)
def numeric(s):
    s=str(s).lower().replace(',','').strip()
    words={'one':1,'two':2,'three':3,'four':4,'half':.5,'third':1/3,'twice':2,'double':2,'quarter':.25}
    if s in words:return words[s]
    if s.endswith('%'):return float(s[:-1])/100
    return float(s)
def parse_nl(id_,r):
    names=r['vars'];n=len(names);mapping=r['var_mention_to_first_var']
    ix=lambda v:names.index(mapping.get(v,v))
    c=np.zeros(n);obj=r['obj_declaration']
    for name,v in obj['terms'].items():c[ix(name)]+=numeric(v)
    if obj['direction']=='maximize':c=-c
    elif obj['direction']!='minimize':raise ValueError('unknown objective direction')
    A=[];rl=[];ru=[]
    for d in r['const_declarations']:
        a=np.zeros(n);b=0.;typ=d['type']
        if typ=='linear':
            for name,v in d['terms'].items():a[ix(name)]+=numeric(v)
            b=numeric(d['limit'])
        elif typ in ['upperbound','lowerbound']:a[ix(d['var'])]=1;b=numeric(d['limit'])
        elif typ=='sum':a[:]=1;b=numeric(d['limit'])
        elif typ in ['xy','xby']:a[ix(d['x_var'])]=1;a[ix(d['y_var'])]-=1 if typ=='xy' else numeric(d['param'])
        elif typ=='ratio':a[:]=-numeric(d['limit']);a[ix(d['var'])]+=1
        else:raise ValueError('unknown constraint type')
        op=d['operator']
        if op not in ['LESS_OR_EQUAL','GREATER_OR_EQUAL','EQUAL']:raise ValueError('unsupported operator')
        A.append(a.tolist());rl.append(b if op in ['GREATER_OR_EQUAL','EQUAL'] else -1e30);ru.append(b if op in ['LESS_OR_EQUAL','EQUAL'] else 1e30)
    return {'id':'nl-'+id_,'sourceId':id_,'collection':'NL4Opt','kind':'lp','names':names,'c':c.tolist(),'A':A,'rl':rl,'ru':ru,'lb':[0.]*n,'ub':[1e30]*n,'integer':False,'sourceText':r['document'],'monitors':{}}
def parse_opt(r):
    q=r['en_question'];matrix={}
    for i,j,c in re.findall(r'City\s+(\d+)\s+to\s+City\s+(\d+)\s+costs\s+(\d+(?:\.\d+)?)',q,re.I):matrix[int(i),int(j)]=float(c)
    # Parse row-list formats independently of objective outcomes.
    for match in re.finditer(r'from\s+City\s+(\d+)(.*?)(?=(?:from\s+City\s+\d+)|$)',q,re.I|re.S):
        i=int(match[1]);body=match[2].split('Each city')[0]
        pairs=re.findall(r'(?:to\s+)?City\s+(\d+)\s*(?:costs?\s*|\(\s*)(\d+(?:\.\d+)?)',body,re.I)
        for j,c in pairs:matrix[i,int(j)]=float(c)
    cities=sorted(set(i for i,j in matrix)|set(j for i,j in matrix));n=len(cities)
    if not 3<=n<=7 or len(matrix)!=n*(n-1) or cities!=list(range(n)):raise ValueError('unsupported or incomplete directed tour matrix')
    edges=[(i,j) for i in cities for j in cities if i!=j];choices=[]
    for tail in itertools.permutations(cities[1:]):
        route=(0,)+tail+(0,);x=[0.]*len(edges)
        for i,j in zip(route,route[1:]):x[edges.index((i,j))]=1.
        choices.append(x)
    return {'id':'opt-'+str(r['id']),'sourceId':r['id'],'collection':'OptMATH','kind':'tour','names':[f'City {i} -> City {j}' for i,j in edges],'c':[matrix[e] for e in edges],'choices':choices,'edges':edges,'sourceAnswer':float(r['en_answer']),'sourceText':q,'monitors':{}}
def source_prepare():
    cfg=read(CFG);OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'freeze.json').exists():raise ValueError('Frozen output already exists')
    save(OUT/'protocol.json',cfg);save(OUT/'protocol-freeze.json',{'sha256':digest(CFG),'createdUtc':datetime.now(timezone.utc).isoformat(),'beforeModelCalls':True})
    nl=[next(iter(json.loads(x).items())) for x in (ROOT/'datasets/llm-grounding-v1/nl4opt-test.jsonl').read_text(encoding='utf8').splitlines()][:12]
    ma={r['id']:r for r in [json.loads(x) for x in (ROOT/'datasets/mamo/mamo_complex_lp.jsonl').read_text(encoding='utf8').splitlines()]}
    op={r['id']:r for r in read(ROOT/'datasets/llm-grounding-v1/OptMATH_Bench.json')}
    audit=[];models=[]
    candidates=[('NL4Opt',i,r) for i,r in nl]+[('MAMO',i,ma[i]) for i in cfg['candidates']['MAMO']]+[('OptMATH',i,op[i]) for i in cfg['candidates']['OptMATH']]
    for collection,id_,r in candidates:
        rec={'collection':collection,'sourceId':id_}
        try:
            if collection=='NL4Opt':m=parse_nl(id_,r)
            elif collection=='OptMATH':m=parse_opt(r)
            else:
                d=parse_diet(r);opt,_=original_solve(d)
                if abs(opt-float(r['Answer']))>1e-5:raise ValueError('original answer mismatch')
                m={'id':'mamo-'+str(id_),'sourceId':id_,'collection':collection,'kind':'diet','names':d['names'],'c':d['c'],'A':d['A'],'rl':d['b'],'ru':[1e30]*len(d['b']),'lb':[0.]*len(d['c']),'ub':[1e30]*len(d['c']),'integer':True,'sourceAnswer':float(r['Answer']),'sourceText':r['Question'],'monitors':{}}
            x,opt=forward(m,m['c'],[],[])
            if 'sourceAnswer' in m and abs(opt-m['sourceAnswer'])>1e-5:raise ValueError(f'public answer mismatch: {opt} vs {m["sourceAnswer"]}')
            n=len(m['c']);rng=random.Random(key(m['id']+'mask-v1'));nonzero=[j for j,v in enumerate(m['c']) if v]
            if len(nonzero)<2:raise ValueError('need a known objective scale anchor')
            hidden=rng.choice(nonzero);scale=st.median(abs(m['c'][j]) for j in nonzero if j!=hidden)
            if m['kind']=='diet':
                m['monitors']={f'{label} relative to requirement':[v/b for v in a] for label,a,b in zip(['protein','carbohydrate','calories'],m['A'],m['rl'])};threshold=1.2
            elif m['kind']=='tour':
                for j in range(3):
                    edges=m['edges'];a=[0.]*n
                    a[edges.index((j%len(set(i for i,k in edges)),(j+1)%len(set(i for i,k in edges))))]=1
                    a[edges.index(((j+1)%len(set(i for i,k in edges)),(j+2)%len(set(i for i,k in edges))))]=1
                    m['monitors'][f'consecutive route pair {j+1}']=a
                threshold=1.
            else:
                for j in range(min(n,3)):
                    c=[0.]*n;c[j]=-1
                    _,v=forward(m,c,[],[])
                    upper=-v
                    if upper<=1e-7:raise ValueError('zero-capacity variable')
                    a=[0.]*n;a[j]=1/upper
                    m['monitors'][m['names'][j]+' capacity share']=a
                threshold=.6
            true_monitor=rng.choice(list(m['monitors']))
            truthfeatures=[{'kind':'linear','variable':m['names'][hidden],'sign':1 if m['c'][hidden]>0 else -1},
                           {'kind':'excess','monitor':true_monitor,'threshold':threshold}]
            truth=[abs(m['c'][hidden])/scale,rng.uniform(1,4)]
            base=[0 if j==hidden else v/scale for j,v in enumerate(m['c'])]
            bank=[truthfeatures[0]]+[{'kind':'excess','monitor':s,'threshold':threshold} for s in m['monitors']]
            public={'id':m['id'],'collection':collection,'task':'Minimize known contextual cost plus unknown signed unit-cost and nonnegative excess penalties. Operational notes describe which terms apply. Physical feasibility is supplied.',
                    'variables':m['names'],'knownBase':base,'monitors':m['monitors'],'domain':m['kind'],'thetaRange':[0,20]}
            if m['kind']!='tour':public['physicalModel']={k:m[k] for k in ['A','rl','ru','lb','ub','integer']}
            else:public['physicalModel']={'cities':len(set(i for i,j in m['edges'])),'directedEdges':m['edges'],'rule':'Hamiltonian cycle; visit all cities once and return'}
            # LLM log writer receives qualitative facts, NEVER hidden weights or source answer.
            other=next(s for s in m['monitors'] if s!=true_monitor)
            facts={'id':m['id'],'variables':m['names'],'monitorDefinitions':m['monitors'],
                   'facts':[f'The ledger omitted the unit {"cost" if truthfeatures[0]["sign"]>0 else "benefit"} of {m["names"][hidden]}; its numerical value is unavailable.',
                            f'When {true_monitor} exceeds {threshold}, each unit of excess creates an extra burden; at or below that level there is no such burden.',
                            f'{other} was discussed but explicitly does not attract a separate penalty.',
                            'The dashboard color changed; it has no effect on costs or decisions.'],
                   'prohibition':'No numeric price or penalty magnitude. Keep the operational threshold. Do not invent an ordering of unknown prices.'}
            rec.update(status='admitted',id=m['id'],originalOptimum=opt,variables=n,truthOutsideBox=any(t>20 for t in truth))
            item={'model':m,'public':public,'trueFeatures':truthfeatures,'truth':truth,'base':base,'allBank':bank,'sourceScale':scale,'hiddenIndex':hidden}
            save(OUT/'oracle'/f'{m["id"]}.json',item);save(OUT/'public'/f'{m["id"]}.json',public);save(OUT/'log-facts'/f'{m["id"]}.json',facts)
            models.append({'id':m['id'],'collection':collection})
        except Exception as e:rec.update(status='excluded',error=str(e))
        audit.append(rec)
    save(OUT/'source-audit.json',audit);save(OUT/'models.json',models)
    files=[p for folder in ['oracle','public','log-facts'] for p in (OUT/folder).glob('*.json')]+[OUT/'protocol.json',OUT/'source-audit.json',OUT/'models.json']
    save(OUT/'freeze.json',{'createdUtc':datetime.now(timezone.utc).isoformat(),'files':{p.relative_to(OUT).as_posix():digest(p) for p in files},'codeSha256':digest(__file__),'numpy':np.__version__,'highspy':hs.Highs().version(),'python':sys.version})
    print(json.dumps({'admitted':models,'excluded':[r for r in audit if r['status']!='admitted']},ensure_ascii=False),flush=True)
def verify():
    f=read(OUT/'freeze.json')
    for rel,s in f['files'].items():
        if digest(OUT/rel)!=s:raise ValueError('frozen input changed '+rel)
def contexts(item,seed):
    m=item['model'];rng=random.Random(key(m['id']+str(seed)+'contexts-v1'));ans=[]
    for k in range(20):
        base=np.array([b*rng.uniform(.5,1.5) for b in item['base']]);s={'context':f'{m["id"]}-s{seed}-c{k}','base':base.tolist()}
        try:
            x,v=forward(m,base,item['trueFeatures'],item['truth'])
            s.update(oracleDecision=x.tolist(),oracleObjective=v,status='complete')
            if k<10:
                s['decisions']={'0':x.tolist()}
                aux=np.array([rng.uniform(.1,2) for b in base])
                try:
                    xn,_=forward(m,base,[],[],aux=aux,cap=v+.1*max(1,abs(v)),capfeatures=item['trueFeatures'],captheta=item['truth'])
                    s['decisions']['0.1']=xn.tolist()
                    s['realizedGap']=max(0,value(m,base,item['trueFeatures'],item['truth'],xn)-v)/max(1,abs(v))
                except Exception as e:s['noisyHistoryError']=str(e)
        except Exception as e:s.update(status='failed',error=str(e))
        ans.append(s)
    return ans
def fit(m,samples,features,lam=.01,epsilon=0.,prior=None,anchor=0.):
    started=time.perf_counter();n=len(features);scale=max(1,st.mean(abs(float(np.dot(s['base'],s['decision']))) for s in samples))
    if n==0:
        losses=[]
        for s in samples:losses.append(max(0,float(np.dot(s['base'],s['decision']))-forward(m,s['base'],[],[])[1])/scale)
        return {'theta':[],'loss':st.mean(losses),'status':'optimal','iterations':0}
    h=solver();t=h.addVariables(n,lb=0,ub=20,obj=[lam/20]*n)
    e=h.addVariables(len(samples),lb=0,obj=[1/len(samples)]*len(samples))
    if anchor:
        z=h.addVariables(n,lb=0,obj=[anchor/20]*n)
        for j in range(n):h.addConstr(z[j]>=t[j]-prior[j]);h.addConstr(z[j]>=prior[j]-t[j])
    for iteration in range(60):
        if time.perf_counter()-started>60:raise TimeoutError('inverse60seconds')
        certify(h);tt=np.array([h.val(t[j]) for j in range(n)]);violations=0;losses=[]
        for k,s in enumerate(samples):
            x,v=forward(m,s['base'],features,tt);delta=phi(m,features,s['decision'])-phi(m,features,x)
            const=float(np.dot(s['base'],np.array(s['decision'])-x));loss=max(0,const+delta@tt)/scale;losses.append(loss)
            if loss-epsilon>h.val(e[k])+1e-6:
                h.addConstr(e[k]>=const/scale-epsilon+h.qsum(float(v/scale)*t[j] for j,v in enumerate(delta)))
                violations+=1
        if not violations:return {'theta':tt.tolist(),'loss':st.mean(losses),'boundedLoss':st.mean(max(0,v-epsilon) for v in losses),'status':'optimal','iterations':iteration+1,'seconds':time.perf_counter()-started}
    raise TimeoutError('inverse60iterations')
def subgradient(m,samples,features):
    n=len(features);tt=np.ones(n);best=tt.copy();bestloss=math.inf;scale=max(1,st.mean(abs(np.dot(s['base'],s['decision'])) for s in samples))
    for k in range(51):
        if k%10==0:
            loss=st.mean(max(0,value(m,s['base'],features,tt,s['decision'])-forward(m,s['base'],features,tt)[1])/scale for s in samples)
            if loss<bestloss:bestloss=loss;best=tt.copy()
        if k==50:break
        s=samples[k%len(samples)];x,_=forward(m,s['base'],features,tt)
        g=(phi(m,features,s['decision'])-phi(m,features,x))/scale
        tt=np.clip(tt-20/math.sqrt(k+1)*g/max(1,np.linalg.norm(g)),0,20)
    return {'theta':best.tolist(),'loss':bestloss,'status':'budgeted','iterations':50}
def structure(features,truefeatures,theta=None):
    inferred={fkey(f) for i,f in enumerate(features) if theta is None or theta[i]>1e-4};truth={fkey(f) for f in truefeatures}
    tp=len(inferred&truth);return {'precision':tp/len(inferred) if inferred else 0,'recall':tp/len(truth),'f1':2*tp/(len(inferred)+len(truth))}
def score(item,test,features,theta):
    m=item['model'];details=[]
    for s in test:
        row={'context':s['context']}
        try:
            if s['status']!='complete':raise ValueError('oracle test unavailable')
            x,pred=forward(m,s['base'],features,theta);true=value(m,s['base'],item['trueFeatures'],item['truth'],x)
            row.update(status='complete',decision=x.tolist(),predictedCost=pred,trueCost=true,oracleCost=s['oracleObjective'],regret=max(0,true-s['oracleObjective'])/max(1,abs(s['oracleObjective'])))
        except Exception as e:row.update(status='failed',error=str(e))
        details.append(row)
    est={fkey(f):v for f,v in zip(features,theta)};truth={fkey(f):v for f,v in zip(item['trueFeatures'],item['truth'])}
    mae=st.mean(abs(est.get(k,0)-v) for k,v in truth.items());rmae=mae/st.mean(truth.values())
    vals=[x['regret'] for x in details if x['status']=='complete']
    return {'status':'complete' if len(vals)==len(test) else 'failed','meanRegret':st.mean(vals) if len(vals)==len(test) else None,'successfulOnlyRegret':st.mean(vals) if vals else None,
            'priceMAE':mae,'relativeMAE':rmae,'nuisanceWeight':sum(v for k,v in est.items() if k not in truth),'structureBefore':structure(features,item['trueFeatures']),'structureAfter':structure(features,item['trueFeatures'],theta),'tests':details}
def llm_record(mode,id_):
    p=OUT/'llm'/mode/f'{id_}.json'
    if not p.exists():raise ValueError('missing API record '+mode)
    r=read(p)
    if r['status']!='ok':raise ValueError('API '+mode+' '+r.get('error','failed'))
    return r['value']
def prepare_histories(id_,seed):
    verify();item=read(OUT/'oracle'/f'{id_}.json');dest=OUT/'contexts'/f'{id_}-s{seed}.json'
    if not dest.exists():save(dest,contexts(item,seed))
    return read(dest)
def evaluate(id_,seed,feedback=False):
    verify();cfg=read(CFG);item=read(OUT/'oracle'/f'{id_}.json');m=item['model'];ss=prepare_histories(id_,seed);rows=[]
    output=OUT/('feedback-results' if feedback else 'jobs')/f'{id_}-s{seed}.json'
    if output.exists():raise ValueError('result exists; no overwrite')
    started=time.perf_counter();cpu=time.process_time();requests=[]
    methods= ['ds_feedback'] if feedback else cfg['methods']+['ds_direct']
    for cap in cfg['noiseCaps']:
        for K in ([10] if feedback else cfg['K']):
            samples=[{**s,'decision':s.get('decisions',{}).get(str(cap))} for s in ss[:K]]
            for method in methods:
                # Numerical prior is estimated from10 histories: do not leak it into K5.
                if method in ['ds_direct','ds_anchor'] and K!=10:continue
                row={'id':id_,'collection':m['collection'],'seed':seed,'noise':cap,'K':K,'method':method};tic=time.perf_counter()
                try:
                    if method in ['zero','unit','random','all_io','oracle_structure_io']:
                        features=item['trueFeatures'] if method=='oracle_structure_io' else item['allBank']
                    else:
                        mode='no_logs' if method=='no_logs_io' else 'shuffled' if method=='shuffled_io' else 'feedback' if feedback else 'proposal'
                        rid=f'{id_}-s{seed}-n{cap}' if feedback else id_
                        features=compile_features(item['public'],llm_record(mode,rid))
                    if method in ['zero','unit','random']:
                        rng=random.Random(key(id_+str(seed)+'constant'))
                        theta=[0 if method=='zero' else 1 if method=='unit' else rng.uniform(0,20) for f in features];fitted={'theta':theta,'status':'constant'}
                    elif method=='ds_direct':
                        g=llm_record('guess',f'{id_}-s{seed}-n{cap}');theta=g.get('weights')
                        if not isinstance(theta,list) or len(theta)!=len(features) or any(isinstance(t,bool) or not isinstance(t,(int,float)) or not math.isfinite(t) or t<0 or t>20 for t in theta):raise ValueError('invalid numerical guess')
                        fitted={'theta':theta,'status':'LLM_direct'}
                    else:
                        if any(s['decision'] is None for s in samples):raise ValueError('history missing for this cap')
                        if method=='subgradient':fitted=subgradient(m,samples,features)
                        elif method=='ds_anchor':
                            prior=llm_record('guess',f'{id_}-s{seed}-n{cap}').get('weights')
                            if not isinstance(prior,list) or len(prior)!=len(features) or any(not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=20 for v in prior):raise ValueError('invalid numerical prior')
                            fitted=fit(m,samples,features,lam=0,epsilon=cap,prior=prior,anchor=.02)
                        else:fitted=fit(m,samples,features,lam=0 if method=='ds_no_l1' else .01)
                    theta=fitted['theta'];row.update(features=features,fit=fitted,**score(item,ss[10:],features,theta))
                    if method=='ds_io' and K==10 and row['status']=='complete':
                        residuals=[]
                        for s in samples:
                            x,v=forward(m,s['base'],features,theta)
                            residuals.append({'context':s['context'],'knownBase':s['base'],'observedDecision':s['decision'],'predictedDecision':x.tolist(),'suboptimalityResidual':max(0,value(m,s['base'],features,theta,s['decision'])-v)})
                        requests.append({'id':f'{id_}-s{seed}-n{cap}','problemId':id_,'features':features,'weights':theta,'topTrainingResiduals':sorted(residuals,key=lambda x:x['suboptimalityResidual'],reverse=True)[:3]})
                except Exception as e:row.update(status='failed',error=str(e))
                row['seconds']=time.perf_counter()-tic;rows.append(row)
            save(OUT/'checkpoints'/f'{id_}-s{seed}{"-feedback" if feedback else ""}.json',{'rows':rows,'seconds':time.perf_counter()-started})
    result={'id':id_,'seed':seed,'rows':rows,'wallSeconds':time.perf_counter()-started,'cpuSeconds':time.process_time()-cpu,'stats':dict(STATS)}
    save(output,result)
    if not feedback:save(OUT/'feedback-requests'/f'{id_}-s{seed}.json',requests)
    print(json.dumps({'id':id_,'seed':seed,'feedback':feedback,'rows':len(rows),'status':dict(Counter(r['status'] for r in rows)),'seconds':result['wallSeconds']}),flush=True)
def requests(mode):
    verify();models=read(OUT/'models.json');result=[]
    for index,meta in enumerate(models):
        id_=meta['id'];pub=read(OUT/'public'/f'{id_}.json')
        if mode=='logs':result.append(read(OUT/'log-facts'/f'{id_}.json'));continue
        try:
            logs=llm_record('logs',id_)['logs']
            if mode in ['proposal','no_logs','shuffled']:
                if mode=='shuffled':
                    group=[m['id'] for m in models if m['collection']==meta['collection']];other=group[(group.index(id_)+1)%len(group)]
                    logs=llm_record('logs',other)['logs']
                result.append({'id':id_,'problem':pub,'logs':[] if mode=='no_logs' else logs});continue
            if mode=='guess':
                features=compile_features(pub,llm_record('proposal',id_))
                for seed in read(CFG)['seeds']:
                    ss=prepare_histories(id_,seed)
                    for cap in read(CFG)['noiseCaps']:
                        history=[{'knownBase':s['base'],'decision':s.get('decisions',{}).get(str(cap))} for s in ss[:10]]
                        result.append({'id':f'{id_}-s{seed}-n{cap}','problem':pub,'logs':logs,'features':features,'history':history,'noiseGapCap':cap})
            if mode=='feedback':
                for seed in read(CFG)['seeds']:
                    p=OUT/'feedback-requests'/f'{id_}-s{seed}.json'
                    if p.exists():
                        for r in read(p):result.append({**r,'problem':pub,'logs':logs})
        except Exception as e:
            save(OUT/'request-failures'/f'{mode}-{id_}.json',{'status':'failed','error':str(e)})
    rng=random.Random(key(mode+'request-order'));rng.shuffle(result)
    save(OUT/'requests'/f'{mode}.json',result);print(json.dumps({'mode':mode,'requests':len(result)}),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode');p.add_argument('--id');p.add_argument('--seed',type=int);a=p.parse_args()
    if a.mode=='prepare':source_prepare()
    elif a.mode=='evaluate':evaluate(a.id,a.seed)
    elif a.mode=='evaluate-feedback':evaluate(a.id,a.seed,True)
    elif a.mode=='histories':prepare_histories(a.id,a.seed)
    else:requests(a.mode)
