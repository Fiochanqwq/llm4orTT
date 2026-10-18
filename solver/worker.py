"""Fixed LP/MILP builder. Input is data only; never eval/exec user or LLM code."""
import json
import sys
import math
import time
import importlib.metadata
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence import inspect_model, postsolve


def emit(value):
    print("LLM4OR_RESULT=" + json.dumps(value, ensure_ascii=True, allow_nan=False), flush=True)


def finite(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def solve(request):
    import pyomo.environ as pyo
    data = request['model']
    model = pyo.ConcreteModel()
    model.x = pyo.Var([v['name'] for v in data['variables']], domain=pyo.Reals)
    domains = {'continuous': pyo.Reals, 'integer': pyo.Integers, 'binary': pyo.Binary}
    for variable in data['variables']:
        x = model.x[variable['name']]
        x.domain = domains[variable['type']]
        x.setlb(variable['lower'])
        x.setub(variable['upper'])
    def expr(terms):
        return sum(value * model.x[name] for name, value in terms.items() if value != 0)
    model.objective = pyo.Objective(expr=expr(data['objective']), sense=pyo.maximize if data['sense'] == 'maximize' else pyo.minimize)
    model.constraints = pyo.ConstraintList()
    for constraint in data['constraints']:
        lhs, rhs = expr(constraint['terms']), constraint['rhs']
        model.constraints.add(lhs <= rhs if constraint['sense'] == '<=' else lhs >= rhs if constraint['sense'] == '>=' else lhs == rhs)
    evidence = inspect_model(model, data, request.get('problem', '')) if request.get('evidence', True) else None
    if request.get('mode') == 'audit':
        return {'status': 'unknown', 'programmaticEvidence': evidence}
    engine = request['engine']
    solver = pyo.SolverFactory('gurobi_direct', manage_env=True) if engine == 'gurobi' else pyo.SolverFactory('appsi_highs')
    try:
        if not solver.available(exception_flag=False):
            return {'status': 'unavailable', 'error': 'Solver is not installed or its license is unavailable.'}
        solver.options['TimeLimit' if engine == 'gurobi' else 'time_limit'] = request['seconds']
        solver.options['Threads' if engine == 'gurobi' else 'threads'] = 1
        solver.options['MIPGap' if engine == 'gurobi' else 'mip_rel_gap'] = 0
        print('LLM4OR_SOLVER_INVOKED=' + engine, flush=True)
        results = solver.solve(model, tee=True, load_solutions=False)
        termination = str(results.solver.termination_condition)
        status = {'optimal': 'optimal', 'infeasible': 'infeasible', 'unbounded': 'unbounded', 'infeasibleOrUnbounded': 'infeasible_or_unbounded', 'maxTimeLimit': 'time_limit'}.get(termination, 'unknown')
        values, objective = None, None
        if len(results.solution):
            model.solutions.load_from(results)
            values = {name: finite(model.x[name].value) for name in model.x}
            objective = finite(pyo.value(model.objective, exception=False))
        result = {'status': status, 'termination': termination, 'objective': objective, 'values': values,
                'bound': finite(results.problem.upper_bound if data['sense'] == 'maximize' else results.problem.lower_bound),
                'versions': {name: importlib.metadata.version(name) for name in ['pyomo', 'gurobipy' if engine == 'gurobi' else 'highspy']}}
        if evidence is not None:
            allowance = max(0, min(2, int(request.get('auxiliarySolveAllowance', 0))))
            try:
                postsolve(evidence, model, data, result, solver, allowance, request.get('perturb', False))
            except Exception as error:
                evidence['diagnostic_error'] = str(error)[:500]
            result['programmaticEvidence'] = evidence
        return result
    finally:
        if engine == 'gurobi':
            solver.close()


if __name__ == '__main__':
    started = time.monotonic()
    try:
        result = solve(json.loads(sys.stdin.read()))
    except Exception as error:
        result = {'status': 'error', 'error': str(error)[:3000]}
    result['solverElapsedMs'] = round((time.monotonic() - started) * 1000)
    emit(result)
