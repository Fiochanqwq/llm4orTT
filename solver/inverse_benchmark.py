"""Seeded synthetic smoke protocol; never labelled NLP4LP or human data."""
import argparse
import copy
import json
import math
import random
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from inverse import canonical, dot, cost, forward, recover


LABELS = [('night', '夜班负担', '老员工总说夜班太累，排班时要算上这份负担。'),
          ('handover', '交接损耗', '临时换人总要重新交接，别只看工资。'),
          ('travel', '跨区支援', '跨区支援来回折腾，师傅一般会尽量避免。'),
          ('color', '表格颜色偏好', '有人说蓝色的排班表看着舒服，但这可能与实际安排无关。')]


def make_case(seed=17, k=10, noise=0, masked=2, integer=True):
    if k not in (5, 10, 20) or noise not in (0, .05, .1, .15) or masked not in (1, 2, 3):
        raise ValueError('Use K=5/10/20, noise=0/.05/.1/.15, masked=1/2/3')
    rng = random.Random(seed)
    noise_rng = random.Random(seed + 100003)
    truth = {key: round(rng.uniform(1, 5), 4) if j < masked else 0 for j, (key, _, _) in enumerate(LABELS)}
    hypotheses = [{'id': key, 'label': label, 'source': log, 'lower': 0, 'upper': 10} for key, label, log in LABELS]
    def sample(i):
        names = ['plan_' + str(j) for j in range(6)]
        base = {n: round(rng.uniform(2, 18), 4) for n in names}
        features = {key: {'kind': 'linear', 'terms': {n: rng.randint(0, 4) for n in names}} for key, _, _ in LABELS}
        # Hinge penalty represents a soft policy; its slack is automatically compiled.
        features['night'].update({'kind': 'soft', 'sense': '<=', 'rhs': 1})
        s = {'id': 'context-' + str(i), 'model': {'sense': 'minimize',
             'variables': [{'name': n, 'type': 'binary' if integer else 'continuous', 'lower': 0, 'upper': 1} for n in names],
             'objective': base, 'constraints': [{'terms': {n: 1 for n in names}, 'sense': '=', 'rhs': 1}]},
             'features': features, 'decision': {n: 0 for n in names}}
        # Solve the oracle, including continuous LPs with soft hinge breakpoints.
        canon = canonical(s, hypotheses)
        x, optimum = forward(canon, truth)
        if noise:
            eligible = []
            for n in names:
                proposed = {key: int(key == n) for key in names}
                candidate = canonical({**s, 'decision': proposed}, hypotheses)
                objective = dot(cost(candidate, truth), candidate['observed'])
                if objective <= optimum + noise * max(1, abs(optimum)) + 1e-8:
                    eligible.append(proposed)
            if eligible:
                x = noise_rng.choice(eligible)
        s['decision'] = {n: x[n] for n in names}
        return s
    # Fixed holdout and nested training prefixes across K; noise does not alter contexts.
    all_samples = [sample(i) for i in range(40)]
    data = {'schema': 'contextual-inverse.v1', 'title': '从排班备注恢复隐性偏好',
            'description': '六种可行排班方案中选一种。工资已知，夜班、交接、支援的隐性代价未知。',
            'logs': [log for _, _, log in LABELS], 'hypotheses': hypotheses, 'samples': all_samples[:k],
            'lambda': .01, 'pruneThreshold': .001, 'anomalyThreshold': .1, 'maxIterations': 60,
            'provenance': {'dataset': 'synthetic-scheduling-v1', 'seed': seed, 'K': k,
                           'noiseBudget': noise, 'masked': masked, 'logGenerator': 'deterministic-template',
                           'history': 'solver-generated; not actual human decisions'}}
    return data, truth, all_samples[20:]


def metrics(data, theta, truth, test):
    ids = list(truth)
    a, b = [theta.get(h, 0) for h in ids], [truth[h] for h in ids]
    norm = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
    predicted, actual = {h for h in ids if theta.get(h, 0) > .001}, {h for h in ids if truth[h] > .001}
    tp = len(predicted & actual)
    precision = tp / len(predicted) if predicted else 0
    recall = tp / len(actual) if actual else 1
    regrets = []
    for s in test:
        canon = canonical(s, data['hypotheses'])
        x, _ = forward(canon, theta)
        _, optimum = forward(canon, truth)
        # Recompute minimum hinge slacks: a zero learned penalty may leave arbitrary slack.
        chosen = canonical({**s, 'decision': {v['name']: x[v['name']] for v in s['model']['variables']}}, data['hypotheses'])
        regrets.append(max(0, dot(cost(chosen, truth), chosen['observed']) - optimum))
    return {'mae': sum(abs(x-y) for x, y in zip(a, b)) / len(ids),
            'cosine': sum(x*y for x, y in zip(a, b)) / norm if norm else None,
            'precision': precision, 'recall': recall,
            'f1': 2*precision*recall/(precision+recall) if precision+recall else 0,
            'meanRegret': sum(regrets)/len(regrets), 'maxRegret': max(regrets), 'testSamples': len(test)}


def run_benchmark(seeds, guesses=None):
    rows = []
    for seed in seeds:
        for k in (5, 10, 20):
            for noise in (0, .05, .1, .15):
                for masked in (1, 2, 3):
                    data, truth, test = make_case(seed, k, noise, masked)
                    key = f'{seed}/{k}/{noise}/{masked}'
                    for method, lam in [('text_sparse', .01), ('no_sparsity', 0)]:
                        fitted = recover({**data, 'lambda': lam})
                        rows.append({'case': key, 'method': method, 'K': k, 'noiseBudget': noise, 'masked': masked,
                                     'theta': fitted['theta'], 'truth': truth, 'status': fitted['status'],
                                     **metrics(data, fitted['theta'], truth, test)})
                    guess = (guesses or {}).get(key)
                    if guess is not None:
                        if set(guess) != set(truth) or any(not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 10 for v in guess.values()):
                            raise ValueError('Invalid externally supplied LLM guess for ' + key)
                        rows.append({'case': key, 'method': 'external_llm_guess', **metrics(data, guess, truth, test)})
    return {'schema': 'inverse-benchmark.v1', 'dataset': 'synthetic-scheduling-v1', 'seeds': seeds,
            'limitations': ['Not NLP4LP. Candidate feature dictionary is supplied by the fixture.',
                            'no_sparsity is an ablation, not an unrestricted unknown-constraint-matrix baseline.',
                            'LLM baseline is skipped unless real, separately generated guesses are supplied.',
                            'Noise is a relative objective-gap budget, not a corrupted-sample percentage.',
                            'F1 is candidate-feature support F1, not proof of semantic constraint equivalence.'], 'rows': rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--out', required=True)
    parser.add_argument('--seeds', default='17')
    parser.add_argument('--guesses')
    args = parser.parse_args()
    result = make_case()[0] if args.demo else run_benchmark([int(s) for s in args.seeds.split(',')], json.loads(Path(args.guesses).read_text('utf-8')) if args.guesses else None)
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(str(output))
