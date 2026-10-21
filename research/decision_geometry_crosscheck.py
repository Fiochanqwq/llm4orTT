"""Independent numerical and exact-witness audit of the two-variable geometry.

Uses its own raw-IR conversion and SciPy HiGHS, never geometry internals.
No model-service requests are made. The output is an append-only audit file.
"""
from __future__ import annotations

import os
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

import argparse
from collections import Counter
from copy import deepcopy
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path
import random
import sys

import numpy as np
import scipy
from scipy.optimize import linprog

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
from decision_geometry import analyze_model, compare_models

TOL = 2e-7
SOLVES = 0


def raw_rows(ir):
    """Independent exact conversion; explicit domain is part of the contract."""
    out = [(F(-1), F(0), F(0)), (F(0), F(-1), F(0))]
    for row in ir["constraints"]:
        a, b = map(lambda v: F(str(v)), row["a"])
        c = F(str(row["b"]))
        if row["op"] in ("<=", "="):
            out.append((a, b, c))
        if row["op"] in (">=", "="):
            out.append((-a, -b, -c))
    return out


def solve(rows, objective):
    global SOLVES
    n = len(objective)
    kwargs = {"c": np.array(objective, dtype=float),
              "A_ub": np.array([r[:n] for r in rows], dtype=float) if rows else None,
              "b_ub": np.array([r[n] for r in rows], dtype=float) if rows else None,
              "bounds": [(None, None)] * n, "method": "highs"}
    SOLVES += 1
    result = linprog(**kwargs)
    if result.status not in (0, 2, 3):
        SOLVES += 1
        result = linprog(**kwargs, options={"presolve": False})
    if result.status not in (0, 2, 3):
        raise AssertionError("unresolved numerical oracle: " + result.message)
    return result


def reference(ir):
    rows = raw_rows(ir)
    coeff = [F(str(v)) for v in ir["objective"]]
    sign = 1 if ir["sense"] == "min" else -1
    result = solve(rows, [sign * v for v in coeff])
    status = {0: "optimal", 2: "infeasible", 3: "unbounded"}[result.status]
    value = float(sign * result.fun) if result.status == 0 else None
    return {"status": status, "value": value, "rows": rows, "objective": coeff}


def region(ref, face=False):
    if ref["status"] == "infeasible" or (face and ref["status"] != "optimal"):
        return None
    rows = list(ref["rows"])
    if face:
        a, b = ref["objective"]
        value = ref["value"]
        rows += [(a, b, value), (-a, -b, -value)]
    return rows


def included(source, target):
    if source is None:
        return True
    if target is None:
        return False
    for a, b, limit in target:
        result = solve(source, [-float(a), -float(b)])
        if result.status == 3:
            return False
        if result.status != 0:
            raise AssertionError("oracle unexpectedly empty in inclusion")
        violation = -result.fun - float(limit)
        if violation > TOL * (1 + abs(float(limit))):
            return False
    return True


def order_equal(left, right, ir_left, ir_right):
    if left["status"] == "infeasible":
        return True
    # Search x,y in the common domain with a.(x-y)<=0 but b.(x-y)>0.
    # Interchanging a,b also detects ties that only one objective preserves.
    rows4 = [(a, b, 0, 0, c) for a, b, c in left["rows"]]
    rows4 += [(0, 0, a, b, c) for a, b, c in left["rows"]]
    sa = 1 if ir_left["sense"] == "min" else -1
    sb = 1 if ir_right["sense"] == "min" else -1
    ca = [float(sa * v) for v in left["objective"]]
    cb = [float(sb * v) for v in right["objective"]]
    for first, second in ((ca, cb), (cb, ca)):
        bound = (*first, -first[0], -first[1], 0)
        obj = [-second[0], -second[1], second[0], second[1]]
        result = solve(rows4 + [bound], obj)
        if result.status == 3 or (result.status == 0 and -result.fun > TOL):
            return False
        if result.status != 0:
            raise AssertionError("diagonal x=y must satisfy ordering oracle")
    return True


def make_model(rng, i):
    def q(): return str(F(rng.randint(-7, 7), rng.randint(1, 7)))
    def row(a, op, b): return {"a": list(map(str, a)), "op": op, "b": str(b)}
    kind = i % 8
    rows = []
    if kind in (0, 1, 5):
        for _ in range(rng.randint(0, 7)):
            rows.append(row((q(), q()), rng.choice(("<=", ">=")), q()))
        if kind == 1:
            rows += [row((1, 0), "<=", rng.randint(1, 8)), row((0, 1), "<=", rng.randint(1, 8))]
        if kind == 5:
            k = F(rng.randint(0, 8), rng.randint(1, 7))
            rows += [row((1, 1), ">=", k), row((1, 1), "<=", k + F(1, 97))]
    elif kind == 2:
        rows = [row((1, 1), "=", F(rng.randint(0, 9), rng.randint(1, 7)))]
    elif kind == 3:
        rows = [row((1, 0), "=", q()), row((0, 1), "=", q())]
    elif kind == 4:
        rows = [row((1, -F(rng.randint(0, 5), rng.randint(1, 5))), "=", rng.randint(0, 5))]
    elif kind == 6:
        rows = [row((0, 0), "<=", rng.choice((-1, 0, 1)))]
    else:
        rows = [row((1, 0), ">=", 2), row((1, 0), "<=", 1)]
    objective = [q(), q()] if kind != 6 else ["0", "0"]
    return {"sense": rng.choice(("min", "max")), "objective": objective, "constraints": rows}


def scaled(ir):
    out = deepcopy(ir)
    out["sense"] = "min" if ir["sense"] == "max" else "max"
    out["objective"] = [str(-3 * F(v)) for v in ir["objective"]]
    for row in out["constraints"]:
        row["a"] = [str(5 * F(v)) for v in row["a"]]
        row["b"] = str(5 * F(row["b"]))
    out["constraints"] += [{"a": ["0", "0"], "op": "<=", "b": "1"}]
    return out


def verify_witness(w, models, exact, refs):
    point = tuple(map(F, w["point"]))
    src = w["source"]
    target = w["target"]
    assert all(a * point[0] + b * point[1] <= c for a, b, c in raw_rows(models[src]))
    if w["kind"] == "optimal_face":
        assert refs[src]["status"] == "optimal"
        c = list(map(F, models[src]["objective"]))
        assert c[0] * point[0] + c[1] * point[1] == F(exact[src]["value"])
    row = w["target_row"]
    violation = sum(F(a) * x for a, x in zip(row["a"], point)) - F(row["b"])
    assert violation > 0 and violation == F(w["violation"])
    normalizer = sum(abs(F(a)) for a in row["a"]) or F(1)
    assert violation / normalizer == F(w["normalized_violation"])
    target_member = all(a * point[0] + b * point[1] <= c for a, b, c in raw_rows(models[target]))
    if w["kind"] == "optimal_face":
        if refs[target]["status"] != "optimal":
            target_member = False
        elif target_member:
            c = list(map(F, models[target]["objective"]))
            target_member = c[0] * point[0] + c[1] * point[1] == F(exact[target]["value"])
    assert not target_member
    if w["origin"] == "ray":
        direction = tuple(map(F, w["ray"]))
        step = F(w["ray_step"])
        assert step >= 0
        assert all(a * direction[0] + b * direction[1] <= 0 for a, b, _ in raw_rows(models[src]))
        anchor = tuple(x - step * d for x, d in zip(point, direction))
        assert all(a * anchor[0] + b * anchor[1] <= c for a, b, c in raw_rows(models[src]))
        if w["kind"] == "optimal_face":
            c = list(map(F, models[src]["objective"]))
            assert c[0] * direction[0] + c[1] * direction[1] == 0


def run(count=400, seed=202610214):
    rng = random.Random(seed)
    models = [make_model(rng, i) for i in range(count)]
    refs, exact = [], []
    failures, counts = [], Counter()
    for i, model in enumerate(models):
        try:
            ref, observed = reference(model), analyze_model(model)
            refs.append(ref); exact.append(observed)
            assert ref["status"] == observed["status"], (ref["status"], observed["status"])
            if ref["status"] == "optimal":
                assert abs(float(F(observed["value"])) - ref["value"]) <= TOL * (1 + abs(ref["value"]))
                counts["objective_values_checked"] += 1
            counts["status_" + ref["status"]] += 1
        except Exception as exc:
            failures.append({"stage": "model", "index": i, "error": repr(exc), "model": model})
            # Fail immediately because pair lookup requires validated status/objectives.
            return {"passed": False, "counts": dict(counts), "failures": failures}
    for i, left in enumerate(models):
        if i % 3 == 0:
            right = scaled(left)
        elif i % 3 == 1:
            right = deepcopy(left)
            right["objective"] = [str(F(rng.randint(-5, 5), 3)), str(F(rng.randint(-5, 5), 5))]
        else:
            right = models[(i + 31) % count]
        try:
            lr, rr = refs[i], reference(right)
            comp = compare_models(left, right)
            for face, key in ((False, "feasible_sets_equal"), (True, "optimal_faces_equal")):
                forward = included(region(lr, face), region(rr, face))
                backward = included(region(rr, face), region(lr, face))
                assert comp[key] == (forward and backward), (key, comp[key], forward, backward)
                kind = "optimal_face" if face else "feasibility"
                for source, subset in (("left", forward), ("right", backward)):
                    assert (not subset) == any(w["kind"] == kind and w["source"] == source for w in comp["witnesses"])
                counts["directed_inclusion_checks"] += 2
                counts[key + "_" + str(comp[key]).lower()] += 1
            if comp["feasible_sets_equal"]:
                assert comp["objective_order_equal"] == order_equal(lr, rr, left, right)
                counts["objective_order_checks"] += 1
            assert comp["equivalent"] == (comp["feasible_sets_equal"] and comp["optimal_faces_equal"] and lr["status"] == rr["status"])
            for w in comp["witnesses"]:
                verify_witness(w, {"left": left, "right": right}, comp, {"left": lr, "right": rr})
                counts["finite_witnesses_checked"] += 1
                counts["witness_" + w["kind"] + "_" + w["origin"]] += 1
            counts["model_pairs_checked"] += 1
        except Exception as exc:
            failures.append({"stage": "pair", "index": i, "error": repr(exc), "left": left, "right": right})
    return {"passed": not failures, "seed": seed, "random_models": count, "counts": dict(counts), "failures": failures}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=400)
    parser.add_argument("--output", type=Path, default=ROOT / "实验/决策契约研究_2026-10-21_01/independent-geometry-audit.json")
    args = parser.parse_args()
    report = run(args.count)
    report.update({"oracle": "SciPy HiGHS via independently converted raw inequalities",
                   "scipy_version": scipy.__version__, "tolerance": TOL, "solver_calls": SOLVES,
                   "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__), ROOT / "research/decision_geometry.py")},
                   "scope": "Numerical crosscheck of exact rational geometry plus exact finite-witness substitution; not a proof of universal correctness."})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(report, ensure_ascii=False))
    raise SystemExit(0 if report["passed"] else 1)
