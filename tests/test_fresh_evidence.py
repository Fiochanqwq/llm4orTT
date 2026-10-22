from copy import deepcopy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'research'))
import fresh_evidence as fresh
import evidence_repair as method
from decision_geometry import compare_models

def box(limit=2):
    return {'sense':'max','objective':[1,1],'constraints':[{'a':[1,0],'op':'<=','b':limit},{'a':[0,1],'op':'<=','b':3}]}

class FreshEvidenceTests(unittest.TestCase):
    def test_no_regression_under_truthful_oracle_for_all_pair_directions(self):
        models=[box(i) for i in (1,2,3)]
        reverse=box();reverse['sense']='min';models.append(reverse)
        models.extend([{'sense':'max','objective':[1,1],'constraints':[]},
                       {'sense':'min','objective':[0,0],'constraints':[{'a':[0,0],'op':'<=','b':-1}]}])
        for a in models:
            for b in models:
                for mode in ('feasibility','joint'):
                    calls=[]
                    def oracle(q):
                        self.assertEqual(set(q),{'kind','point'});calls.append(q)
                        return method.membership(a,q['kind'],q['point'])
                    out=fresh.deliver(a,b,oracle,mode)
                    self.assertTrue(compare_models(a,out['model'])['equivalent'])
                    self.assertLessEqual(len(calls),1)

    def test_correct_proposal_is_accepted_when_joint_separator_exists(self):
        a,b=box(2),box(4)
        out=fresh.deliver(a,b,lambda q:method.membership(b,q['kind'],q['point']),'joint')
        self.assertTrue(out['accepted']);self.assertEqual(out['model'],b)

    def test_missing_oracle_abstains_and_wrong_oracle_can_damage(self):
        a,b=box(2),box(4)
        self.assertEqual(fresh.deliver(a,b,lambda q:None)['model'],a)
        bad=fresh.deliver(a,b,lambda q:not method.membership(a,q['kind'],q['point']))
        self.assertEqual(bad['model'],b)

    def test_objective_only_change_requires_stronger_oracle(self):
        a,b=box(),box();b['sense']='min'
        self.assertIsNone(fresh.fresh_question(a,b,'feasibility'))
        self.assertEqual(fresh.fresh_question(a,b,'joint')['kind'],'optimality')
        self.assertEqual(fresh.deliver(a,b,lambda q:False,'feasibility')['model'],a)

    def test_invalid_and_equivalent_models_need_no_question(self):
        def forbidden(q):raise AssertionError('Unnecessary query')
        self.assertEqual(fresh.deliver(None,box(),forbidden)['model'],box())
        self.assertEqual(fresh.deliver(box(),None,forbidden)['model'],box())
        self.assertEqual(fresh.deliver(box(),box(),forbidden)['reason'],'same_contract')

    def test_stale_points_miss_reversed_ratio_and_fresh_point_finds_it(self):
        a={'sense':'max','objective':[45,55],'constraints':[{'a':[10,12],'op':'<=','b':400},{'a':[-9,11],'op':'<=','b':0}]}
        b=deepcopy(a);b['constraints'][1]['a']=[-11,9]
        for point in ([50,0],[0,'100/3']):
            self.assertEqual(method.membership(a,'feasibility',point),method.membership(b,'feasibility',point))
        out=fresh.deliver(a,b,lambda q:method.membership(a,q['kind'],q['point']))
        self.assertFalse(out['accepted']);self.assertEqual(len(out['queries']),1)

if __name__=='__main__':unittest.main()
