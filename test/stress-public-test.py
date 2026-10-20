import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'research'))
import stress_public as s
import numpy as np
def choice():
 return {'family':'TOY','A':[[1,1]],'rl':[1.],'ru':[1.],'lb':[0.,0.],'ub':[1.,1.],'integer':False}
class StressTests(unittest.TestCase):
 def test_linear_cost_and_bounds(self):
  x,v,status=s.solve(choice(),[2,5]);self.assertEqual(status,'optimal');self.assertAlmostEqual(v,2)
 def test_face_exposes_cost_difference(self):
  x,v,_=s.solve(choice(),[0,0]);a=s.solve(choice(),[2,9],capcost=[0,0],cap=v);b=s.solve(choice(),[2,9],capcost=[0,0],cap=v,maximize=True)
  self.assertAlmostEqual(a[1],2);self.assertAlmostEqual(b[1],9)
 def test_unbounded_not_imputed(self):
  m={'family':'TOY','A':[[1]],'rl':[1.],'ru':[1e30],'lb':[0.],'ub':[1e30],'integer':False}
  self.assertEqual(s.solve(m,[-1])[2],'unbounded')
 def test_tsp_subtours_separated(self):
  n=6;edges=list(s.itertools.combinations(range(n),2));A=np.zeros((n,len(edges)))
  for k,(i,j) in enumerate(edges):A[i,k]=A[j,k]=1
  m={'family':'TSPLIB','cities':n,'edges':edges,'A':A.tolist(),'rl':[2.]*n,'ru':[2.]*n,'lb':[0.]*len(edges),'ub':[1.]*len(edges),'integer':True}
  c=[1 if (i<3)==(j<3) else 10 for i,j in edges];x,v,_=s.solve(m,c)
  self.assertEqual(len(s.components(m,x)),1);self.assertEqual(v,24)
 def test_inverse_known_threshold(self):
  F=np.zeros((2,5));F[0,0]=1
  fit=s.Inverse(choice(),[{'base':[0,3],'decision':[0,1]}],F,[0],.01)
  theta,loss=fit.fit();self.assertAlmostEqual(theta[0],3,places=5);self.assertLess(loss,1e-7)
 def test_parameter_interval_is_not_point(self):
  F=np.zeros((2,5));F[0,0]=1
  io=s.Inverse(choice(),[{'base':[0,3],'decision':[0,1]}],F,[0])
  b=io.profiles()['bounds'][0]
  self.assertAlmostEqual(b['lower'],3,places=4);self.assertAlmostEqual(b['upper'],10)
if __name__=='__main__':unittest.main()
