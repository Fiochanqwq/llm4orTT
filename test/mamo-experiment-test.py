import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'research'))
from mamo_experiment import parse_diet, original_solve, forward, fit, features


class MamoTests(unittest.TestCase):
    def test_parser_rejects_ambiguous_requirement(self):
        q='\n'.join([f'- Food_{i}: {i+1} grams of protein, 2 grams of carbohydrates, and 30 calories for $2.' for i in range(4)])
        with self.assertRaises(ValueError):
            parse_diet({'id':1,'Question':q+'\nAt least 20 grams of protein, 30 grams of protein and 100 calories.','Answer':'10'})

    def test_exact_cut_solution(self):
        bank=[{'kind':'cost','variable':1}]
        samples=[]
        for c,choose in [(2.9,[1,0]),(3.1,[0,1])]:
            samples.append({'A':[[1,1]],'b':[1],'base':[c,0],'decision':choose})
        result=fit(samples,bank,[0],0)
        self.assertEqual(result['status'],'optimal')
        self.assertGreaterEqual(result['theta'][0],2.9-1e-6)
        self.assertLessEqual(result['theta'][0],3.1+1e-6)
        for s in samples:
            _,v=forward(s,bank,result['theta'])
            self.assertAlmostEqual(v,np.dot(s['base'],s['decision'])+np.dot(result['theta'],features(s,bank,s['decision'])))

    def test_noise_feasible_and_capped(self):
        s={'A':[[1,1]],'b':[5],'base':[1,0]}
        bank=[{'kind':'cost','variable':1}]
        _,opt=forward(s,bank,[2])
        x,v=forward(s,bank,[2],auxiliary=[2,.1],cap=opt*1.15)
        self.assertGreaterEqual(sum(x),5)
        self.assertLessEqual(v,opt*1.15+1e-6)
        self.assertLess(np.max(abs(x-np.round(x))),1e-6)

    def test_hinge_value_and_forward(self):
        s={'A':[[1,1]],'b':[2],'base':[1,2]}
        bank=[{'kind':'hinge','nutrient':0}]
        self.assertAlmostEqual(features(s,bank,[3,0])[0],.3)
        x,v=forward(s,bank,[7])
        self.assertAlmostEqual(v,2)
        self.assertEqual(list(x),[2,0])

    def test_numerical_dust_does_not_break_cuts(self):
        bank=[{'kind':'cost','variable':1},{'kind':'cost','variable':2}]
        samples=[{'A':[[1,1,1]],'b':[1],'base':[c,0,0],'decision':x}
                 for c,x in [(2.9,[1,0,0]),(3.1,[0,1+1e-14,0])]]
        result=fit(samples,bank,[0,1],.01)
        self.assertEqual(result['status'],'optimal')
        self.assertGreaterEqual(result['theta'][0],2.9-1e-6)

if __name__=='__main__': unittest.main()
