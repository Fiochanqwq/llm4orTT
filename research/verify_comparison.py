"""Independent exact audit for saved finite, two-parameter comparisons.

Only Python's standard library is used. This file deliberately imports neither
the method being evaluated nor the previous pilot checker. It reconstructs all
feasible original integer decisions and all historical inequalities from input,
clips the parameter box using Fraction arithmetic, and evaluates every vertex.
The resulting audit is conditional on the supplied numerical model; it cannot
validate the truth of real-world modeling assumptions.

Usage:
    resources/runtime/python/python.exe research/verify_comparison.py OUTPUT

OUTPUT/cases/ID.json holds {input, truth, chosenDecision, metadata}.
OUTPUT/runs/*.json holds {caseId, method, budget, result}; failed runs are kept.
The CLI writes independent-verification.json and exits nonzero on audit failure
or an original method failure. An embedded previous verification is never used.
"""
import argparse
import hashlib
import itertools
import json
import math
from fractions import Fraction
from pathlib import Path


Q = Fraction


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value):
    """The input contract interprets JSON numbers by their decimal spelling."""
    require(not isinstance(value, bool) and isinstance(value, (int, float)),
            "Input coefficients must be numeric")
    require(math.isfinite(value), "Input coefficients must be finite")
    return Q(str(value))


def rational_record(value):
    """Witnesses/truth may retain exact rationals as strings."""
    if isinstance(value, str):
        try:
            return Q(value)
        except (ValueError, ZeroDivisionError) as error:
            raise ValueError("Invalid rational record") from error
    return number(value)


def serialized_bound(value):
    """Audit the actual stored binary float, not a favorable decimal rounding."""
    require(not isinstance(value, bool) and isinstance(value, (int, float)),
            "Reported bound must be numeric")
    require(math.isfinite(value), "Reported bound must be finite")
    return Q(value) if isinstance(value, int) else Q.from_float(value)


def linear_value(terms, decision):
    require(isinstance(terms, dict), "Terms must be an object")
    require(set(terms) <= set(decision), "Unknown variable in a model expression")
    return sum((number(value) * decision[name] for name, value in terms.items()), Q(0))


def coefficients(sample, decision, identifiers):
    base = linear_value(sample["model"]["objective"], decision)
    require(set(sample["features"]) == set(identifiers), "Feature identifiers do not match")
    features = []
    for identifier in identifiers:
        feature = sample["features"][identifier]
        kind = feature.get("kind", "linear")
        require(kind in ("linear", "soft"), "Unsupported feature kind")
        value = linear_value(feature["terms"], decision)
        if kind == "soft":
            require(feature["sense"] in ("<=", ">="), "Unsupported soft-feature sense")
            value -= number(feature["rhs"])
            if feature["sense"] == ">=":
                value = -value
            value = max(Q(0), value)
        features.append(value)
    return base, tuple(features)


def feasible_actions(sample, identifiers):
    model = sample["model"]
    require(model.get("sense", "minimize") == "minimize", "Only minimization is supported")
    variables = model["variables"]
    names = [variable["name"] for variable in variables]
    require(bool(names) and len(names) == len(set(names)), "Invalid variable identifiers")
    domains = []
    for variable in variables:
        kind = variable["type"]
        require(kind in ("binary", "integer"), "Only bounded integer decisions are supported")
        low, high = variable.get("lower"), variable.get("upper")
        if kind == "binary":
            low = max(Q(0), number(low) if low is not None else Q(0))
            high = min(Q(1), number(high) if high is not None else Q(1))
        else:
            require(low is not None and high is not None, "Integer variables need finite bounds")
            low, high = number(low), number(high)
        domains.append(range(math.ceil(low), math.floor(high) + 1))
    actions = []
    for values in itertools.product(*domains):
        decision = dict(zip(names, values))
        valid = True
        for row in model["constraints"]:
            lhs, rhs = linear_value(row["terms"], decision), number(row["rhs"])
            sense = row["sense"]
            require(sense in ("<=", ">=", "="), "Unsupported original constraint sense")
            if ((sense == "<=" and lhs > rhs) or (sense == ">=" and lhs < rhs)
                    or (sense == "=" and lhs != rhs)):
                valid = False
                break
        if valid:
            actions.append((decision, coefficients(sample, decision, identifiers)))
    require(bool(actions), "Original decision feasible set is empty")
    return actions


def normalize_decision(decision, names):
    require(isinstance(decision, dict) and set(decision) == set(names),
            "Decision has missing or unexpected variables")
    return {name: number(decision[name]) for name in names}


def find_decision(actions, decision, description):
    normalized = normalize_decision(decision, actions[0][0])
    found = next((row for row in actions if row[0] == normalized), None)
    require(found is not None, description + " is infeasible in the original model")
    return found


def deduplicate(points):
    return list(dict.fromkeys(points))


def clip_polygon(vertices, row):
    """Closed half-plane clipping, including exact segments and singletons."""
    a, b, limit = row
    if not vertices:
        return []
    output = []
    previous = vertices[-1]
    previous_gap = a * previous[0] + b * previous[1] - limit
    for current in vertices:
        current_gap = a * current[0] + b * current[1] - limit
        previous_inside, current_inside = previous_gap <= 0, current_gap <= 0
        if previous_inside != current_inside:
            ratio = previous_gap / (previous_gap - current_gap)
            intersection = (
                previous[0] + ratio * (current[0] - previous[0]),
                previous[1] + ratio * (current[1] - previous[1]),
            )
            output.append(intersection)
        if current_inside:
            output.append(current)
        previous, previous_gap = current, current_gap
    return deduplicate(output)


def evaluate(affine, theta):
    constant, features = affine
    return constant + sum((x * y for x, y in zip(features, theta)), Q(0))


def prepare_case(data, chosenDecision, truth=None):
    """Build the complete truth-free oracle once, then reuse it across methods.

    Returned objects contain Fractions and are intentionally internal. `truth`
    is used only for evaluation after all histories and deployment actions are
    reconstructed; it has no role in constructing the compatibility polygon.
    """
    require(data.get("schema") == "contextual-inverse.v1", "Unexpected input schema")
    hypotheses = data["hypotheses"]
    require(len(hypotheses) == 2, "This checker requires exactly two parameters")
    identifiers = [hypothesis["id"] for hypothesis in hypotheses]
    require(len(set(identifiers)) == 2, "Duplicate parameter identifier")
    bounds = [(number(h.get("lower", 0)), number(h.get("upper", 20))) for h in hypotheses]
    require(all(0 <= low <= high for low, high in bounds), "Invalid parameter box")
    vertices = deduplicate([
        (bounds[0][0], bounds[1][0]), (bounds[0][1], bounds[1][0]),
        (bounds[0][1], bounds[1][1]), (bounds[0][0], bounds[1][1]),
    ])
    noise = data["certification"]["noise"]
    require(noise["kind"] == "absolute", "Only declared absolute budgets are supported")
    rows, action_counts = [], []
    require(isinstance(data["samples"], list), "History must be a list")
    ids = [sample["id"] for sample in data["samples"]]
    require(len(ids) == len(set(ids)), "Duplicate historical context identifier")
    for sample in data["samples"]:
        if "budgets" in noise:
            require(sample["id"] in noise["budgets"], "Missing per-history noise budget")
            delta = number(noise["budgets"][sample["id"]])
        else:
            delta = number(noise["budget"])
        require(delta >= 0, "Negative noise budget")
        actions = feasible_actions(sample, identifiers)
        observed = find_decision(actions, sample["decision"], "Observed historical decision")[1]
        action_counts.append(len(actions))
        for _, competitor in actions:
            row = (
                observed[1][0] - competitor[1][0],
                observed[1][1] - competitor[1][1],
                delta - observed[0] + competitor[0],
            )
            rows.append(row)
            vertices = clip_polygon(vertices, row)
    require("deployment" in data, "The comparison requires an explicit deployment context")
    deployment_actions = feasible_actions(data["deployment"], identifiers)
    chosen, chosen_affine = find_decision(deployment_actions, chosenDecision, "Chosen decision")
    prepared = {
        "identifiers": identifiers, "bounds": bounds, "rows": rows, "vertices": vertices,
        "historyActionCounts": action_counts, "deploymentActions": deployment_actions,
        "chosenDecision": chosen, "chosenAffine": chosen_affine,
        "defaultThreshold": data["certification"].get("threshold", 0),
        "truth": None,
    }
    if truth is not None:
        if isinstance(truth, dict):
            require(set(truth) == set(identifiers), "Truth parameter identifiers do not match")
            truth = [truth[name] for name in identifiers]
        require(len(truth) == 2, "Truth dimension mismatch")
        prepared["truth"] = tuple(rational_record(value) for value in truth)
    return prepared


def contains(prepared, theta):
    return (all(low <= value <= high for value, (low, high) in zip(theta, prepared["bounds"]))
            and all(a * theta[0] + b * theta[1] <= limit for a, b, limit in prepared["rows"]))


def regret_at(prepared, theta):
    chosen_cost = evaluate(prepared["chosenAffine"], theta)
    optimum = min(evaluate(affine, theta) for _, affine in prepared["deploymentActions"])
    return chosen_cost - optimum


def verify_prepared(prepared, result):
    """Reject an invalid claim; otherwise return exact, serializable audit data."""
    require(isinstance(result, dict), "Result must be an object")
    supplied_choice = normalize_decision(result["chosenDecision"], prepared["chosenDecision"])
    require(supplied_choice == prepared["chosenDecision"], "Result changed the frozen chosen decision")
    status = result["status"]
    require(status in ("safe", "risk_witness", "unresolved", "incompatible"),
            "Unexpected decision-certificate status")
    if "thresholdRational" in result:
        threshold = rational_record(result["thresholdRational"])
    else:
        threshold = number(result.get("threshold", prepared["defaultThreshold"]))
    require(threshold >= 0, "Negative risk threshold")
    identifiers = prepared["identifiers"]
    witnesses = []
    require(isinstance(result.get("witnesses", []), list), "Witnesses must be a list")
    for record in result.get("witnesses", []):
        require(isinstance(record, dict) and set(record) == set(identifiers),
                "Witness has missing or unexpected parameter identifiers")
        witness = tuple(rational_record(record[name]) for name in identifiers)
        require(contains(prepared, witness), "Witness violates the parameter box or full historical budget")
        witnesses.append(witness)
    vertices = prepared["vertices"]
    empty = not vertices
    lower = result.get("lowerBound")
    upper = result.get("upperBound")
    lower = None if lower is None else serialized_bound(lower)
    upper = None if upper is None else serialized_bound(upper)
    if lower is not None and upper is not None:
        require(lower <= upper, "Reported bounds are reversed")
    worst = max((regret_at(prepared, point) for point in vertices), default=None)
    witnessed = max((regret_at(prepared, point) for point in witnesses), default=None)
    if empty:
        require(status in ("incompatible", "unresolved"), "Empty set cannot justify a safe or risky release")
        require(lower is None, "An empty set has no regret lower-bound witness")
        if status == "incompatible":
            require(upper is None, "Incompatible result must not report a regret upper bound")
    else:
        require(status != "incompatible", "False empty-set claim")
        if lower is not None:
            require(witnessed is not None and lower <= witnessed,
                    "Reported lower bound has no supporting compatible witness")
            require(lower <= worst, "Invalid regret lower bound")
        if upper is not None:
            require(worst <= upper, "Invalid regret upper bound")
        if status == "safe":
            require(bool(witnesses) and upper is not None,
                    "Safe status requires nonempty-set evidence and an upper bound")
            require(worst <= threshold, "False safe release at the declared threshold")
        elif status == "risk_witness":
            require(witnessed is not None and witnessed > threshold,
                    "Risk status has no compatible witness above the declared threshold")
            require(lower is not None, "Risk status is missing its lower bound")
    truth = prepared["truth"]
    truth_contained = None if truth is None else contains(prepared, truth)
    true_regret = None if truth is None else regret_at(prepared, truth)
    maximizer = next((point for point in vertices if regret_at(prepared, point) == worst), None)
    serialize_point = lambda point: dict(zip(identifiers, (str(value) for value in point)))
    return {
        "verified": True,
        "status": status,
        "feasibleSetEmpty": empty,
        "vertices": [serialize_point(point) for point in vertices],
        "vertexCount": len(vertices),
        "exactWorstRegretRational": None if worst is None else str(worst),
        "exactTrueRegretRational": None if true_regret is None else str(true_regret),
        "exactWitnessRegretRational": None if witnessed is None else str(witnessed),
        "worstRegretWitness": None if maximizer is None else serialize_point(maximizer),
        "thresholdRational": str(threshold),
        "truthContained": truth_contained,
        "verifiedWitnesses": len(witnesses),
        "historyActionCounts": prepared["historyActionCounts"],
        "deploymentActionCount": len(prepared["deploymentActions"]),
    }


def verify_one(data, result, truth=None):
    return verify_prepared(prepare_case(data, result["chosenDecision"], truth), result)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def audit_directory(directory):
    """Recompute saved runs independently, preserving failed method records."""
    cases, prepared, reports = {}, {}, []
    for path in sorted((directory / "cases").glob("*.json")):
        cases[path.stem] = read_json(path)
    run_paths = sorted((directory / "runs").glob("*.json"))
    require(bool(cases), "No saved cases found")
    require(bool(run_paths), "No saved runs found")
    original_failures = 0
    for path in run_paths:
        saved = read_json(path)
        report = {"file": str(path.relative_to(directory)), "caseId": saved.get("caseId"),
                  "method": saved.get("method"), "budget": saved.get("budget")}
        if "result" not in saved or saved["result"] is None:
            original_failures += 1
            report.update(status="method_failed", error=saved.get("error", "Missing result"))
            reports.append(report)
            continue
        try:
            identifier = saved["caseId"]
            require(identifier in cases, "Saved run has no matching raw input")
            case = cases[identifier]
            choice = case.get("chosenDecision", saved["result"]["chosenDecision"])
            if identifier not in prepared:
                prepared[identifier] = prepare_case(case["input"], choice, case.get("truth"))
            report.update(status="passed", verification=verify_prepared(prepared[identifier], saved["result"]))
        except (ValueError, KeyError, TypeError, ArithmeticError) as error:
            report.update(status="failed", error=str(error))
        reports.append(report)
    failed = sum(report["status"] == "failed" for report in reports)
    return {
        "schema": "independent-comparison-audit.v1",
        "checkerSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "cases": len(cases), "runs": len(reports),
        "passed": sum(report["status"] == "passed" for report in reports),
        "failed": failed, "methodFailures": original_failures,
        "allPassed": failed == 0 and original_failures == 0,
        "arithmetic": "Exact rational clipping and exhaustive original decision enumeration",
        "reports": reports,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = audit_directory(arguments.directory)
    output = arguments.output or arguments.directory / "independent-verification.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "reports"},
                     ensure_ascii=False, allow_nan=False))
    return 0 if report["allPassed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
