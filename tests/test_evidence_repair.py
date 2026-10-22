"""Scientific invariants for evidence acquisition and final-model selection."""
from copy import deepcopy
from fractions import Fraction as F
from itertools import combinations
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'research'))
import evidence_repair as method
from decision_geometry import compare_models


def box(limit=2):
    return {'sense':'max','objective':['1','1'],'constraints':[
        {'a':['1','0'],'op':'<=','b':str(limit)},
        {'a':['0','1'],'op':'<=','b':'3'}]}


class EvidenceRepairTests(unittest.TestCase):
    def test_exact_panel_separates_all_generated_contracts(self):
        prepared=method.prepare(box(2),box(4))
        for i,j in combinations(range(len(prepared['bank'])),2):
            self.assertFalse(compare_models(prepared['bank'][i]['model'],prepared['bank'][j]['model'])['equivalent'])
            self.assertGreater(prepared['distance'][i,j],0)

    def test_ray_and_empty_domains_are_distinguishable(self):
        for peer in ({'sense':'max','objective':[1,1],'constraints':[]},
                     {'sense':'min','objective':[1,1],'constraints':[{'a':[0,0],'op':'<=','b':-1}]}):
            p=method.prepare(box(),peer)
            self.assertGreater(p['distance'][p['initial_index'],p['peer_index']],0)

    def test_objective_error_is_not_identified_by_feasibility_queries(self):
        peer=box(); peer['sense']='min'
        p=method.prepare(box(),peer)
        a,b=p['initial_index'],p['peer_index']
        self.assertTrue(all(p['predictions'][a,q]==p['predictions'][b,q] for q in method.available(p,'feasibility')))
        self.assertTrue(any(p['predictions'][a,q]!=p['predictions'][b,q] for q in method.available(p,'joint')))

    def test_clean_evidence_never_removes_a_covered_truth(self):
        p=method.prepare(box(2),box(4))
        for truth in range(len(p['bank'])):
            evidence=[(q,bool(p['predictions'][truth,q])) for q in range(len(p['queries']))]
            self.assertEqual(method.survivors(p,evidence),[truth])

    def test_one_error_budget_retains_covered_truth(self):
        p=method.prepare(box(2),box(4)); truth=p['peer_index']
        evidence=[(q,bool(p['predictions'][truth,q])) for q in range(len(p['queries']))]
        q,label=evidence[0]; evidence[0]=(q,not label)
        self.assertIn(truth,method.survivors(p,evidence,1))
        self.assertNotIn(truth,method.survivors(p,evidence,0))

    def test_gate_only_accepts_strict_panel_risk_improvement(self):
        p=method.prepare(box(2),box(4)); a=p['initial_index']
        for remaining in ([i] for i in range(len(p['bank']))):
            chosen,abstained,loss=method.choose(p,remaining,'gated')
            if not abstained:
                self.assertLess(loss,max(p['distance'][a,j] for j in remaining))
            else:
                self.assertEqual(chosen,a)

    def test_oracle_access_is_counted_and_contains_only_a_question(self):
        p=method.prepare(box(2),box(4)); calls=[]
        def oracle(question):
            self.assertEqual(set(question),{'kind','point'})
            calls.append(question)
            return method.membership(box(4),question['kind'],question['point'])
        states=method.adaptive(p,oracle,'feasibility','risk',17,budget=2)
        self.assertLessEqual(len(calls),2)
        self.assertEqual(states[-1]['attempts'],len(calls))
        self.assertEqual(states[0]['selected'],p['initial_index'])

    def test_missing_labels_do_not_filter_candidates(self):
        p=method.prepare(box(2),box(4))
        self.assertEqual(method.survivors(p,[(0,None)]),list(range(len(p['bank']))))

    def test_invalid_initial_and_both_invalid_remain_representable(self):
        p=method.prepare(None,box())
        self.assertIsNone(p['initial_index'])
        self.assertTrue(p['bank'])
        empty=method.prepare(None,None)
        self.assertEqual(method.adaptive(empty,lambda _:True,'joint','risk',17)[-1]['selected'],None)

    def test_constraint_permutation_does_not_change_candidate_contracts(self):
        a,b=box(2),box(4)
        first=method.prepare(a,b)
        a['constraints'].reverse(); b['constraints'].reverse()
        second=method.prepare(a,b)
        self.assertEqual([method.fingerprint(x['model']) for x in first['bank']],
                         [method.fingerprint(x['model']) for x in second['bank']])
        self.assertEqual(first['queries'],second['queries'])

    def test_fixed_sequence_is_answer_free_and_repeatable(self):
        p=method.prepare(box(2),box(4))
        a=method.fixed_sequence(p,'joint')
        b=method.fixed_sequence(p,'joint')
        self.assertEqual(a,b)
        self.assertEqual(len(a),len(set(a)))
        self.assertLessEqual(len(a),8)

    def test_fingerprint_matches_exact_comparison_on_controlled_models(self):
        models=[box(1),box(2),box(3),box(4)]
        redundant=box(2); redundant['constraints'].append({'a':[2,0],'op':'<=','b':4}); models.append(redundant)
        for a in models:
            for b in models:
                self.assertEqual(method.fingerprint(a)==method.fingerprint(b),compare_models(a,b)['equivalent'])


if __name__=='__main__':
    unittest.main()
