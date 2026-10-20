import copy
import importlib.util
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'solver'))
from inverse_local import analyze, profile_bound
from inverse import canonical
spec=importlib.util.spec_from_file_location('fixtures',ROOT/'test/inverse-python-test.py')
fixtures=importlib.util.module_from_spec(spec); spec.loader.exec_module(fixtures)


class LocalTests(unittest.TestCase):
    def test_lp_and_milp_identification_match_analytic_bracket(self):
        for integer in (False, True):
            data=fixtures.bracket(integer)
            result=analyze(data)
            ranges={r['id']:r for r in result['analysis']['identification']['ranges']}
            self.assertEqual(result['analysis']['modelCalls'],0)
            self.assertEqual(result['analysis']['status'],'complete')
            self.assertAlmostEqual(ranges['benefit']['lower'],2.9,places=3)
            self.assertAlmostEqual(ranges['benefit']['upper'],3.1,places=3)
            self.assertEqual(ranges['irrelevant']['lower'],0)
            self.assertEqual(ranges['irrelevant']['upper'],20)

    def test_cross_validation_partitions_have_no_overlap_and_ignore_test_truth(self):
        data=fixtures.bracket(True)
        data['samples']=[{**copy.deepcopy(data['samples'][i%2]),'id':str(i)} for i in range(6)]
        before=copy.deepcopy(data)
        result=analyze({**data,'truth':{'benefit':999},'test':[{'secret':'do not use'}]})
        self.assertEqual(data,before)
        for candidate in result['analysis']['crossValidation']['grid']:
            self.assertEqual(candidate['status'],'optimal')
            held=[]
            for f in candidate['folds']:
                self.assertFalse(set(f['trainIds']) & set(f['validationIds']))
                held.extend(f['validationIds'])
            self.assertEqual(sorted(held),[str(i) for i in range(6)])
        self.assertNotIn('secret',str(result['analysis']))

    def test_failed_separation_never_claims_a_bound(self):
        data=fixtures.bracket(True); data['maxIterations']=1
        samples=[canonical(s,data['hypotheses']) for s in data['samples']]
        result=profile_bound(data,samples,'benefit',.00001,True)
        self.assertEqual(result['status'],'iteration_limit')
        self.assertIsNone(result['value'])

    def test_feasibility_checked_before_validation(self):
        data=fixtures.bracket(True); data['samples'][0]['decision']['x']=.5
        with self.assertRaises(ValueError):analyze(data)

if __name__=='__main__':unittest.main()
