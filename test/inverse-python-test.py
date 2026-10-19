import copy
import math
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'solver'))
from inverse import canonical, cost, dot, forward, recover
from inverse_benchmark import make_case, metrics


def bracket(integer=False):
    # Selecting x=1 below price 3 and x=0 above price 3 identifies theta within [2.9,3.1].
    samples = []
    for i, price in enumerate([2.9, 3.1]):
        samples.append({'id': str(i), 'model': {'sense': 'minimize',
            'variables': [{'name': 'x', 'type': 'binary' if integer else 'continuous', 'lower': 0, 'upper': 1}],
            'objective': {'x': price}, 'constraints': []},
            'features': {'benefit': {'terms': {'x': -1}}, 'irrelevant': {'terms': {'x': 0}}},
            'decision': {'x': 1 if i == 0 else 0}})
    return {'schema': 'contextual-inverse.v1', 'hypotheses': [{'id': 'benefit'}, {'id': 'irrelevant'}],
            'samples': samples, 'lambda': .01}


class InverseTests(unittest.TestCase):
    def test_lp_strong_duality_and_sparse_irrelevant(self):
        r = recover(bracket())
        self.assertEqual(r['status'], 'optimal')
        self.assertEqual(r['method'], 'strong_duality')
        self.assertAlmostEqual(r['theta']['benefit'], 2.9, places=6)
        self.assertEqual(r['theta']['irrelevant'], 0)
        self.assertLess(r['meanResidual'], 1e-7)

    def test_milp_agrees_with_lp_on_integral_fixture(self):
        r = recover(bracket(True))
        self.assertEqual(r['status'], 'optimal')
        self.assertAlmostEqual(r['theta']['benefit'], 2.9, places=6)
        self.assertTrue(any(t['cutsAdded'] for t in r['trace']))
        self.assertLess(r['trace'][-1]['gap'], 1e-6)

    def test_iteration_limit_is_not_success(self):
        r = recover({**bracket(True), 'maxIterations': 1})
        self.assertEqual(r['status'], 'iteration_limit')
        self.assertGreater(r['trace'][-1]['gap'], 0)

    def test_reject_invalid_data(self):
        mutations = [lambda d: d['samples'][0]['decision'].update(x=.5),
                     lambda d: d['samples'][0]['decision'].update(x=2),
                     lambda d: d['samples'][0]['model']['objective'].update(x=0),
                     lambda d: d.update(**{'lambda': -1}),
                     lambda d: d['samples'][0]['features']['benefit']['terms'].update(unknown=1),
                     lambda d: d['samples'][0]['decision'].update(x=float('nan'))]
        for mutation in mutations:
            d = bracket(True); mutation(d)
            with self.assertRaises((ValueError, KeyError)):
                recover(d)

    def test_negative_free_variables_and_equality(self):
        d = bracket()
        for s in d['samples']:
            s['model']['variables'][0].update(lower=-1, upper=None)
            s['model']['constraints'] = [{'terms': {'x': 1}, 'sense': '=', 'rhs': -1}]
            s['decision']['x'] = -1
        self.assertLess(recover(d)['meanResidual'], 1e-7)

    def test_soft_penalty_and_holdout_metrics(self):
        d, truth, holdout = make_case(k=20, integer=False)
        r = recover(d)
        self.assertEqual(r['method'], 'strong_duality')
        self.assertTrue(math.isfinite(metrics(d, r['theta'], truth, holdout)['meanRegret']))
        for s, residual in zip(d['samples'], r['residuals']):
            c = canonical(s, d['hypotheses'])
            _, optimum = forward(c, r['theta'])
            self.assertAlmostEqual(residual['residual'], max(0, dot(cost(c, r['theta']), c['observed']) - optimum), places=6)

    def test_noise_is_feasible_and_bounded(self):
        d, truth, _ = make_case(noise=.15)
        for s in d['samples']:
            c = canonical(s, d['hypotheses'])
            _, optimum = forward(c, truth)
            self.assertLessEqual(c['infeasibility'], 1e-8)
            self.assertLessEqual(dot(cost(c, truth), c['observed']) - optimum, .15*max(1, abs(optimum)) + 1e-7)

    def test_determinism_and_private_truth(self):
        a, truth, _ = make_case()
        b, _, _ = make_case()
        self.assertEqual(a, b)
        self.assertNotIn('truth', a)
        self.assertNotIn('theta', a)
        self.assertTrue(truth)

    def test_k_and_noise_share_contexts_and_fixed_holdout(self):
        small, _, test_small = make_case(k=5)
        large, _, test_large = make_case(k=20)
        noisy, _, _ = make_case(k=5, noise=.15)
        self.assertEqual(small['samples'], large['samples'][:5])
        self.assertEqual(test_small, test_large)
        self.assertEqual([s['model'] for s in small['samples']], [s['model'] for s in noisy['samples']])


if __name__ == '__main__':
    unittest.main()
