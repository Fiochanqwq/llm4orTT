"""Public MAMO reconstruction + frozen, locally solved inverse MILP experiment.

Never executes downloaded code. Public source questions are parsed as data.
Learner records contain no hidden costs, source answers or held-out decisions.
"""
import argparse
import copy
import hashlib
import importlib.metadata
import json
import math
import random
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import highspy as hs
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/inverse/mamo-diet-20261020-v2'
PROTOCOL = ROOT / 'research/mamo_protocol.json'


def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8-sig'))


def save(p, value):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def solver():
    h = hs.Highs()
    for k, v in {'output_flag': False, 'threads': 1, 'time_limit': 10.0,
                 'mip_rel_gap': 0.0, 'mip_abs_gap': 0.0, 'random_seed': 17}.items():
        h.setOptionValue(k, v)
    return h


def certified(h):
    h.run()
    if h.getModelStatus() != hs.HighsModelStatus.kOptimal:
        raise ValueError('uncertified solve: ' + str(h.getModelStatus()))


def parse_diet(row):
    q = row['Question'].replace('**', '').replace('a single gram', '1 gram').replace('a single dollar', '1 dollars')
    q = re.sub(r'(?<=\d),(?=\d{3}\b)', '', q)
    nutrient = [r'(\d+)\s*(?:grams?|g)\s+of\s+proteins?',
                r'(\d+)\s*(?:(?:grams?|g)\s+of\s+)?(?:carbohydrates?|carbs)', r'(\d+)\s+calories']
    foods, costs, cols, remaining = [], [], [], []
    for line in q.splitlines():
        values = [re.search(p, line, re.I) for p in nutrient]
        if values[0] is None:
            values[0] = re.search(r'protein (?:powerhouse with|at) (\d+) grams', line, re.I)
        money = re.search(r'(?:\$\s*(\d+(?:\.\d+)?)|(\d+) dollars)', line)
        inherited = re.search(r'same cost as ([\w ]+),', line, re.I)
        price = float(next(g for g in money.groups() if g)) if money else None
        if inherited:
            if inherited.group(1) not in foods: raise ValueError('unresolved price reference')
            price = costs[foods.index(inherited.group(1))]
        if price is not None and all(values):
            title = re.sub(r'^\s*(?:[-*]|\d+[.)])\s*', '', line).split(':')[0]
            title = title.split('(')[0].strip()
            foods.append(title)
            costs.append(price)
            cols.append([float(m.group(1)) for m in values])
        else:
            if re.match(r'^\s*(?:[-*]|\d+[.)])\s*', line) and (price is not None or inherited):
                raise ValueError('unparsed priced food line')
            remaining.append(line)
    if not 4 <= len(foods) <= 12 or len(set(foods)) != len(foods):
        raise ValueError('unsupported/ambiguous food rows: ' + str(len(foods)))
    text = '\n'.join(remaining)
    b = []
    for i, p in enumerate(nutrient):
        hits = re.findall(p, text, re.I)
        if not hits:
            label = ['Protein', 'Carbohydrates', 'Calories'][i]
            hits = re.findall(label + r'\s*:\s*(?:At least\s*)?(\d+)', text, re.I)
        if len(hits) != 1:
            raise ValueError('ambiguous requirement ' + str(i) + ': ' + str(hits))
        b.append(float(hits[0]))
    return {'id': row['id'], 'names': foods, 'A': np.array(cols).T.tolist(),
            'b': b, 'c': costs, 'sourceAnswer': float(row['Answer']),
            'questionSha256': hashlib.sha256(row['Question'].encode()).hexdigest()}


def original_solve(model, integer=True):
    h = solver()
    x = h.addVariables(len(model['c']), obj=model['c'],
                       type=hs.HighsVarType.kInteger if integer else hs.HighsVarType.kContinuous)
    for a, b in zip(model['A'], model['b']):
        h.addConstr(h.qsum(float(v) * x[j] for j, v in enumerate(a)) >= b)
    certified(h)
    return h.getObjectiveValue(), [h.val(x[j]) for j in range(len(x))]


def audit():
    source = ROOT / 'datasets/mamo/mamo_complex_lp.jsonl'
    rows = [json.loads(s) for s in source.read_text(encoding='utf-8').splitlines()]
    models, records = [], []
    for row in rows[:40]:
        record = {'id': row['id'], 'status': 'failed'}
        try:
            m = parse_diet(row)
            integer, x = original_solve(m)
            continuous, _ = original_solve(m, False)
            record.update(integer=integer, continuous=continuous, reference=m['sourceAnswer'],
                          absoluteError=abs(integer-m['sourceAnswer']))
            if abs(integer-m['sourceAnswer']) > 1e-6:
                raise ValueError('integer reconstruction does not match source answer')
            if min(np.asarray(m['A']) @ x - m['b']) < -1e-6:
                raise ValueError('forward infeasibility')
            record['status'] = 'passed'
            models.append(m)
        except Exception as e:
            record['reason'] = str(e)
        records.append(record)
    save(OUT / 'source-audit.json', {'source': str(source.relative_to(ROOT)),
         'sha256': digest(source), 'revision': read(ROOT/'datasets/mamo/revision.json'),
         'license': 'CC BY-SA 4.0', 'audited': 40, 'passed': len(models), 'records': records})
    save(OUT / 'oracle/models.json', models)
    print(json.dumps({'passed': len(models), 'failed': [r for r in records if r['status'] != 'passed']}), flush=True)


def features(s, bank, x):
    return np.array([x[f['variable']] if f['kind'] == 'cost' else
                     max(0.0, float(np.dot(s['A'][f['nutrient']], x)) / s['b'][f['nutrient']] - 1.2)
                     for f in bank])


def forward(s, bank, theta, auxiliary=None, cap=None):
    h = solver()
    n = len(s['base'])
    x = h.addVariables(n, type=hs.HighsVarType.kInteger)
    for a, b in zip(s['A'], s['b']):
        h.addConstr(h.qsum(float(v)*x[j] for j,v in enumerate(a)) >= b)
    terms = [h.qsum(float(v)*x[j] for j,v in enumerate(s['base']))]
    for j, f in enumerate(bank):
        if f['kind'] == 'cost':
            terms.append(float(theta[j])*x[f['variable']])
        elif theta[j] > 0:
            z = h.addVariable(lb=0)
            i = f['nutrient']
            h.addConstr(z >= h.qsum(float(v/s['b'][i])*x[t] for t,v in enumerate(s['A'][i])) - 1.2)
            terms.append(float(theta[j])*z)
    objective = h.qsum(terms)
    if cap is not None:
        h.addConstr(objective <= float(cap)+1e-8)
    if auxiliary is None:
        h.minimize(objective)
    else:
        h.minimize(h.qsum(float(v)*x[j] for j,v in enumerate(auxiliary)))
    if h.getModelStatus() != hs.HighsModelStatus.kOptimal:
        raise ValueError('uncertified forward: '+str(h.getModelStatus()))
    xx = np.array([h.val(x[j]) for j in range(n)])
    if min(np.asarray(s['A']) @ xx - s['b']) < -1e-5 or max(abs(xx-np.round(xx))) > 1e-5:
        raise ValueError('invalid integer decision')
    # Solver-certified integer vectors can contain floating-point dust.
    xx = np.round(xx)
    return xx, float(np.dot(s['base'], xx)+np.dot(theta, features(s,bank,xx)))


def freeze():
    if (OUT/'freeze.json').exists():
        verify_freeze()
        print('Existing frozen dataset verified', flush=True)
        return
    cfg = read(PROTOCOL)
    models = read(OUT/'oracle/models.json')
    public, private, proposals, guesses = [], [], [], []
    for m in models:
        rng = random.Random(cfg['seed']+m['id']*1009)
        hidden = sorted(rng.sample(range(len(m['c'])), 2))
        bank = [{'id': 'cost_'+str(j), 'kind': 'cost', 'variable':j,
                 'label': m['names'][j]+'的未记录单价'} for j in hidden]
        bank += [{'id':'excess_'+str(i), 'kind':'hinge', 'nutrient':i,
                  'label':['蛋白质','碳水','热量'][i]+'超出需求两成后的额外代价'} for i in range(3)]
        truth = [m['c'][j] for j in hidden]+[0,0,0]
        logs = [f"采购备注：{m['names'][j]}不能当成免费食材，账上漏了它的单价，买多少就要付多少。" for j in hidden]
        logs += ['有人说蛋白质超出目标两成以后可能有额外浪费，但暂时没核实。',
                 '碳水和热量只要满足最低要求即可，超出的部分没有另外收费。']
        contexts, oracles = [], []
        for i in range(40):
            b = [round(v*rng.uniform(.7,1.3), 4) for v in m['b']]
            base = [0 if j in hidden else round(v*rng.uniform(.5,1.5),4) for j,v in enumerate(m['c'])]
            s = {'id':f"p{m['id']}-c{i}", 'A':m['A'], 'b':b,'base':base}
            xx, val = forward(s, bank, truth)
            contexts.append(s)
            oracles.append({'x':xx.tolist(),'objective':val})
        histories, gaps = {}, {}
        for noise in cfg['noise_gap_caps']:
            samples, actual = [], []
            for i,s in enumerate(contexts[:20]):
                optimum = oracles[i]['objective']
                if noise == 0:
                    x = np.array(oracles[i]['x'])
                else:
                    nrng = random.Random(cfg['seed']+m['id']*10000+i*100+round(noise*100))
                    aux = [nrng.uniform(.1,2) for _ in m['c']]
                    x, _ = forward(s,bank,truth,auxiliary=aux,cap=optimum+noise*max(1,abs(optimum)))
                actual.append((float(np.dot(s['base'],x)+np.dot(truth,features(s,bank,x)))-optimum)/max(1,abs(optimum)))
                if actual[-1] > noise+1e-6:
                    raise ValueError('noise cap violated')
                samples.append({**s,'decision':x.tolist()})
            histories[str(noise)] = samples
            gaps[str(noise)] = actual
        item = {'id':m['id'], 'split':'development' if m['id']%5==0 else 'evaluation',
                'names':m['names'],'bank':bank,'logs':logs,'histories':histories,'testContexts':contexts[20:]}
        public.append(item)
        private.append({'id':m['id'],'truth':truth,'oracles':oracles,'realizedGaps':gaps})
        proposals.append({'id':m['id'],'logs':logs,'bank':bank})
        if item['split'] == 'evaluation':
            guesses.append({'id':m['id'],'logs':logs,'bank':bank,'names':m['names'],
                            'A':m['A'],'samples':[{'id':s['id'],'b':s['b'],'base':s['base'],'decision':s['decision']}
                                                     for s in histories['0.1'][:10]]})
    save(OUT/'public/problems.json',public)
    save(OUT/'oracle/truth.json',private)
    save(OUT/'public/proposal-requests.json',proposals)
    save(OUT/'public/guess-requests.json',guesses)
    save(OUT/'protocol.json',cfg)
    schedule = [{'id':p['id'],'K':k,'noise':noise,'method':method}
                for p in public for k in cfg['K'] for noise in cfg['noise_gap_caps'] for method in cfg['methods']]
    random.Random(cfg['seed']).shuffle(schedule)
    save(OUT/'schedule.json',schedule)
    paths = ['public/problems.json','oracle/truth.json','public/proposal-requests.json',
             'public/guess-requests.json','protocol.json','schedule.json','source-audit.json']
    save(OUT/'freeze.json',{'createdUtc':datetime.now(timezone.utc).isoformat(),
         'files':{p:digest(OUT/p) for p in paths},'protocolSha256':digest(PROTOCOL),
         'sourceSha256':digest(__file__),'python':sys.version,'highspy':hs.Highs().version(),
         'numpy':np.__version__,'scope':'local pre-run freeze, not external preregistration'})
    print(json.dumps({'problems':len(public),'evaluation':len(guesses),'scheduled':len(schedule)}),flush=True)


def verify_freeze():
    f=read(OUT/'freeze.json')
    if digest(PROTOCOL)!=f['protocolSha256']:
        raise ValueError('protocol changed after freeze')
    for p,d in f['files'].items():
        if digest(OUT/p)!=d:
            raise ValueError('frozen data changed: '+p)


def fit(samples, bank, allowed, lam):
    n=len(bank)
    if not allowed:
        return {'theta':[0.0]*n,'iterations':0,'status':'optimal'}
    h=solver()
    theta=h.addVariables(n,lb=0,ub=[20.0 if j in allowed else 0.0 for j in range(n)],obj=[lam/20]*n)
    scale=max(1.0, statistics.mean(float(np.dot(s['base'],s['decision'])) for s in samples))
    e=h.addVariables(len(samples),lb=0,obj=[1/(len(samples)*scale)]*len(samples))
    observed=[features(s,bank,s['decision']) for s in samples]
    for iteration in range(80):
        certified(h)
        t=np.array([h.val(theta[j]) for j in range(n)])
        cuts=0
        for k,s in enumerate(samples):
            x,v=forward(s,bank,t)
            diff=np.asarray(s['decision'])-x
            delta=observed[k]-features(s,bank,x)
            residual=float(np.dot(s['base'],s['decision'])+np.dot(t,observed[k])-v)
            if residual > h.val(e[k])+1e-6:
                # HiGHS rejects its own warning status for near-zero matrix entries.
                # Remove numerical dust conservatively: theta lies in [0,20],
                # so adding 20*min(delta,0) keeps each dropped term a lower bound.
                kept=[j for j in range(n) if abs(delta[j])>1e-9]
                correction=20*sum(min(float(delta[j]),0) for j in range(n) if j not in kept)
                h.addConstr(e[k] >= float(np.dot(s['base'],diff))+correction+h.qsum(float(delta[j])*theta[j] for j in kept))
                cuts+=1
        if not cuts:
            return {'theta':t.tolist(),'iterations':iteration+1,'status':'optimal','scale':scale,'objective':h.getObjectiveValue()}
    raise ValueError('inverse iteration limit; no certified estimate')


def loss(samples,bank,t):
    values=[]
    for s in samples:
        _,v=forward(s,bank,t)
        values.append(max(0,float(np.dot(s['base'],s['decision'])+np.dot(t,features(s,bank,s['decision']))-v)))
    return statistics.mean(values)


def score(problem, oracle, estimate):
    t=np.array(estimate['theta']);truth=np.array(oracle['truth']);bank=problem['bank']
    regrets=[]
    for i,s in enumerate(problem['testContexts']):
        x,_=forward(s,bank,t)
        objective=float(np.dot(s['base'],x)+np.dot(truth,features(s,bank,x)))
        opt=oracle['oracles'][20+i]['objective']
        if objective < opt-1e-5:
            raise ValueError('decision beats certified oracle')
        regrets.append(max(0,objective-opt)/max(1,abs(opt)))
    a=set(np.flatnonzero(t>1e-3));b=set(np.flatnonzero(truth>1e-3));tp=len(a&b)
    return {'normalizedRegret':statistics.mean(regrets),'testRegrets':regrets,
            'hiddenMAE':float(np.mean(abs(t[:2]-truth[:2]))),
            'cosine':float(np.dot(t,truth)/(np.linalg.norm(t)*np.linalg.norm(truth))) if np.linalg.norm(t)>1e-12 else 0.0,
            'supportF1':2*tp/(len(a)+len(b)), 'nuisanceCount':len(a-b)}


def text_indices(p, records):
    r=records.get(str(p['id']))
    if not r or r['status']!='ok':
        # Transparent local fallback for failed/unavailable paid extraction.
        return [0,1,2], 'local_template_fallback'
    ids=r['value']['features']
    allowed=[j for j,f in enumerate(p['bank']) if f['id'] in ids]
    return allowed, 'deepseek'


def run(problem_id=None):
    verify_freeze()
    cfg=read(PROTOCOL)
    problems={p['id']:p for p in read(OUT/'public/problems.json')}
    truth={p['id']:p for p in read(OUT/'oracle/truth.json')}
    prop_path=OUT/'llm/proposals.json'
    records=read(prop_path) if prop_path.exists() else {}
    # Freeze the actual text-provider outputs before evaluating any methods.
    fingerprint=hashlib.sha256(json.dumps(records,sort_keys=True).encode()).hexdigest()
    for pid,p in problems.items():
        if problem_id is not None and pid!=problem_id:
            continue
        dest=OUT/f'rows/problem-{pid}.json'
        if dest.exists():
            if read(dest)['proposalFingerprint']!=fingerprint:
                raise ValueError('proposal cache changed; start a new run directory')
            continue
        rows=[];allowed,provider=text_indices(p,records)
        for k in cfg['K']:
            for noise in cfg['noise_gap_caps']:
                samples=p['histories'][str(noise)][:k]
                # Shared fits are reused, preserving exact paired inputs.
                cached={}
                for method in cfg['methods']:
                    start=time.perf_counter()
                    row={'id':pid,'split':p['split'],'K':k,'noise':noise,'method':method,'textProvider':provider}
                    try:
                        lam=cfg['lambda'];chosen=allowed
                        if method=='zero_missing': est={'theta':[0]*5,'status':'optimal','iterations':0}
                        elif method=='midpoint': est={'theta':[10,10,0,0,0],'status':'optimal','iterations':0}
                        else:
                            if method.startswith('no_text'): chosen=list(range(5))
                            if method.endswith('no_l1'): lam=0
                            if method=='shuffled_text': chosen=[(j+2)%5 for j in allowed]
                            if method in ['missing_text','local_feedback']: chosen=[j for j in allowed if j!=1]
                            key=(tuple(chosen),lam)
                            if key not in cached: cached[key]=fit(samples,p['bank'],chosen,lam)
                            est=copy.deepcopy(cached[key])
                            if method=='local_feedback':
                                candidates=[(loss(samples,p['bank'],est['theta']),-1,est)]
                                for j in range(5):
                                    if j in chosen: continue
                                    candidate=fit(samples,p['bank'],chosen+[j],lam)
                                    candidates.append((loss(samples,p['bank'],candidate['theta']),j,candidate))
                                _,added,est=min(candidates,key=lambda a:(a[0],a[1]))
                                est={**est,'addedFeature':added}
                        row.update(**est,**score(p,truth[pid],est))
                    except Exception as e:
                        row.update(status='failed',error=str(e))
                    row['seconds']=time.perf_counter()-start
                    rows.append(row)
        save(dest,{'proposalFingerprint':fingerprint,'rows':rows})
        print(json.dumps({'problem':pid,'rows':len(rows),'failures':sum(r['status']!='optimal' for r in rows)}),flush=True)


def evaluate_guesses():
    records=read(OUT/'llm/guesses.json')
    truth={p['id']:p for p in read(OUT/'oracle/truth.json')}
    rows=[]
    for p in read(OUT/'public/problems.json'):
        if p['split']!='evaluation':continue
        r=records.get(str(p['id']),{'status':'failed','error':'missing model answer'})
        row={'id':p['id'],'split':p['split'],'K':10,'noise':.1,'method':'llm_guess'}
        try:
            if r['status']!='ok':raise ValueError(r['error'])
            t=r['value']['theta']
            est={'theta':[float(t[f['id']]) for f in p['bank']]}
            row.update(status='optimal',**est,**score(p,truth[p['id']],est))
        except Exception as e:row.update(status='failed',error=str(e))
        rows.append(row)
    save(OUT/'llm-guess-scores.json',rows)
    print(json.dumps({'guessRows':len(rows),'failures':sum(r['status']!='optimal' for r in rows)}),flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['audit','freeze','run','guesses']);ap.add_argument('--id',type=int)
    args=ap.parse_args()
    {'audit':audit,'freeze':freeze,'run':lambda:run(args.id),'guesses':evaluate_guesses}[args.mode]()
