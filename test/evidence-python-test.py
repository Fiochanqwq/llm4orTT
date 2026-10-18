"""Exercise detector failure branches without pretending fabricated solves are real."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'solver'))
import evidence
import pyomo.environ as pyo
from unittest.mock import patch

m = pyo.ConcreteModel()
m.x = pyo.Var(['x'], bounds=(0, None))
m.objective = pyo.Objective(expr=3*m.x['x'], sense=pyo.maximize)
m.constraints = pyo.ConstraintList()
m.constraints.add(m.x['x'] <= 10)
data = dict(sense='maximize', variables=[dict(name='x', type='continuous', lower=0, upper=None)], objective={'x':3}, constraints=[dict(name='capacity', terms={'x':1}, sense='<=', rhs=10)])
e = evidence.inspect_model(m, data, '最大化 3x，限制 x<=10。')
class Result:
    class solver:
        termination_condition = 'optimal'
    solution = [1]
class BrokenSolver:
    def solve(self, model, **kwargs):
        # Deliberate violation: a tighter cap is claimed to yield higher profit.
        model.x['x'].value = 11 if pyo.value(model.constraints[1].upper) < 10 else 9
        return Result()
with patch('pyomo.core.base.PyomoModel.ModelSolutions.load_from', lambda *a, **k: None):
    evidence.postsolve(e, m, data, dict(status='optimal', values={'x':10}, objective=30), BrokenSolver(), 2, True)
assert e['monotonicity_violated']
assert len(e['monotonicity_anomalies']) == 2
assert e['auxiliary_solves'] == 2
assert evidence.prompt_numbers('x1 12 2.5 1e3 容量20') == [2.5,12.0,20.0,1000.0]
print('Python detector checks passed')
