import sys
import unittest
from fractions import Fraction as Q
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"research"))
from language_resolution_map import maximize, certificate, cell_metrics, inject, status
from language_decisions import endpoint
from language_density import materialize_density


class ResolutionTests(unittest.TestCase):
    def test_exact_four_dimensions(self):
        rows=[]
        for j in range(4):
            u=tuple(int(j==k) for k in range(4))
            rows.extend([(u,Q(2)),(tuple(-v for v in u),Q(0))])
        value,x=maximize(rows,[1,2,3,4])
        self.assertEqual(value,20)
        self.assertEqual(x,[2,2,2,2])

    def test_agrees_with_old_exact_vertex_enumeration(self):
        _,public,truth=materialize_density("dispatch",82001)
        for selected in ([],[truth['activeFactor']],sorted(truth['thetaTenths'])):
            for cap in (0,1,2):
                old=endpoint(public,selected,'p0',cap)
                new=certificate(public,selected,'p0',Q(cap))
                self.assertEqual(new['feasible'],old['status']!='incompatible')
                self.assertEqual(new['worstRegret'],old['worstRegret'])

    def test_null_and_abstention_are_retained(self):
        got=cell_metrics([{'dangerous':False,'status':'safe'},{'dangerous':False,'status':'unresolved'}])
        self.assertIsNone(got['sensitivity']['rate'])
        self.assertEqual(got['specificity']['rate'],.5)
        self.assertEqual(got['specificity']['denominator'],2)

    def test_deterministic_injection_and_strict_threshold(self):
        _,public,_=materialize_density('dispatch',82001)
        one=inject(public,'dispatch-s82001')
        self.assertEqual(one,inject(public,'dispatch-s82001'))
        self.assertNotIn('injected_zero_3',public['histories'][0]['actions'][0]['monitors'])
        self.assertEqual(status({'feasible':True},{'feasible':True,'worstRegret':'1/4'},Q(1,4)),'safe')
        self.assertEqual(status({'feasible':False},{'feasible':True,'worstRegret':'1/4'},Q(1,4)),'unresolved')


if __name__=='__main__':
    unittest.main()
