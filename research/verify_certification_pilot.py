"""Independent exact audit of the saved two-parameter development pilot.

Uses only the Python standard library. It does not import the certificate,
point estimator, benchmark runner, or a numerical solver. Feasible decisions
are enumerated anew; the parameter polygon is intersected with every exact
historical halfspace. All costs use Fraction(str(input_number)).

Usage:
    resources/runtime/python/python.exe research/verify_certification_pilot.py

The default report is outputs/certification-20261020/independent-verification.json.
Any missing case or failed check produces a report and a nonzero exit status.
This verifies the saved finite development cases, not statistical coverage.
"""
import argparse
import hashlib
import itertools
import json
import math
import sys
from collections import Counter
from fractions import Fraction as F
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIRECTORY = ROOT / "outputs" / "certification-20261020"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def q(value):
    require(not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value), "Expected finite numeric input")
    return F(str(value))


def binary_float(value):
    require(not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value), "Expected finite serialized bound")
    return F.from_float(float(value))


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def product_cost(terms, decision):
    return sum((q(value) * decision[name] for name, value in terms.items()), F(0))


def cost(sample, decision, theta):
    value = product_cost(sample["model"]["objective"], decision)
    for name, weight in theta.items():
        feature = sample["features"][name]
        term = product_cost(feature["terms"], decision)
        if feature.get("kind") == "soft":
            term -= q(feature["rhs"])
            if feature["sense"] == ">=":
                term = -term
            term = max(F(0), term)
        value += weight * term
    return value


def actions(sample):
    """Complete integer enumeration, independently checking every original row."""
    variables = sample["model"]["variables"]
    domains = []
    for var in variables:
        require(var["type"] in ("integer", "binary"), "Unsupported continuous input")
        lo, hi = var.get("lower"), var.get("upper")
        if var["type"] == "binary":
            lo = max(0, 0 if lo is None else lo)
            hi = min(1, 1 if hi is None else hi)
        require(lo is not None and hi is not None, "Unbounded integer input")
        domains.append(range(math.ceil(q(lo)), math.floor(q(hi)) + 1))
    result = []
    for values in itertools.product(*domains):
        decision = dict(zip([v["name"] for v in variables], values))
        feasible = True
        for row in sample["model"]["constraints"]:
            lhs, rhs = product_cost(row["terms"], decision), q(row["rhs"])
            if not {"<=": lhs <= rhs, ">=": lhs >= rhs, "=": lhs == rhs}[row["sense"]]:
                feasible = False
                break
        if feasible:
            result.append(decision)
    require(bool(result), "Empty decision domain")
    return result


def clip(polygon, a, b, c):
    """Exact clipping by a*x+b*y<=c, retaining segment and singleton cases."""
    if not polygon:
        return []
    output = []
    for start, end in zip(polygon, polygon[1:] + polygon[:1]):
        first = a * start[0] + b * start[1] - c
        second = a * end[0] + b * end[1] - c
        if first <= 0:
            output.append(start)
        if (first < 0 < second) or (second < 0 < first):
            amount = first / (first - second)
            output.append(tuple(
                x + amount * (y - x) for x, y in zip(start, end)
            ))
        elif first > 0 and second == 0:
            output.append(end)
    unique = []
    for vertex in output:
        if vertex not in unique:
            unique.append(vertex)
    return unique


def verify_case(data, saved, record):
    hypotheses = data["hypotheses"]
    require(len(hypotheses) == 2, "This independent verifier requires two parameters")
    names = [h["id"] for h in hypotheses]
    bounds = [(q(h.get("lower", 0)), q(h.get("upper", 20))) for h in hypotheses]
    polygon = [
        (bounds[0][0], bounds[1][0]), (bounds[0][1], bounds[1][0]),
        (bounds[0][1], bounds[1][1]), (bounds[0][0], bounds[1][1]),
    ]
    zero = {name: F(0) for name in names}
    first_unit = {names[0]: F(1), names[1]: F(0)}
    second_unit = {names[0]: F(0), names[1]: F(1)}
    noise = data["certification"]["noise"]
    require(noise["kind"] == "absolute", "Unexpected noise contract")
    historical_rows, action_counts = [], []
    for sample in data["samples"]:
        delta = q(noise["budgets"][sample["id"]]
                  if "budgets" in noise else noise["budget"])
        feasible = actions(sample)
        observed = sample["decision"]
        require(observed in feasible, "Infeasible observed decision")
        action_counts.append(len(feasible))
        for opponent in feasible:
            constant = cost(sample, observed, zero) - cost(sample, opponent, zero)
            a = cost(sample, observed, first_unit) - cost(sample, opponent, first_unit) - constant
            b = cost(sample, observed, second_unit) - cost(sample, opponent, second_unit) - constant
            c = delta - constant
            historical_rows.append((a, b, c))
            polygon = clip(polygon, a, b, c)
    require(bool(polygon), "Unexpected empty independent compatibility polygon")
    require(saved["historyActionCounts"] == action_counts, "History action-count mismatch")

    witnesses = []
    for serialized in saved["witnesses"]:
        witness = tuple(F(serialized[name]) for name in names)
        require(all(lo <= value <= hi for value, (lo, hi) in zip(witness, bounds)),
                "Witness lies outside the declared parameter box")
        require(all(a * witness[0] + b * witness[1] <= c for a, b, c in historical_rows),
                "Witness violates a complete-history constraint")
        witnesses.append(witness)
    require(bool(witnesses), "Completed pilot case has no verified witness")

    intervals = {interval["id"]: interval for interval in saved["ranges"]}
    require(set(intervals) == set(names), "Missing or unexpected coordinate range")
    for j, name in enumerate(names):
        interval = intervals[name]
        require(binary_float(interval["lower"]) <= min(p[j] for p in polygon),
                "Coordinate lower bound is invalid")
        require(binary_float(interval["upper"]) >= max(p[j] for p in polygon),
                "Coordinate upper bound is invalid")

    deployment = data["deployment"]
    feasible = actions(deployment)
    certificate = saved["decisionCertificate"]
    chosen = certificate["chosenDecision"]
    require(chosen in feasible, "Selected deployment decision is infeasible")
    require(saved["deploymentActionCount"] == len(feasible), "Deployment action-count mismatch")

    def regret(theta):
        parameter = dict(zip(names, theta))
        return cost(deployment, chosen, parameter) - min(
            cost(deployment, opponent, parameter) for opponent in feasible
        )

    worst = max(regret(vertex) for vertex in polygon)
    witness_regret = max(regret(witness) for witness in witnesses)
    require(binary_float(certificate["lowerBound"]) <= witness_regret <= worst,
            "Reported risk lower bound lacks a supporting compatible witness")
    require(worst <= binary_float(certificate["upperBound"]), "Invalid risk upper bound")
    require(worst == F(record["exactWorstRegretRational"]),
            "Saved exact worst-regret value differs from independent oracle")

    comparisons = certificate["comparisons"]
    require(len(comparisons) == len(feasible), "Missing rival comparison")
    rival_keys = set()
    for comparison in comparisons:
        opponent = comparison["rivalDecision"]
        require(opponent in feasible, "Infeasible rival")
        rival_keys.add(tuple(sorted(opponent.items())))

        def difference(theta):
            parameter = dict(zip(names, theta))
            return cost(deployment, chosen, parameter) - cost(deployment, opponent, parameter)

        exact = max(difference(vertex) for vertex in polygon)
        require(exact <= binary_float(comparison["upperBound"]), "Invalid rival upper bound")
        if comparison["lowerBound"] is not None:
            require(binary_float(comparison["lowerBound"]) <=
                    max(difference(witness) for witness in witnesses) <= exact,
                    "Invalid rival witness lower bound")
    require(len(rival_keys) == len(feasible), "Duplicate or omitted rival")

    truth = tuple(q(value) for value in record["truth"])
    require(all(lo <= value <= hi for value, (lo, hi) in zip(truth, bounds)),
            "Simulated truth outside the declared parameter box")
    require(all(a * truth[0] + b * truth[1] <= c for a, b, c in historical_rows),
            "Simulated truth violates the declared noise budget")
    true_regret = regret(truth)
    require(true_regret <= worst, "True regret exceeds independently computed worst regret")
    threshold = q(data["certification"]["threshold"])
    status = certificate["status"]
    if status == "safe":
        require(worst <= threshold, "False safe release")
    elif status == "risk_witness":
        require(witness_regret > threshold, "Risk status lacks a compatible risky witness")
    else:
        require(status == "unresolved", "Unexpected certificate status for a nonempty set")

    return {
        "id": record["id"], "status": "passed",
        "vertices": len(polygon), "verifiedWitnesses": len(witnesses),
        "historyActionCounts": action_counts, "deploymentActionCount": len(feasible),
        "exactWorstRegret": str(worst), "exactTrueRegret": str(true_regret),
        "certificateStatus": status,
    }


def audit(directory):
    result_path = directory / "results.json"
    freeze_path = directory / "protocol-freeze.json"
    records_list = read(result_path)["rows"]
    records = {record["id"]: record for record in records_list}
    require(len(records) == len(records_list), "Duplicate result identifiers")
    protocol = read(freeze_path)["protocol"]
    planned = protocol["independent_instances"] * len(protocol["conditions"])
    require(len(records) == planned, "Saved result count differs from frozen plan")
    inputs = {path.name[:-len("-input.json")]: path
              for path in directory.glob("*-input.json")}
    certificates = {path.name[:-len("-certificate.json")]: path
                    for path in directory.glob("*-certificate.json")}
    require(set(inputs) == set(certificates) == set(records),
            "Input, certificate, and result case inventories differ")
    report = {
        "schema": "independent-certificate-verification.v1",
        "method": "Standard-library exact rational polygon clipping and independent complete decision enumeration",
        "projectImports": 0, "solverCalls": 0, "planned": planned,
        "limitations": "Saved two-parameter finite development cases only; not statistical coverage or generalization evidence.",
        "verifierSha256": digest(Path(__file__)),
        "sourceHashes": {
            "results.json": digest(result_path),
            "protocol-freeze.json": digest(freeze_path),
        },
        "cases": [],
    }
    for name in sorted(inputs):
        input_path, certificate_path = inputs[name], certificates[name]
        report["sourceHashes"][input_path.name] = digest(input_path)
        report["sourceHashes"][certificate_path.name] = digest(certificate_path)
        try:
            row = verify_case(read(input_path), read(certificate_path), records[name])
        except Exception as error:
            row = {"id": name, "status": "failed", "error": str(error)}
        report["cases"].append(row)
    report["checked"] = len(report["cases"])
    report["passed"] = sum(row["status"] == "passed" for row in report["cases"])
    report["failed"] = report["checked"] - report["passed"]
    report["status"] = "passed" if report["failed"] == 0 else "failed"
    report["certificateStatuses"] = dict(Counter(
        row["certificateStatus"] for row in report["cases"] if row["status"] == "passed"
    ))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    directory = arguments.directory.resolve()
    output = arguments.output or directory / "independent-verification.json"
    try:
        report = audit(directory)
    except Exception as error:
        report = {
            "schema": "independent-certificate-verification.v1",
            "status": "failed", "checked": 0, "passed": 0, "failed": 1,
            "error": str(error),
        }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        key: report[key] for key in ["status", "checked", "passed", "failed"]
    }, ensure_ascii=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
