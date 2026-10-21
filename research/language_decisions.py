"""Truth-free finite inverse fit and exact rational two-endpoint audit."""
import itertools
import sys
from fractions import Fraction as Q
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "solver"))
from inverse import recover


def parse_proposal(raw, catalog):
    if not isinstance(raw, dict) or not isinstance(raw.get("hypotheses"), list):
        raise ValueError("Expected hypotheses array")
    ids = []
    allowed = {h["monitor"]: h["id"] for h in catalog}
    for item in raw["hypotheses"]:
        if not isinstance(item, dict) or set(item) != {"monitor"} or item["monitor"] not in allowed:
            raise ValueError("Unknown structure or invalid hypothesis schema: " + repr(item))
        ids.append(allowed[item["monitor"]])
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate hypothesis id")
    return sorted(ids)


def inverse_input(public, selected):
    samples = []
    for context in public["histories"]:
        names = [a["id"] for a in context["actions"]]
        samples.append({
            "id": context["id"],
            "model": {"sense": "minimize",
                      "variables": [{"name": n, "type": "binary", "lower": 0, "upper": 1} for n in names],
                      "objective": {a["id"]: a["knownCostTenths"] / 10 for a in context["actions"]},
                      "constraints": [{"terms": {n: 1 for n in names}, "sense": "=", "rhs": 1}]},
            "features": {h: {"kind": "linear", "terms": {a["id"]: a["monitors"][h] for a in context["actions"]}}
                         for h in selected},
            "decision": {n: int(n == context["chosen"]) for n in names},
        })
    return {"schema": "contextual-inverse.v1",
            "hypotheses": [{"id": h, "label": h, "lower": 0, "upper": 2} for h in selected],
            "samples": samples, "lambda": 0, "pruneThreshold": 0,
            "tolerance": 1e-7, "maxIterations": 60, "seconds": 5}


def determinant(m):
    n = len(m)
    if n == 1:
        return m[0][0]
    if n == 2:
        return m[0][0] * m[1][1] - m[0][1] * m[1][0]
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


def vertices(rows, dimensions):
    """Integer Cramer's rule; u=10*theta, each inequality A*u <= integer b."""
    rows = sorted(set(rows))
    if dimensions == 0:
        return [((), 1)] if all(b >= 0 for _, b in rows) else []
    result = set()
    for active in itertools.combinations(rows, dimensions):
        matrix = [list(a) for a, _ in active]
        den = determinant(matrix)
        if den == 0:
            continue
        numerators = []
        for j in range(dimensions):
            replaced = [r.copy() for r in matrix]
            for k in range(dimensions):
                replaced[k][j] = active[k][1]
            numerators.append(determinant(replaced))
        if den < 0:
            den, numerators = -den, [-v for v in numerators]
        if all(sum(x * v for x, v in zip(a, numerators)) <= b * den for a, b in rows):
            result.add(tuple(Q(v, den) for v in numerators))
    # Canonical numerator/denominator tuples for all vertices.
    return [(tuple(v.numerator * (d // v.denominator) for v in point), d)
            for point in sorted(result)
            for d in [__import__("math").lcm(*(v.denominator for v in point))]]


def endpoint(public, selected, chosen, cap):
    d = len(selected)
    rows = []
    for j in range(d):
        unit = tuple(int(j == k) for k in range(d))
        rows.extend([(unit, 20), (tuple(-v for v in unit), 0)])
    for context in public["histories"]:
        observed = next(a for a in context["actions"] if a["id"] == context["chosen"])
        for other in context["actions"]:
            rows.append((tuple(observed["monitors"][h] - other["monitors"][h] for h in selected),
                         10 * cap - observed["knownCostTenths"] + other["knownCostTenths"]))
    points = vertices(rows, d)
    if not points:
        return {"status": "incompatible", "cap": cap, "vertices": 0, "worstRegret": None}
    deployment = public["deployment"]
    candidate = next(a for a in deployment["actions"] if a["id"] == chosen)
    worst, witness = Q(0), None
    for nums, den in points:
        for other in deployment["actions"]:
            value = Q((candidate["knownCostTenths"] - other["knownCostTenths"]) * den +
                      sum((candidate["monitors"][h] - other["monitors"][h]) * v
                          for h, v in zip(selected, nums)), 10 * den)
            if value > worst:
                worst = value
                witness = {"theta": {h: str(Q(v, 10 * den)) for h, v in zip(selected, nums)},
                           "alternative": other["id"]}
    return {"status": "safe" if worst <= Q(1, 4) else "risk", "cap": cap,
            "vertices": len(points), "worstRegret": str(worst), "witness": witness}


def decide(public, selected):
    data = inverse_input(public, selected)
    if selected:
        fit = recover(data)
        if fit["status"] != "optimal":
            raise ValueError("Point estimator did not finish optimally")
        theta = fit["theta"]
    else:
        fit = {"status": "optimal", "theta": {}, "method": "zero-hidden-cost",
               "versions": {}, "meanResidual": None}
        theta = {}
    costs = [(Q(a["knownCostTenths"], 10) +
              sum(Q(str(theta[h])) * a["monitors"][h] for h in selected), a["id"])
             for a in public["deployment"]["actions"]]
    chosen = min(costs)[1]  # fixed lexicographic tie break, truth independent
    nominal = endpoint(public, selected, chosen, 0)
    upper = endpoint(public, selected, chosen, 1)
    if upper["status"] == "risk":
        status = "risk"
    elif upper["status"] == "safe" and nominal["status"] != "incompatible":
        status = "safe"
    elif upper["status"] == "incompatible":
        status = "incompatible"
    else:
        status = "unresolved"
    return {"selected": selected, "chosenDecision": chosen, "fit": fit,
            "A0": {"status": "safe", "released": True},
            "A1": {**nominal, "released": nominal["status"] == "safe"},
            "A2": {"status": status, "released": status == "safe",
                   "nominal": nominal, "upper": upper},
            "proposedInput": data}
