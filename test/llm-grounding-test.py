import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'research'))
from llm_grounding import forward,fit,phi,compile_features,structure,parse_nl,feasible

class GroundingMath(unittest.TestCase):
    def setUp(self):
        self.m={'kind':'diet','names':['x'],'A':[[1]],'rl':[0.],'ru':[4.],'lb':[0.],'ub':[4.],'integer':True,'monitors':{'load':[1.]}}
        self.f=[{'kind':'excess','monitor':'load','threshold':1.}]
    def test_hinge_milp_matches_full_enumeration(self):
        for b in [-2.5,-1.,.2]:
            for t in [0.,.5,2.,4.]:
                x,v=forward(self.m,[b],self.f,[t])
                vals=[b*i+t*max(0,i-1) for i in range(5)]
                self.assertAlmostEqual(v,min(vals),places=6);self.assertTrue(feasible(self.m,x))
    def test_noise_cap_preserves_true_hinge_cost(self):
        x,v=forward(self.m,[-1],[],[],aux=[-1],cap=-.5,capfeatures=self.f,captheta=[2])
        self.assertLessEqual(-x[0]+2*max(0,x[0]-1),-.5+1e-6)
    def test_inverse_constraints_on_every_possible_integer_decision(self):
        samples=[{'base':[-b],'decision':[1.]} for b in [.5,1.,1.5]]
        result=fit(self.m,samples,self.f,lam=.01)
        theta=result['theta'][0]
        for s in samples:
            observed=s['base'][0]
            for i in range(5):self.assertLessEqual(observed,s['base'][0]*i+theta*max(0,i-1)+1e-5)
    def test_empty_hypothesis_is_valid_and_has_no_fake_recovery(self):
        self.assertEqual(compile_features({'variables':['x'],'monitors':{'load':[1]}},{'features':[]}),[])
        self.assertEqual(structure([],self.f)['f1'],0)
    def test_forbidden_expression_never_executes(self):
        with self.assertRaises(ValueError):compile_features({'variables':['x'],'monitors':{}},{'features':[{'kind':'python','code':'raise RuntimeError()'}]})
    def test_nl_annotations_ratio_and_alias(self):
        r={'vars':['a','b'],'var_mention_to_first_var':{'alias':'a'},'document':'test',
           'obj_declaration':{'direction':'maximize','terms':{'alias':'2','b':'1'}},
           'const_declarations':[{'type':'sum','limit':'10','operator':'LESS_OR_EQUAL'},{'type':'ratio','limit':'20%','var':'b','operator':'GREATER_OR_EQUAL'}]}
        m=parse_nl('unit',r);x,v=forward(m,m['c'],[],[])
        self.assertAlmostEqual(v,-18);np.testing.assert_allclose(x,[8,2],atol=1e-6)
if __name__=='__main__':unittest.main()
