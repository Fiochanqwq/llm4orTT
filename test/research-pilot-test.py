import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'research'))
from pilot import BANK, costs, fit, history, validate_hypotheses, score, identified_intervals
from inverse import recover


class PilotTests(unittest.TestCase):
    def fixture(self):
        contexts = []
        for i in range(50):
            plans = [{**{h['id']: 0 for h in BANK}, 'wage': 6, 'handover': 0},
                     {**{h['id']: 0 for h in BANK}, 'wage': 3.1 if i % 2 else 2.9, 'handover': 1}]
            s = {'id': str(i), 'plans': plans, 'chosen': 0 if i % 2 else 1}
            contexts.append(s)
        return {'seed': 123, 'masked': 1, 'truth': {h['id']: 3 if h['id']=='handover' else 0 for h in BANK}, 'contexts': contexts}

    def test_noise_is_feasible_and_bounded_and_prefix_nested(self):
        b = self.fixture()
        for noise in (0,.05,.1,.15):
            all_s = history(b,20,noise)
            self.assertEqual(all_s[:5], history(b,5,noise))
            self.assertTrue(all(0 <= s['realizedGap'] <= noise+1e-8 for s in all_s))
            self.assertTrue(all(0 <= s['chosen'] < len(s['plans']) for s in all_s))
        self.assertTrue(any(s['realizedGap']>0 for s in history(b,20,.05)))

    def test_enumerated_inverse_agrees_with_independent_milp_solver(self):
        b=self.fixture(); hs=[BANK[1]]; samples=history(b,10,0)
        fitted=fit(samples,hs,.01)
        data={'schema':'contextual-inverse.v1','hypotheses':[{'id':'handover','upper':10}], 'lambda':.01,'samples':[]}
        for s in samples:
            names=['a','b']; plans=s['plans']
            data['samples'].append({'id':s['id'],'model':{'variables':[{'name':n,'type':'binary','lower':0,'upper':1} for n in names],
                'objective':dict(zip(names,[p['wage'] for p in plans])), 'constraints':[{'terms':dict.fromkeys(names,1),'sense':'=','rhs':1}]},
                'features':{'handover':{'terms':dict(zip(names,[p['handover'] for p in plans]))}},
                'decision':{n:int(i==s['chosen']) for i,n in enumerate(names)}})
        result=recover(data)
        self.assertAlmostEqual(fitted['objective'],result['objective'],places=6)
        self.assertAlmostEqual(fitted['theta']['handover'],2.9,places=6)

    def test_metrics_use_true_cost_and_missing_features_count(self):
        b=self.fixture()
        oracle=score(b,BANK,b['truth']); wrong=score(b,BANK,{})
        self.assertEqual(oracle['normalizedRegret'],0)
        self.assertGreater(wrong['normalizedRegret'],0)
        self.assertEqual(wrong['supportF1'],0)
        self.assertIsNone(wrong['cosine'])
        self.assertEqual(wrong['hiddenMAE'],3)

    def test_nonidentification_is_not_hidden(self):
        bounds=identified_intervals(history(self.fixture(),20,0))
        self.assertAlmostEqual(bounds['handover'][0],2.9,places=6)
        self.assertAlmostEqual(bounds['handover'][1],3.1,places=6)
        self.assertEqual(bounds['color'][1],10)

    def test_declarative_schema_rejects_invalid_or_overfit_features(self):
        for hs in [[{'id':'night','kind':'linear'}],[BANK[0],BANK[0]],[{'id':'eval','kind':'linear'}]]:
            with self.assertRaises(ValueError):validate_hypotheses(hs)
        self.assertEqual(validate_hypotheses([]),[])

    def test_test_contexts_never_affect_fit_or_training(self):
        b=self.fixture(); modified=copy.deepcopy(b)
        for s in modified['contexts'][30:]:s['plans'][0]['wage']=100000
        self.assertEqual(history(b,20,0),history(modified,20,0))
        self.assertEqual(fit(history(b,20,0),BANK,.01)['theta'],fit(history(modified,20,0),BANK,.01)['theta'])


if __name__=='__main__':unittest.main()
