import sys,unittest,itertools
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'research'))
from llm_grounding_stable_fit import sparse_box_lower_cut,fit_stable
class StableCuts(unittest.TestCase):
    def test_cut_is_lower_bound_at_all_box_vertices(self):
        coeff=[1e-16,-1e-10,.7,-.9]
        kept,offset=sparse_box_lower_cut(coeff)
        for theta in itertools.product([0,20],repeat=4):
            self.assertLessEqual(offset+sum(v*theta[j] for j,v in kept),np.dot(coeff,theta)+1e-12)
    def test_dropped_uncertainty_is_below_separation_tolerance(self):
        coeff=[(-1.)**j*9e-10 for j in range(8)]
        kept,offset=sparse_box_lower_cut(coeff)
        spread=20*sum(abs(v) for v in coeff)
        self.assertLess(spread,1e-6)
    def test_full_inverse_still_explains_all_choices(self):
        m={'kind':'diet','names':['x'],'A':[[1]],'rl':[0.],'ru':[4.],'lb':[0.],'ub':[4.],'integer':True,'monitors':{'load':[1.]}}
        fs=[{'kind':'excess','monitor':'load','threshold':1}]
        r=fit_stable(m,[{'base':[-1.5],'decision':[1]}],fs)
        self.assertGreaterEqual(r['theta'][0],1.5-1e-6)
if __name__=='__main__':unittest.main()
