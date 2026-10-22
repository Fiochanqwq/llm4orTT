"""LP set comparison in dimensions 1..6, with rationally checked certificates.

HiGHS only proposes solutions. No tolerance participates in a proof verdict.
Failed reconstruction raises Unresolved rather than declaring equivalence.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction as F
from functools import lru_cache
from itertools import combinations, islice
import math

import highspy as hs


class Unresolved(RuntimeError):
    pass


def rational(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, F)):
        raise ValueError("Expected a rational coefficient")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Nonfinite coefficient")
    if isinstance(value, str) and len(value) > 128:
        raise ValueError("Oversized coefficient")
    q = F(str(value))
    if max(abs(q.numerator).bit_length(), q.denominator.bit_length()) > 128:
        raise ValueError("Coefficient bit limit exceeded")
    return q


def dot(a, b):
    return sum((x*y for x, y in zip(a, b)), F(0))


def normalize(a, b):
    scale = sum(map(abs, a)) or abs(b) or F(1)
    return tuple(v/scale for v in a), b/scale


@dataclass(frozen=True)
class LP:
    sense: str
    objective: tuple
    rows: tuple


def compile_model(ir):
    if not isinstance(ir, dict) or set(ir) != {"sense", "objective", "constraints"}:
        raise ValueError("Model must contain exactly sense/objective/constraints")
    if ir["sense"] not in ("min", "max") or not isinstance(ir["objective"], (list, tuple)):
        raise ValueError("Invalid direction or objective")
    objective = tuple(map(rational, ir["objective"]))
    n = len(objective)
    if not 1 <= n <= 6:
        raise ValueError("Supported dimension is 1..6")
    constraints = ir["constraints"]
    if not isinstance(constraints, list) or len(constraints) > 32:
        raise ValueError("At most 32 explicit constraints are supported")
    rows = [(tuple(F(-int(i == j)) for j in range(n)), F(0)) for i in range(n)]
    for row in constraints:
        if not isinstance(row, dict) or set(row) != {"a", "op", "b"}:
            raise ValueError("Constraint must contain exactly a/op/b")
        if not isinstance(row["a"], (list, tuple)) or len(row["a"]) != n or row["op"] not in ("<=", ">=", "="):
            raise ValueError("Invalid constraint shape or operator")
        a, b = tuple(map(rational, row["a"])), rational(row["b"])
        if row["op"] in ("<=", "="):
            rows.append(normalize(a, b))
        if row["op"] in (">=", "="):
            rows.append(normalize(tuple(-x for x in a), -b))
    return LP(ir["sense"], objective, tuple(sorted(set(rows))))


def linear_solve(a, b, n, full_rank=False):
    """Exact rectangular RREF; reject inconsistency, set free coordinates to zero."""
    matrix = [list(row) + [rhs] for row, rhs in zip(a, b)]
    pivots, k = [], 0
    for col in range(n):
        pivot = next((i for i in range(k, len(matrix)) if matrix[i][col]), None)
        if pivot is None:
            continue
        matrix[k], matrix[pivot] = matrix[pivot], matrix[k]
        divisor = matrix[k][col]
        matrix[k] = [v/divisor for v in matrix[k]]
        for i in range(len(matrix)):
            if i != k and matrix[i][col]:
                factor = matrix[i][col]
                matrix[i] = [v-factor*w for v, w in zip(matrix[i], matrix[k])]
        pivots.append(col)
        k += 1
    if any(not any(row[:n]) and row[n] for row in matrix) or (full_rank and k != n):
        return None
    result = [F(0)]*n
    for i, col in enumerate(pivots):
        result[col] = matrix[i][n]
    return tuple(result)


def inside(rows, point):
    return point is not None and all(dot(a, point) <= b for a, b in rows)


def check_certificate(rows, objective, certificate):
    """Verify primal, dual, complementary slackness, rays or Farkas exactly."""
    n = len(objective)
    status = certificate["status"]
    if status == "infeasible":
        y = certificate["multipliers"]
        return (len(y) == len(rows) and all(v >= 0 for v in y)
                and all(sum((y[i]*a[j] for i, (a, _) in enumerate(rows)), F(0)) == 0 for j in range(n))
                and sum((y[i]*b for i, (_, b) in enumerate(rows)), F(0)) < 0)
    x = certificate["point"]
    if len(x) != n or not inside(rows, x):
        return False
    if status == "unbounded":
        ray = certificate["ray"]
        return len(ray) == n and all(dot(a, ray) <= 0 for a, _ in rows) and dot(objective, ray) > 0
    if status != "optimal":
        return False
    y = certificate["multipliers"]
    return (len(y) == len(rows) and all(v >= 0 for v in y)
            and all(sum((y[i]*a[j] for i, (a, _) in enumerate(rows)), F(0)) == objective[j] for j in range(n))
            and all(y[i]*(b-dot(a, x)) == 0 for i, (a, b) in enumerate(rows))
            and dot(objective, x) == sum((y[i]*b for i, (_, b) in enumerate(rows)), F(0)) == certificate["value"])


def numeric_solver(rows, objective):
    solver = hs.Highs()
    for key, value in {"output_flag": False, "threads": 1, "solver": "simplex", "presolve": "off",
                       "time_limit": 10.0, "primal_feasibility_tolerance": 1e-9, "dual_feasibility_tolerance": 1e-9}.items():
        if solver.setOptionValue(key, value) != hs.HighsStatus.kOk:
            raise Unresolved("Rejected solver option " + key)
    n = len(objective)
    lp = hs.HighsLp()
    lp.num_col_, lp.num_row_ = n, len(rows)
    lp.col_cost_ = [-float(v) for v in objective]
    lp.col_lower_, lp.col_upper_ = [-hs.kHighsInf]*n, [hs.kHighsInf]*n
    lp.row_lower_, lp.row_upper_ = [-hs.kHighsInf]*len(rows), [float(b) for _, b in rows]
    starts, indices, values = [0], [], []
    for a, _ in rows:
        for j, v in enumerate(a):
            if v:
                indices.append(j)
                values.append(float(v))
        starts.append(len(indices))
    lp.a_matrix_.format_ = hs.MatrixFormat.kRowwise
    lp.a_matrix_.start_, lp.a_matrix_.index_, lp.a_matrix_.value_ = starts, indices, values
    if solver.passModel(lp) != hs.HighsStatus.kOk or solver.run() == hs.HighsStatus.kError:
        raise Unresolved("HiGHS model or run failed")
    return solver


def rational_proposals(values):
    for denominator in (10**6, 10**9, 10**12):
        yield tuple(F(str(float(v))).limit_denominator(denominator) for v in values)


def primal_proposals(rows, values):
    yield from rational_proposals(values)
    n = len(values)
    ranked = sorted(range(len(rows)), key=lambda i: abs(dot(tuple(float(v) for v in rows[i][0]), values) - float(rows[i][1])))
    for indices in islice(combinations(ranked[:min(len(rows), n+10)], n), 4096):
        point = linear_solve([rows[i][0] for i in indices], [rows[i][1] for i in indices], n, True)
        if point is not None:
            yield point


def dual_proposals(rows, objective, values, farkas=False):
    yield from rational_proposals(values)
    support = [i for i, v in enumerate(values) if abs(v) > 1e-12]
    if not support:
        return
    matrix = [[rows[i][0][j] for i in support] for j in range(len(objective))]
    rhs = list(objective)
    if farkas:
        matrix.append([F(1)]*len(support))
        rhs.append(F(1))
    weights = linear_solve(matrix, rhs, len(support))
    if weights is not None:
        answer = [F(0)]*len(rows)
        for i, y in zip(support, weights):
            answer[i] = y
        yield tuple(answer)


def optimal_certificate(rows, objective, solver):
    solution = solver.getSolution()
    duals = list(dual_proposals(rows, objective, [-v for v in solution.row_dual]))
    for point in primal_proposals(rows, solution.col_value):
        if not inside(rows, point):
            continue
        for weights in duals:
            certificate = {"status": "optimal", "point": point, "multipliers": weights, "value": dot(objective, point)}
            if check_certificate(rows, objective, certificate):
                return certificate
    return None


@lru_cache(maxsize=32768)
def support(rows, objective):
    for i, (a, b) in enumerate(rows):
        if not any(a) and b < 0:
            weights = tuple(F(int(j == i)) for j in range(len(rows)))
            certificate = {"status": "infeasible", "multipliers": weights}
            assert check_certificate(rows, objective, certificate)
            return certificate
    solver = numeric_solver(rows, objective)
    status = solver.getModelStatus()
    if status == hs.HighsModelStatus.kOptimal:
        certificate = optimal_certificate(rows, objective, solver)
        if certificate is not None:
            return certificate
    elif status == hs.HighsModelStatus.kInfeasible:
        _, exists, values = solver.getDualRay()
        if exists:
            for sign in (1, -1):
                for weights in dual_proposals(rows, (F(0),)*len(objective), [sign*v for v in values], True):
                    certificate = {"status": "infeasible", "multipliers": weights}
                    if check_certificate(rows, objective, certificate):
                        return certificate
    elif status == hs.HighsModelStatus.kUnbounded:
        _, exists, values = solver.getPrimalRay()
        zero = (F(0),)*len(objective)
        feasible_solver = numeric_solver(rows, zero)
        feasible = optimal_certificate(rows, zero, feasible_solver) if feasible_solver.getModelStatus() == hs.HighsModelStatus.kOptimal else None
        if exists and feasible is not None:
            for ray in rational_proposals(values):
                certificate = {"status": "unbounded", "point": feasible["point"], "ray": ray}
                if check_certificate(rows, objective, certificate):
                    return certificate
    raise Unresolved("No exact certificate reconstructed for numeric status " + str(status))


def analyze(model):
    direction = F(1) if model.sense == "max" else F(-1)
    result = support(model.rows, tuple(direction*c for c in model.objective))
    return {"status": result["status"], "value": direction*result["value"] if result["status"] == "optimal" else None,
            "certificate": result}


def face_rows(model, analysis):
    if analysis["status"] != "optimal":
        return (((F(0),)*len(model.objective), F(-1)),)
    a, b = model.objective, analysis["value"]
    return tuple(sorted(set(model.rows + (normalize(a, b), normalize(tuple(-v for v in a), -b)))))


def inclusion(source, target, n):
    zero = (F(0),)*n
    feasibility = support(source, zero)
    if feasibility["status"] == "infeasible":
        return {"included": True, "reason": "empty_source", "checks": [{"objective": zero, "certificate": feasibility}]}
    checks = []
    for a, b in target:
        result = support(source, a)
        checks.append({"objective": a, "limit": b, "certificate": result})
        if result["status"] == "unbounded":
            x, ray = result["point"], result["ray"]
            step = max(F(0), (b-dot(a, x))/dot(a, ray)) + 1
            point = tuple(v+step*d for v, d in zip(x, ray))
        elif result["status"] == "optimal" and result["value"] > b:
            point = result["point"]
        else:
            continue
        assert inside(source, point) and dot(a, point) > b
        return {"included": False, "witness": point, "violated_row": (a, b), "checks": checks}
    return {"included": True, "checks": checks}


def serializable(value):
    if isinstance(value, F):
        return str(value)
    if isinstance(value, dict):
        return {k: serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serializable(v) for v in value]
    return value


def compare_models(left_ir, right_ir):
    left, right = compile_model(left_ir), compile_model(right_ir)
    n = len(left.objective)
    if len(right.objective) != n:
        raise ValueError("Dimensions differ")
    la, ra = analyze(left), analyze(right)
    feasible = [inclusion(left.rows, right.rows, n), inclusion(right.rows, left.rows, n)]
    lf, rf = face_rows(left, la), face_rows(right, ra)
    faces = [inclusion(lf, rf, n), inclusion(rf, lf, n)]
    fe, oe = all(v["included"] for v in feasible), all(v["included"] for v in faces)
    return serializable({"feasible_sets_equal": fe, "optimal_faces_equal": oe,
        "statuses_equal": la["status"] == ra["status"], "equivalent": fe and oe and la["status"] == ra["status"],
        "left": la, "right": ra, "feasible_inclusions": feasible, "optimal_face_inclusions": faces})
