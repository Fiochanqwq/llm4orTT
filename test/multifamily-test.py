import itertools
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'research'))
import multifamily as m
import numpy as np

class ResearchTests(unittest.TestCase):
    def test_tour_enumeration_requires_return(self):
        q="""From City A, the cost is 19 units to City B, 45 units to City C, and 30 units to City D.
From City B, it costs 19 units to City A, 89 units to City C, and 46 units to City D.
From City C, it costs 45 units to City A, 89 units to City B, and 11 units to City D.
From City D, it costs 30 units to City A, 46 units to City B, and 11 units to City C."""
        model=m.parse_tour({'id':61,'Question':q})
        self.assertEqual(len(model['choices']),3)
        self.assertEqual(m.solve(model,model['c'])[1],121)
        self.assertTrue(all(sum(x)==4 for x in model['choices']))

    def test_zero_cost_flow_has_unbounded_bad_optimal_face(self):
        model={'family':'relocation','A':[[-1,1],[1,-1]],'b':[-2,1]}
        x,v,s=m.solve(model,[0,0]);self.assertEqual(s,'optimal')
        best=m.solve(model,[1,1],cap_cost=[0,0],cap=v)
        worst=m.solve(model,[1,1],cap_cost=[0,0],cap=v,maximize=True)
        self.assertEqual(best[1],1);self.assertEqual(worst[2],'unbounded')

    def test_finite_tour_tie_envelope(self):
        model={'family':'tour','choices':[[1,0],[0,1]]}
        self.assertEqual(m.solve(model,[2,7],cap_cost=[0,0],cap=0)[1],2)
        self.assertEqual(m.solve(model,[2,7],cap_cost=[0,0],cap=0,maximize=True)[1],7)

    def test_inverse_separation_agrees_with_hand_bound(self):
        F=np.zeros((2,5));F[0,0]=1
        samples=[{'family':'tour','choices':[[1,0],[0,1]],'base':[0,3],'decision':[0,1]}]
        result=m.fit(samples,F,10,[0],lam=.01)
        self.assertAlmostEqual(result['theta'][0],3,places=5)

    def test_positive_floor_and_center_use_no_truth(self):
        F=np.zeros((2,5));F[0,0]=1;F[1,1]=1
        samples=[{'family':'tour','choices':[[1,0],[0,1]],'base':[0,0],'decision':[1,0]}]
        floor=m.fit(samples,F,10,[0,1],lam=.01,floor=True)
        self.assertAlmostEqual(min(floor['theta'][:2]),1)
        center=m.fit(samples,F,10,[0,1],center=True)
        self.assertTrue(np.allclose(center['theta'][:2],[5,5],atol=1e-5))

if __name__=='__main__':unittest.main()
