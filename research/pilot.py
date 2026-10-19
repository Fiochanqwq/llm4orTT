"""Frozen, finite-choice inverse MILP pilot. No downloaded code is executed.

Six binary plans with sum(x)=1 permit exact enumeration of all forward solutions.
The inverse epigraph includes every plan: it is the fully separated oracle-cut LP.
The app's independent MILP cutting-plane implementation is checked in tests.
"""
import argparse
import copy
import hashlib
import importlib.metadata
import json
import math
import random
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

import pyomo.environ as pyo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'solver'))
from inverse import optimize

OUT = ROOT / 'outputs/inverse/pilot-20261019-v3'
PROTOCOL = ROOT / 'research/pilot-protocol.json'
BANK = [
    {'id': 'night', 'label': '夜班数超过一次的部分', 'kind': 'hinge', 'threshold': 1},
    {'id': 'handover', 'label': '交接次数', 'kind': 'linear'},
    {'id': 'travel', 'label': '跨区支援次数', 'kind': 'linear'},
    {'id': 'overtime', 'label': '加班小时数', 'kind': 'linear'},
    {'id': 'color', 'label': '表格颜色编号', 'kind': 'linear'},
    {'id': 'badge', 'label': '方案装饰标签编号', 'kind': 'linear'},
]


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def feature(plan, h):
    raw = plan[h['id']]
    return max(0, raw - h['threshold']) if h['kind'] == 'hinge' else raw


def costs(context, hypotheses, theta):
    return [p['wage'] + sum(theta.get(h['id'], 0) * feature(p, h) for h in hypotheses) for p in context['plans']]


def validate_hypotheses(value):
    if not isinstance(value, list) or len(value) > len(BANK):
        raise ValueError('hypotheses must be an array of at most six items')
    allowed = {h['id']: h for h in BANK}
    ids = set()
    for h in value:
        if not isinstance(h, dict) or h.get('id') not in allowed or h['id'] in ids:
            raise ValueError('unknown or duplicate hypothesis ID')
        ids.add(h['id'])
        # A closed declarative bank prevents arbitrary code and per-sample overfitting.
        expected = allowed[h['id']]
        if h.get('kind') != expected['kind'] or h.get('threshold') != expected.get('threshold'):
            raise ValueError('hypothesis must use the declared shared feature definition')
    return [copy.deepcopy(allowed[h['id']]) for h in value]


def history(base, k, noise):
    samples = copy.deepcopy(base['contexts'][:k])
    rng = random.Random(base['seed'] * 10000 + base['masked'] * 100 + round(noise * 100))
    for s in samples:
        c = costs(s, BANK, base['truth'])
        optimum = min(c)
        candidates = [j for j, v in enumerate(c) if 1e-8 < v - optimum <= noise * max(1, abs(optimum)) + 1e-8]
        s['chosen'] = rng.choice(candidates) if candidates else min(range(len(c)), key=c.__getitem__)
        s['realizedGap'] = (c[s['chosen']] - optimum) / max(1, abs(optimum))
    return samples


def learner_samples(samples):
    return [{'id': s['id'], 'plans': s['plans'], 'chosen': s['chosen']} for s in samples]


def prepare():
    config = read(PROTOCOL)
    if (OUT / 'freeze.json').exists():
        if read(OUT / 'freeze.json')['protocolSha256'] != digest(PROTOCOL):
            raise ValueError('Frozen protocol changed. Use a new experiment ID/directory.')
        print('Using existing frozen data', flush=True)
        return
    bases = []
    for seed in config['seeds']:
        for masked in config['masked']:
            rng = random.Random(seed * 100 + masked)
            active = set(rng.sample([h['id'] for h in BANK[:4]], masked))
            truth = {h['id']: round(rng.uniform(1, 5), 4) if h['id'] in active else 0 for h in BANK}
            contexts = []
            for i in range(50):
                plans = [{**{h['id']: rng.randint(0, 4) for h in BANK}, 'wage': round(rng.uniform(2, 18), 4)} for _ in range(6)]
                s = {'id': f'context-{i}', 'plans': plans}
                c = costs(s, BANK, truth)
                s['chosen'] = min(range(6), key=c.__getitem__)
                contexts.append(s)
            bases.append({'id': f's{seed}-m{masked}', 'seed': seed, 'masked': masked, 'truth': truth, 'contexts': contexts})
    save(OUT / 'oracle/private-bases.json', bases)
    save(OUT / 'protocol.json', config)
    # Generator sees relevant semantics, but NEVER the hidden weights or histories.
    requests = [{'id': b['id'], 'semanticFacts': [h for h in BANK if b['truth'][h['id']] > 0],
                 'nuisance': '表格颜色和装饰标签有人闲聊，但不影响实际工作代价。'} for b in bases]
    save(OUT / 'generator/log-requests.json', requests)
    save(OUT / 'public/feature-bank.json', BANK)
    schedule = [{'base': b['id'], 'K': k, 'noise': n, 'method': method}
                for b in bases for k in config['K'] for n in config['noise_gap_budgets'] for method in config['methods']]
    random.Random(20261019).shuffle(schedule)
    save(OUT / 'schedule.json', schedule)
    freeze = {'createdUtc': datetime.now(timezone.utc).isoformat(), 'protocolSha256': digest(PROTOCOL),
              'dataSha256': digest(OUT / 'oracle/private-bases.json'), 'scheduleSha256': digest(OUT / 'schedule.json'),
              'sourceSha256': digest(__file__), 'configurations': len(bases), 'scheduledRows': len(schedule),
              'note': 'Local preregistration frozen before LLM calls/results, not an external registry.'}
    save(OUT / 'freeze.json', freeze)
    print(json.dumps(freeze), flush=True)


def build_guess_requests():
    requests = []
    logs = read(OUT / 'llm/logs.json')
    config = read(PROTOCOL)
    for b in read(OUT / 'oracle/private-bases.json'):
        for k in config['K']:
            for noise in config['noise_gap_budgets']:
                requests.append({'id': f"{b['id']}-k{k}-n{int(noise*100)}", 'base': b['id'],
                                 'logs': logs.get(b['id']), 'bank': BANK,
                                 'samples': learner_samples(history(b, k, noise))})
    save(OUT / 'public/guess-requests.json', requests)


def fit(samples, hypotheses, lam):
    if not hypotheses:
        residuals = [max(0, s['plans'][s['chosen']]['wage'] - min(p['wage'] for p in s['plans'])) for s in samples]
        return {'theta': {}, 'meanResidual': statistics.mean(residuals), 'objective': statistics.mean(residuals), 'residuals': residuals, 'status': 'optimal'}
    m = pyo.ConcreteModel()
    m.theta = pyo.Var([h['id'] for h in hypotheses], bounds=(0, 10))
    m.e = pyo.Var(range(len(samples)), domain=pyo.NonNegativeReals)
    m.rows = pyo.ConstraintList()
    for i, s in enumerate(samples):
        chosen = s['plans'][s['chosen']]
        for p in s['plans']:
            m.rows.add(m.e[i] >= chosen['wage'] - p['wage'] + sum(m.theta[h['id']] * (feature(chosen, h) - feature(p, h)) for h in hypotheses))
    m.obj = pyo.Objective(expr=sum(m.e.values()) / len(samples) + lam * sum(m.theta.values()))
    optimize(m)
    theta = {key: pyo.value(v) for key, v in m.theta.items()}
    residuals = []
    for s in samples:
        c = costs(s, hypotheses, theta)
        residuals.append(max(0, c[s['chosen']] - min(c)))
    objective = statistics.mean(residuals) + lam * sum(theta.values())
    assert abs(objective - pyo.value(m.obj)) < 1e-6
    return {'theta': theta, 'meanResidual': statistics.mean(residuals), 'objective': objective, 'residuals': residuals, 'status': 'optimal'}


def score(base, hypotheses, theta):
    truth = base['truth']
    a, b = [theta.get(h['id'], 0) for h in BANK], list(truth.values())
    norm = math.sqrt(sum(v*v for v in a) * sum(v*v for v in b))
    actual = {h for h, v in truth.items() if v > .001}
    predicted = {h for h, v in theta.items() if v > .001}
    tp = len(actual & predicted)
    regret, normalized = [], []
    for s in base['contexts'][30:50]:
        estimated = costs(s, hypotheses, theta)
        decision = min(range(len(estimated)), key=estimated.__getitem__)
        true_cost = costs(s, BANK, truth)
        gap = max(0, true_cost[decision] - min(true_cost))
        regret.append(gap)
        normalized.append(gap / max(1, abs(min(true_cost))))
    return {'hiddenMAE': statistics.mean(abs(theta.get(h, 0)-truth[h]) for h in actual),
            'fullMAE': statistics.mean(abs(x-y) for x, y in zip(a, b)),
            'cosine': sum(x*y for x, y in zip(a, b))/norm if norm else None,
            'supportF1': 2*tp/(len(actual)+len(predicted)),
            'supportRecall': tp/len(actual), 'supportPrecision': tp/len(predicted) if predicted else 0,
            'meanRegret': statistics.mean(regret), 'normalizedRegret': statistics.mean(normalized),
            'testRegrets': regret, 'testNormalizedRegrets': normalized}


def response_value(path, key):
    records = read(path) if Path(path).exists() else {}
    record = records.get(key)
    if not record or record.get('status') != 'ok':
        raise ValueError('LLM response unavailable or invalid; see raw request records')
    return record['value']


def run():
    config = read(PROTOCOL)
    freeze = read(OUT / 'freeze.json')
    assert digest(PROTOCOL) == freeze['protocolSha256']
    assert digest(OUT / 'oracle/private-bases.json') == freeze['dataSha256']
    bases = {b['id']: b for b in read(OUT / 'oracle/private-bases.json')}
    rows = []
    target = OUT / 'results.jsonl'
    target.write_text('', encoding='utf-8')
    for seq, job in enumerate(read(OUT / 'schedule.json')):
        base = bases[job['base']]
        samples = history(base, job['K'], job['noise'])
        row = {**job, 'runOrder': seq+1, 'changedHistories': sum(s['realizedGap'] > 1e-8 for s in samples),
               'realizedNoiseFraction': statistics.mean(s['realizedGap'] > 1e-8 for s in samples),
               'meanHistoryGap': statistics.mean(s['realizedGap'] for s in samples)}
        try:
            if job['method'] == 'no_text_dictionary':
                hypotheses, lam = BANK, config['lambda']
            elif job['method'] in ('text_sparse', 'text_no_l1'):
                proposal = response_value(OUT / 'llm/proposals.json', base['id'])
                hypotheses = validate_hypotheses(proposal['hypotheses'])
                lam = config['lambda'] if job['method'] == 'text_sparse' else 0
            else:
                key = f"{base['id']}-k{job['K']}-n{int(job['noise']*100)}"
                guess = response_value(OUT / 'llm/guesses.json', key)
                theta = guess['theta']
                if set(theta) != {h['id'] for h in BANK} or any(type(v) not in (float, int) or not math.isfinite(v) or not 0 <= v <= 10 for v in theta.values()):
                    raise ValueError('Invalid LLM weights')
                hypotheses = BANK
                row.update({'status': 'ok', 'theta': theta, **score(base, hypotheses, theta)})
            if job['method'] != 'llm_guess':
                fitted = fit(samples, hypotheses, lam)
                row.update({**fitted, **score(base, hypotheses, fitted['theta'])})
                row['retained'] = [h for h, v in fitted['theta'].items() if v > .001]
                row['proposed'] = [h['id'] for h in hypotheses]
        except Exception as error:
            row.update({'status': 'failed', 'error': str(error)})
        rows.append(row)
        with target.open('a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False, allow_nan=False)+'\n')
        if (seq+1) % 24 == 0:
            print(f'Completed {seq+1}/{len(read(OUT / "schedule.json"))} rows', flush=True)
    save(OUT / 'versions.json', {'python': sys.version, 'pyomo': importlib.metadata.version('pyomo'),
                               'highspy': importlib.metadata.version('highspy'), 'sourceSha256': digest(__file__)})


def identified_intervals(samples):
    # Conditional on the FULL declared dictionary and exact clean optimality.
    m = pyo.ConcreteModel()
    m.theta = pyo.Var([h['id'] for h in BANK], bounds=(0, 10))
    m.rows = pyo.ConstraintList()
    for s in samples:
        chosen = s['plans'][s['chosen']]
        for p in s['plans']:
            expr = chosen['wage']-p['wage'] + sum(m.theta[h['id']]*(feature(chosen,h)-feature(p,h)) for h in BANK)
            m.rows.add(expr <= 1e-8)
    m.obj = pyo.Objective(expr=0)
    intervals = {}
    for h in BANK:
        m.obj.set_value(m.theta[h['id']]); m.obj.sense = pyo.minimize; optimize(m)
        lo = pyo.value(m.theta[h['id']])
        m.obj.sense = pyo.maximize; optimize(m)
        intervals[h['id']] = [lo, pyo.value(m.theta[h['id']])]
    return intervals


def feedback_requests():
    requests, checks = [], []
    for base in read(OUT / 'oracle/private-bases.json'):
        try:
            proposal = response_value(OUT / 'llm/proposals.json', base['id'])
            hypotheses = validate_hypotheses(proposal['hypotheses'])
            samples = history(base, 20, 0)
            # Deliberate missing-log/structure stress arm, separate from primary comparison.
            removed = hypotheses[0]['id'] if hypotheses else None
            partial = hypotheses[1:] if hypotheses else []
            fitted = fit(samples, partial, .01)
            logs = response_value(OUT / 'llm/logs.json', base['id'])
            requests.append({'id': base['id'], 'bank': BANK, 'logs': logs,
                             'currentHypotheses': partial, 'estimatedWeights': fitted['theta'],
                             'history': learner_samples(samples), 'residuals': fitted['residuals']})
            checks.append({'base': base['id'], 'removedProposedFeature': removed,
                           'initialHypotheses': partial, 'initialFit': fitted})
        except Exception as e:
            checks.append({'base': base['id'], 'status': 'failed', 'error': str(e)})
    save(OUT / 'public/feedback-requests.json', requests)
    save(OUT / 'feedback-before.json', checks)


def feedback_evaluate():
    bases = {b['id']: b for b in read(OUT / 'oracle/private-bases.json')}
    checks = read(OUT / 'feedback-before.json')
    for c in checks:
        if c.get('status') == 'failed':
            continue
        b = bases[c['base']]
        try:
            proposal = response_value(OUT / 'llm/feedback.json', c['base'])
            hypotheses = validate_hypotheses(proposal['hypotheses'])
            fitted = fit(history(b, 20, 0), hypotheses, .01)
            def validation(hs, theta):
                values = []
                for s in b['contexts'][20:30]:
                    predicted = costs(s, hs, theta)
                    j = min(range(len(predicted)), key=predicted.__getitem__)
                    # Choose among models by imitation disagreement on held-out history,
                    # with no hidden true cost coefficients exposed to acceptance.
                    values.append(int(j != s['chosen']))
                return statistics.mean(values)
            before = validation(c['initialHypotheses'], c['initialFit']['theta'])
            after = validation(hypotheses, fitted['theta'])
            accepted = after < before - 1e-8 or (abs(after-before)<1e-8 and fitted['meanResidual'] < c['initialFit']['meanResidual']-1e-6)
            c.update({'status': 'ok', 'candidateHypotheses': hypotheses, 'candidateFit': fitted,
                      'validationDisagreementBefore': before, 'validationDisagreementAfter': after,
                      'accepted': accepted, 'testBefore': score(b, c['initialHypotheses'], c['initialFit']['theta']),
                      'testAfter': score(b, hypotheses if accepted else c['initialHypotheses'], fitted['theta'] if accepted else c['initialFit']['theta'])})
        except Exception as e:
            c.update({'status': 'failed', 'error': str(e)})
    save(OUT / 'feedback-results.json', checks)
    intervals = []
    for b in bases.values():
        intervals.append({'base': b['id'], 'K': 20, 'bounds': identified_intervals(history(b, 20, 0)), 'truth': b['truth']})
    save(OUT / 'identifiability.json', intervals)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['prepare', 'requests', 'run', 'feedback-requests', 'feedback-evaluate'])
    args = parser.parse_args()
    {'prepare': prepare, 'requests': build_guess_requests, 'run': run,
     'feedback-requests': feedback_requests, 'feedback-evaluate': feedback_evaluate}[args.stage]()
