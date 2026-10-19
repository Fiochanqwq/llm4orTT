"""Contextual inverse LP/MILP, data-only input, anchored objective weights.

LP: primal-dual gap epigraph. MILP: exact forward-oracle separation.
Unknown hard constraint coefficients are deliberately outside the v1 contract.
"""
import copy
import json
import importlib.metadata
import math
import sys
import time
import pyomo.environ as pyo


def number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 1e9:
        raise ValueError(label + ': expected finite number with magnitude <= 1e9')
    return float(value)


def dot(a, b):
    return sum(v * b.get(k, 0) for k, v in a.items())


def validate(data):
    if not isinstance(data, dict) or data.get('schema') != 'contextual-inverse.v1':
        raise ValueError('Expected schema contextual-inverse.v1')
    hypotheses, samples = data.get('hypotheses'), data.get('samples')
    if not isinstance(hypotheses, list) or not 1 <= len(hypotheses) <= 32:
        raise ValueError('Provide 1 to 32 hypotheses')
    if not isinstance(samples, list) or not 1 <= len(samples) <= 100:
        raise ValueError('Provide 1 to 100 historical samples')
    ids = [h['id'] for h in hypotheses]
    if len(set(ids)) != len(ids) or any(not isinstance(i, str) or not i or len(i) > 80 for i in ids):
        raise ValueError('Hypothesis IDs must be unique strings')
    for h in hypotheses:
        lo, hi = number(h.get('lower', 0), 'lower'), number(h.get('upper', 20), 'upper')
        if not 0 <= lo <= hi:
            raise ValueError('v1 requires nonnegative bounded weights; encode cost direction in features')
    sample_ids = [s['id'] for s in samples]
    if len(set(sample_ids)) != len(sample_ids) or any(not isinstance(i, str) or not i for i in sample_ids):
        raise ValueError('Sample IDs must be unique strings')
    for s in samples:
        variables = s['model']['variables']
        if not 1 <= len(variables) <= 200 or len(s['model']['constraints']) > 500:
            raise ValueError('v1 limit: 200 variables and 500 rows per sample')
        names = [v['name'] for v in variables]
        if len(set(names)) != len(names) or any(not isinstance(n, str) or not n or n.startswith('__io_') for n in names):
            raise ValueError('Invalid or duplicate variable name')
        if s['model'].get('sense', 'minimize') != 'minimize':
            raise ValueError('Canonical model must minimize; negate maximization objective and features')
        def terms(t):
            if not isinstance(t, dict) or any(k not in names for k in t):
                raise ValueError('Unknown variable in coefficients')
            for value in t.values():
                number(value, 'coefficient')
        for v in variables:
            if v['type'] not in ('continuous', 'integer', 'binary'):
                raise ValueError('Invalid variable type')
            lo, hi = v.get('lower'), v.get('upper')
            if lo is not None:
                number(lo, 'variable lower')
            if hi is not None:
                number(hi, 'variable upper')
            if lo is not None and hi is not None and lo > hi:
                raise ValueError('Inconsistent variable bounds')
        terms(s['model']['objective'])
        if not any(s['model']['objective'].values()):
            raise ValueError('A known nonzero cost anchor is required to prevent the all-zero objective')
        for row in s['model']['constraints']:
            terms(row['terms'])
            number(row['rhs'], 'rhs')
            if row['sense'] not in ('<=', '>=', '='):
                raise ValueError('Invalid constraint sense')
        if set(s['features']) != set(ids):
            raise ValueError('Each sample needs exactly one feature per hypothesis')
        for f in s['features'].values():
            terms(f['terms'])
            if f.get('kind', 'linear') not in ('linear', 'soft'):
                raise ValueError('Feature kind must be linear or soft')
            if f.get('kind') == 'soft':
                number(f['rhs'], 'soft rhs')
                if f['sense'] not in ('<=', '>='):
                    raise ValueError('Soft features support <= and >=')
        if set(s['decision']) != set(names):
            raise ValueError('Historical decision must include exactly the original variables')
        for value in s['decision'].values():
            number(value, 'decision')
    for key, default, lo, hi in [('lambda', .01, 0, 100), ('pruneThreshold', .001, 0, 1),
                                  ('tolerance', 1e-6, 1e-9, .01), ('anomalyThreshold', .1, 0, 1e9),
                                  ('seconds', 15, 1, 60), ('maxIterations', 40, 1, 200)]:
        value = number(data.get(key, default), key)
        if not lo <= value <= hi or (key == 'maxIterations' and int(value) != value):
            raise ValueError('Invalid ' + key)
    return data


def canonical(sample, hypotheses):
    """Represent all rows and variable bounds as A z >= b with free z."""
    variables = copy.deepcopy(sample['model']['variables'])
    rows, features = [], {}
    observed = dict(sample['decision'])
    for row in sample['model']['constraints']:
        for sign in ([1, -1] if row['sense'] == '=' else [1] if row['sense'] == '>=' else [-1]):
            rows.append(({n: sign * v for n, v in row['terms'].items()}, sign * row['rhs']))
    for j, h in enumerate(hypotheses):
        f = sample['features'][h['id']]
        if f.get('kind') == 'soft':
            name = '__io_soft_' + str(j)
            variables.append({'name': name, 'type': 'continuous', 'lower': 0, 'upper': None})
            sign = 1 if f['sense'] == '<=' else -1
            violation = sign * (dot(f['terms'], observed) - f['rhs'])
            observed[name] = max(0, violation)
            rows.append(({**{n: -sign * v for n, v in f['terms'].items()}, name: 1}, -sign * f['rhs']))
            features[h['id']] = {name: 1}
        else:
            features[h['id']] = f['terms']
    for v in variables:
        lo, hi = v.get('lower'), v.get('upper')
        if v['type'] == 'binary':
            lo, hi = max(0, lo if lo is not None else 0), min(1, hi if hi is not None else 1)
        if lo is not None:
            rows.append(({v['name']: 1}, lo))
        if hi is not None:
            rows.append(({v['name']: -1}, -hi))
    infeasibility = max([0] + [b - dot(a, observed) for a, b in rows])
    integral_error = max([0] + [abs(observed[v['name']] - round(observed[v['name']])) for v in variables if v['type'] != 'continuous'])
    return {'id': sample['id'], 'variables': variables, 'rows': rows, 'features': features,
            'base': sample['model']['objective'], 'observed': observed,
            'infeasibility': max(infeasibility, integral_error),
            'integer': any(v['type'] != 'continuous' for v in variables)}


def optimize(model, seconds=15):
    solver = pyo.SolverFactory('appsi_highs')
    solver.options.update({'time_limit': seconds, 'threads': 1, 'mip_rel_gap': 0})
    result = solver.solve(model, load_solutions=False)
    status = str(result.solver.termination_condition)
    if status != 'optimal':
        raise ValueError('Solver did not certify optimality: ' + status)
    model.solutions.load_from(result)
    return model


def cost(sample, theta):
    return {v['name']: sample['base'].get(v['name'], 0) + sum(theta[h] * f.get(v['name'], 0) for h, f in sample['features'].items()) for v in sample['variables']}


def forward(sample, theta, seconds=15):
    m = pyo.ConcreteModel()
    m.x = pyo.Var([v['name'] for v in sample['variables']], domain=pyo.Reals)
    for v in sample['variables']:
        if v['type'] != 'continuous':
            m.x[v['name']].domain = pyo.Integers
    m.rows = pyo.ConstraintList()
    for a, b in sample['rows']:
        expr = sum(val * m.x[n] for n, val in a.items())
        m.rows.add(expr >= b if a else pyo.Constraint.Feasible if b <= 0 else pyo.Constraint.Infeasible)
    c = cost(sample, theta)
    m.obj = pyo.Objective(expr=sum(c[n] * m.x[n] for n in m.x))
    optimize(m, seconds)
    x = {n: pyo.value(m.x[n]) for n in m.x}
    return x, dot(c, x)


def fit(data, samples, fixed=None):
    hypotheses = data['hypotheses']
    m = pyo.ConcreteModel()
    m.theta = pyo.Var([h['id'] for h in hypotheses], domain=pyo.NonNegativeReals)
    for h in hypotheses:
        m.theta[h['id']].setlb(h.get('lower', 0))
        m.theta[h['id']].setub(h.get('upper', 20))
        if h['id'] in (fixed or []):
            m.theta[h['id']].fix(0)
    m.e = pyo.Var(range(len(samples)), domain=pyo.NonNegativeReals)
    m.rows = pyo.ConstraintList()
    coefficients = []
    for k, s in enumerate(samples):
        c = {v['name']: s['base'].get(v['name'], 0) + sum(m.theta[h] * f.get(v['name'], 0) for h, f in s['features'].items()) for v in s['variables']}
        coefficients.append(c)
        if not s['integer']:
            y = pyo.Var(range(len(s['rows'])), domain=pyo.NonNegativeReals)
            m.add_component('dual_' + str(k), y)
            for n in c:
                m.rows.add(sum(a.get(n, 0) * y[r] for r, (a, _) in enumerate(s['rows'])) == c[n])
            m.rows.add(m.e[k] >= sum(c[n] * s['observed'][n] for n in c) - sum(b * y[r] for r, (_, b) in enumerate(s['rows'])))
    lam = data.get('lambda', .01)
    m.obj = pyo.Objective(expr=sum(m.e.values()) / len(samples) + lam * sum(m.theta.values()))
    trace, tol = [], data.get('tolerance', 1e-6)
    for iteration in range(int(data.get('maxIterations', 40))):
        optimize(m, data.get('seconds', 15))
        theta = {h: pyo.value(m.theta[h]) for h in m.theta}
        residuals, cuts = [], []
        for k, s in enumerate(samples):
            x, optimum = forward(s, theta, data.get('seconds', 15))
            residual = max(0, dot(cost(s, theta), s['observed']) - optimum)
            residuals.append({'id': s['id'], 'residual': residual, 'counterfactual': {n: v for n, v in x.items() if not n.startswith('__io_')}})
            if s['integer'] and residual > pyo.value(m.e[k]) + tol:
                cuts.append((k, x))
        lower = pyo.value(m.obj)
        upper = sum(r['residual'] for r in residuals) / len(samples) + lam * sum(theta.values())
        trace.append({'iteration': iteration + 1, 'lowerBound': lower, 'upperBound': upper, 'gap': max(0, upper - lower), 'cutsAdded': len(cuts)})
        if not cuts:
            return {'status': 'optimal', 'theta': theta, 'residuals': residuals, 'trace': trace, 'objective': upper}
        for k, x in cuts:
            m.rows.add(m.e[k] >= sum(coefficients[k][n] * (samples[k]['observed'][n] - x[n]) for n in x))
    return {'status': 'iteration_limit', 'theta': theta, 'residuals': residuals, 'trace': trace, 'objective': upper}


def recover(data):
    validate(data)
    started = time.monotonic()
    samples = [canonical(s, data['hypotheses']) for s in data['samples']]
    rejected = [{'id': s['id'], 'violation': s['infeasibility']} for s in samples if s['infeasibility'] > 1e-6]
    if rejected:
        raise ValueError('Historical decisions violate known hard constraints or integrality; repair inputs, do not treat them as suboptimal observations: ' + json.dumps(rejected))
    result = fit(data, samples)
    threshold = data.get('pruneThreshold', .001)
    pruned = [h['id'] for h in data['hypotheses'] if h.get('lower', 0) == 0 and result['theta'][h['id']] <= threshold] if result['status'] == 'optimal' else []
    initial_trace = result['trace']
    if pruned and any(result['theta'][h] != 0 for h in pruned):
        refined = fit(data, samples, pruned)
        refined['prePruneObjective'] = result['objective']
        result = refined
    result.update({'schema': 'contextual-inverse-result.v1', 'method': 'strong_duality' if not any(s['integer'] for s in samples) else 'hybrid_oracle_cuts',
                   'versions': {'python': sys.version.split()[0], 'pyomo': importlib.metadata.version('pyomo'), 'highspy': importlib.metadata.version('highspy')},
                   'pruned': pruned, 'initialTrace': initial_trace,
                   'meanResidual': sum(r['residual'] for r in result['residuals']) / len(samples),
                   'anomalies': [r for r in result['residuals'] if r['residual'] > data.get('anomalyThreshold', .1)],
                   'hypotheses': [{**h, 'weight': result['theta'][h['id']], 'retained': h['id'] not in pruned} for h in data['hypotheses']],
                   'identifiability': 'not_certified: zero residual does not imply unique parameter recovery; known cost anchor and feature units must be informative',
                   'elapsedMs': round((time.monotonic() - started) * 1000)})
    return result


if __name__ == '__main__':
    try:
        print(json.dumps(recover(json.load(sys.stdin)), ensure_ascii=True, allow_nan=False))
    except Exception as error:
        print(json.dumps({'status': 'error', 'error': str(error)}, ensure_ascii=True))
        sys.exit(1)
