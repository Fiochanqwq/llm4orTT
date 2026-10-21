"""Local validation, empirical fit ranges and separate bounded-noise checks.

No language model, network client, held-out truth or benchmark labels are used.
Ranges describe the empirical loss sublevel set, not statistical confidence.
"""
import copy
import hashlib
import json
import sys
import time
from pathlib import Path

import pyomo.environ as pyo
sys.path.insert(0, str(Path(__file__).resolve().parent))
from inverse import canonical, cost, dot, fit, forward, optimize, recover, validate
from inverse_sensitivity import analyze_with_sensitivity as analyze_compatibility


def loss(sample, theta, seconds):
    _, optimum = forward(sample, theta, seconds)
    return max(0, dot(cost(sample, theta), sample['observed']) - optimum)


def profile_bound(data, samples, target, allowed_loss, maximize=False):
    """Exact LP dualization / MILP separation over a bounded theta box."""
    m = pyo.ConcreteModel()
    m.theta = pyo.Var([h['id'] for h in data['hypotheses']], domain=pyo.NonNegativeReals)
    for h in data['hypotheses']:
        m.theta[h['id']].setlb(h.get('lower', 0))
        m.theta[h['id']].setub(h.get('upper', 20))
    m.e = pyo.Var(range(len(samples)), domain=pyo.NonNegativeReals)
    m.rows = pyo.ConstraintList()
    cs = []
    for k, s in enumerate(samples):
        c = {v['name']: s['base'].get(v['name'], 0) + sum(m.theta[h] * f.get(v['name'], 0) for h, f in s['features'].items()) for v in s['variables']}
        cs.append(c)
        if not s['integer']:
            y = pyo.Var(range(len(s['rows'])), domain=pyo.NonNegativeReals)
            m.add_component('dual_' + str(k), y)
            for n in c:
                m.rows.add(sum(a.get(n, 0) * y[j] for j, (a, _) in enumerate(s['rows'])) == c[n])
            m.rows.add(m.e[k] >= sum(c[n] * s['observed'][n] for n in c) - sum(b * y[j] for j, (_, b) in enumerate(s['rows'])))
    m.budget = pyo.Constraint(expr=sum(m.e.values()) / len(samples) <= allowed_loss)
    m.obj = pyo.Objective(expr=m.theta[target], sense=pyo.maximize if maximize else pyo.minimize)
    tolerance = data.get('tolerance', 1e-6)
    for iteration in range(int(data.get('maxIterations', 40))):
        optimize(m, data.get('seconds', 15))
        theta = {h['id']: pyo.value(m.theta[h['id']], exception=False) for h in data['hypotheses']}
        theta = {h['id']: theta[h['id']] if theta[h['id']] is not None else h.get('lower', 0) for h in data['hypotheses']}
        cuts, residuals = [], []
        for k, s in enumerate(samples):
            x, optimum = forward(s, theta, data.get('seconds', 15))
            residual = max(0, dot(cost(s, theta), s['observed']) - optimum)
            residuals.append(residual)
            if s['integer'] and residual > pyo.value(m.e[k]) + tolerance:
                cuts.append((k, x))
        if not cuts:
            if sum(residuals) / len(samples) > allowed_loss + 2*tolerance:
                raise ValueError('Profile candidate fails the empirical loss budget')
            return {'status': 'optimal', 'value': theta[target], 'iterations': iteration + 1}
        for k, x in cuts:
            m.rows.add(m.e[k] >= sum(cs[k][n] * (samples[k]['observed'][n] - x[n]) for n in x))
    return {'status': 'iteration_limit', 'value': None, 'iterations': data.get('maxIterations', 40)}


def analyze(input_data):
    started = time.monotonic()
    data = copy.deepcopy(input_data)
    validate(data)
    baseline = recover(data)  # Also verifies historical feasibility before diagnostics.
    samples = [canonical(s, data['hypotheses']) for s in data['samples']]
    diagnostics = {'schema': 'local-inverse-analysis.v1', 'modelCalls': 0, 'notes': [],
                   'originalLambda': data.get('lambda', .01), 'selectedLambda': data.get('lambda', .01)}
    # This is a distinct, explicitly budgeted set, never a relabelled fit interval.
    # Bounded desktop work. Never silently truncate historical samples.
    if len(samples) > 30 or len(data['hypotheses']) > 8:
        diagnostics['compatibility'] = analyze_compatibility(data, baseline.get('theta'))
        diagnostics.update(status='skipped_size_limit')
        diagnostics['notes'].append('本地深度检查限30条历史、8个候选；基础求解仍使用完整输入。')
        return {'input': data, 'result': baseline, 'analysis': diagnostics}
    if baseline['status'] != 'optimal':
        diagnostics['compatibility'] = analyze_compatibility(data, baseline.get('theta'))
        diagnostics.update(status='skipped_uncertified_baseline')
        return {'input': data, 'result': baseline, 'analysis': diagnostics}
    selected = baseline
    if len(samples) >= 6:
        ordered = sorted(range(len(samples)), key=lambda i: hashlib.sha256(samples[i]['id'].encode()).hexdigest())
        assignment = {i: rank % 3 for rank, i in enumerate(ordered)}
        candidates = []
        for lam in [0, .001, .01, .1]:
            scores, folds = [], []
            try:
                for fold in range(3):
                    train = [s for i, s in enumerate(samples) if assignment[i] != fold]
                    validation = [s for i, s in enumerate(samples) if assignment[i] == fold]
                    fitted = fit({**data, 'lambda': lam}, train)
                    if fitted['status'] != 'optimal':
                        raise ValueError('Training fit not certified optimal')
                    values = [loss(s, fitted['theta'], data.get('seconds', 15)) / max(1, abs(dot(s['base'], s['observed']))) for s in validation]
                    scores.extend(values)
                    folds.append({'fold': fold, 'trainIds': [s['id'] for s in train], 'validationIds': [s['id'] for s in validation], 'loss': sum(values)/len(values)})
                candidates.append({'lambda': lam, 'status': 'optimal', 'validationLoss': sum(scores)/len(scores), 'folds': folds})
            except Exception as error:
                candidates.append({'lambda': lam, 'status': 'failed', 'error': str(error)})
        valid = [c for c in candidates if c['status'] == 'optimal']
        if valid:
            best = min(valid, key=lambda c: (c['validationLoss'], c['lambda']))
            proposal = {**data, 'lambda': best['lambda']}
            fitted = recover(proposal)
            if fitted['status'] == 'optimal':
                selected, data = fitted, proposal
                diagnostics['selectedLambda'] = best['lambda']
        diagnostics['crossValidation'] = {'folds': 3, 'grid': candidates,
            'metric': 'held-out suboptimality / max(1, abs(known base cost at observation)); not true decision regret',
            'tieRule': 'smaller lambda', 'splitRule': 'SHA256(sample id), round-robin; exchangeable histories assumed'}
    else:
        diagnostics['notes'].append('不足6条历史，保留原正则化强度，不做交叉验证。')
    diagnostics['compatibility'] = analyze_compatibility(data, selected.get('theta'))
    diagnostics['compatibility']['pointEstimateSource'] = 'selected_point_estimate'
    # Profile against the best unregularized empirical residual, not a L1-biased point.
    unregularized = fit({**data, 'lambda': 0}, samples)
    ranges = []
    if unregularized['status'] == 'optimal':
        minimum = sum(r['residual'] for r in unregularized['residuals']) / len(samples)
        epsilon = max(1e-6, data.get('tolerance', 1e-6)*10)
        for h in data['hypotheses']:
            try:
                lo = profile_bound(data, samples, h['id'], minimum + epsilon)
                hi = profile_bound(data, samples, h['id'], minimum + epsilon, True)
                certified = lo['status'] == hi['status'] == 'optimal'
                ranges.append({'id': h['id'], 'label': h.get('label', h['id']), 'status': 'optimal' if certified else 'iteration_limit',
                               'lower': lo['value'] if certified else None, 'upper': hi['value'] if certified else None})
            except Exception as error:
                ranges.append({'id': h['id'], 'label': h.get('label', h['id']), 'status': 'failed', 'error': str(error), 'lower': None, 'upper': None})
        diagnostics['identification'] = {'minimumMeanResidual': minimum, 'lossAllowance': epsilon, 'ranges': ranges,
            'meaning': 'coordinate projections of the bounded near-minimum empirical suboptimality set; not confidence intervals or proof of population identifiability'}
    else:
        diagnostics['notes'].append('无正则残差尚未证明最优，不报告参数区间。')
    diagnostics.update(status='complete' if ranges and all(r['status']=='optimal' for r in ranges) else 'partial', elapsedMs=round((time.monotonic()-started)*1000))
    return {'input': data, 'result': selected, 'analysis': diagnostics}


if __name__ == '__main__':
    try:
        print(json.dumps(analyze(json.load(sys.stdin)), ensure_ascii=True, allow_nan=False))
    except Exception as error:
        print(json.dumps({'status': 'error', 'error': str(error)}, ensure_ascii=True))
        sys.exit(1)
