"""Frozen small mechanism pilot, with a separate exact 2D polygon oracle."""
import hashlib
import itertools
import json
import random
import sys
import time
from fractions import Fraction as F
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "solver"))
from inverse import recover
from inverse_local import profile_bound
from inverse import canonical, fit
from inverse_certified import analyze_compatibility


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), "utf-8")


def fq(x):
    return F(str(x))


def generate(family, seed, noise):
    rng, feedback = random.Random(seed), random.Random(seed + 10000)
    truth = [F(rng.randint(2, 18), 10), F(rng.randint(2, 18), 10)]
    samples, tables = [], []
    for k in range(6):
        names = [f"x{j}" for j in range(6 if family == "six_choice_menu" else 5)]
        base = {n: rng.randint(-15, 15) / 10 for n in names}
        if not any(base.values()):
            base[names[0]] = 1
        features = {f"p{j}": {"kind": "linear", "terms": {n: rng.randint(-3, 4) for n in names}}
                    for j in range(2)}
        weights = {n: rng.randint(1, 5) for n in names}
        row = {"terms": {n: 1 for n in names}, "sense": "=", "rhs": 1} if family == "six_choice_menu" else {
            "terms": weights, "sense": "<=", "rhs": 7}
        actions = []
        for vector in itertools.product((0, 1), repeat=len(names)):
            if family == "six_choice_menu" and sum(vector) != 1:
                continue
            if family == "binary_knapsack" and sum(weights[n] * v for n, v in zip(names, vector)) > 7:
                continue
            b = sum((fq(base[n]) * v for n, v in zip(names, vector)), F(0))
            fs = tuple(sum((fq(features[f"p{j}"]["terms"][n]) * v for n, v in zip(names, vector)), F(0))
                       for j in range(2))
            actions.append({"decision": dict(zip(names, vector)), "b": b, "f": fs})
        true_cost = lambda a: a["b"] + sum(t * f for t, f in zip(truth, a["f"]))
        optimum = min(map(true_cost, actions))
        eligible = [a for a in actions if true_cost(a) - optimum <= fq(noise)]
        observed = feedback.choice(eligible)
        sample = {"id": f"context-{k}", "model": {"sense": "minimize",
                  "variables": [{"name": n, "type": "binary", "lower": 0, "upper": 1} for n in names],
                  "objective": base, "constraints": [row]}, "features": features,
                  "decision": observed["decision"]}
        samples.append(sample)
        tables.append((actions, observed))
    data = {"schema": "contextual-inverse.v1",
            "hypotheses": [{"id": f"p{j}", "label": f"隐藏费用{j + 1}", "lower": 0, "upper": 2} for j in range(2)],
            "samples": samples[:5], "deployment": samples[5], "lambda": 0, "pruneThreshold": 0,
            "maxIterations": 80, "seconds": 5,
            "certification": {"noise": {"kind": "absolute", "budget": noise},
                              "threshold": .25, "maxSeconds": 20, "maxOracleCalls": 200,
                              "maxAssignments": 4096}}
    return data, truth, tables


def oracle_polygon(tables, noise, decision):
    # Independent implementation: all inequalities assembled directly from
    # generator truth-free cost tables, then enumerate every pairwise intersection.
    rows = [((F(1), F(0)), F(2)), ((F(-1), F(0)), F(0)),
            ((F(0), F(1)), F(2)), ((F(0), F(-1)), F(0))]
    for actions, observed in tables[:5]:
        for action in actions:
            a = tuple(v - w for v, w in zip(observed["f"], action["f"]))
            rhs = fq(noise) - observed["b"] + action["b"]
            rows.append((a, rhs))
    vertices = set()
    for (a, b), (c, d) in itertools.combinations(rows, 2):
        determinant = a[0] * c[1] - a[1] * c[0]
        if not determinant:
            continue
        point = ((b * c[1] - a[1] * d) / determinant,
                 (a[0] * d - b * c[0]) / determinant)
        if all(r[0] * point[0] + r[1] * point[1] <= bound for r, bound in rows):
            vertices.add(point)
    if not vertices:
        raise AssertionError("Known simulated truth should make this polytope nonempty")
    actions = tables[5][0]
    chosen = next(a for a in actions if a["decision"] == decision)
    regret = max(chosen["b"] - a["b"] + sum((v - w) * t for v, w, t in zip(chosen["f"], a["f"], p))
                 for p in vertices for a in actions)
    return regret, len(vertices)


def main():
    protocol_path = ROOT / "research" / "certification_protocol.json"
    protocol = json.loads(protocol_path.read_text("utf-8"))
    output = ROOT / "outputs" / "certification-20261020"
    output.mkdir(parents=True, exist_ok=False)
    save(output / "protocol-freeze.json", {"protocol": protocol,
         "sha256": hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
         "runnerSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
         "solverSha256": hashlib.sha256((ROOT / "solver/inverse_certified.py").read_bytes()).hexdigest(),
         "frozenBeforeResults": True})
    rows = []
    for family in protocol["families"]:
        for seed in protocol["seeds_per_family"]:
            for noise in (0, .4):
                identifier = f"{family}-s{seed}-noise{noise}"
                row = {"id": identifier, "family": family, "seed": seed, "noise": noise}
                started = time.monotonic()
                try:
                    data, truth, tables = generate(family, seed, noise)
                    save(output / (identifier + "-input.json"), data)
                    fitted = recover(data)
                    certificate = analyze_compatibility(data, fitted["theta"])
                    save(output / (identifier + "-certificate.json"), certificate)
                    decision = certificate["decisionCertificate"]["chosenDecision"]
                    exact, vertices = oracle_polygon(tables, noise, decision)
                    actions = tables[5][0]
                    cost = lambda a: a["b"] + sum(v * t for v, t in zip(a["f"], truth))
                    chosen = next(a for a in actions if a["decision"] == decision)
                    actual = cost(chosen) - min(map(cost, actions))
                    cert = certificate["decisionCertificate"]
                    lower, upper = cert["lowerBound"], cert["upperBound"]
                    lower_ok = lower is None or F.from_float(lower) <= exact
                    upper_ok = upper is not None and exact <= F.from_float(upper)
                    contained = all(F.from_float(r["lower"]) <= truth[i] <= F.from_float(r["upper"])
                                    for i, r in enumerate(certificate["ranges"]))
                    canonical_samples = [canonical(s, data["hypotheses"]) for s in data["samples"]]
                    unregularized = fit(data, canonical_samples)
                    minimum = sum(r["residual"] for r in unregularized["residuals"]) / len(canonical_samples)
                    old_ranges = []
                    for i, h in enumerate(data["hypotheses"]):
                        lo = profile_bound(data, canonical_samples, h["id"], minimum + 1e-6)
                        hi = profile_bound(data, canonical_samples, h["id"], minimum + 1e-6, True)
                        old_ranges.append({"lower": lo["value"], "upper": hi["value"],
                                           "containsTruth": lo["value"] is not None and hi["value"] is not None
                                           and lo["value"] - 1e-6 <= float(truth[i]) <= hi["value"] + 1e-6})
                    row.update(status="complete", certificateStatus=cert["status"],
                               truth=[float(t) for t in truth], pointTheta=fitted["theta"],
                               trueRegret=float(actual), exactWorstRegret=float(exact),
                               exactWorstRegretRational=str(exact), oracleVertices=vertices,
                               lowerBound=lower, upperBound=upper,
                               validBounds=lower_ok and upper_ok, compatibleRangesContainTruth=contained,
                               falseRelease=cert["status"] == "safe" and actual > F(1, 4),
                               empiricalRanges=old_ranges, resources=certificate["resources"])
                except Exception as error:
                    row.update(status="failed", error=str(error))
                row["elapsedSeconds"] = time.monotonic() - started
                rows.append(row)
                save(output / "results.json", {"rows": rows})
                print(json.dumps({k: row[k] for k in ("id", "status", "certificateStatus", "error") if k in row}), flush=True)
    completed = [r for r in rows if r["status"] == "complete"]
    summary = {"planned": 24, "completed": len(completed), "failed": 24 - len(completed),
               "independentGeneratedInstances": 12, "conditionsPerInstance": 2,
               "certificateStatuses": {s: sum(r["certificateStatus"] == s for r in completed)
                                       for s in ("safe", "risk_witness", "unresolved", "incompatible")},
               "invalidBounds": sum(not r["validBounds"] for r in completed),
               "falseReleases": sum(r["falseRelease"] for r in completed),
               "compatibleRangeExclusions": sum(not r["compatibleRangesContainTruth"] for r in completed),
               "empiricalRangeExclusions": sum(not all(rng["containsTruth"] for rng in r["empiricalRanges"]) for r in completed),
               "interpretation": "Development mechanism checks, not statistical coverage, generalization, or novelty evidence."}
    save(output / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False))
    if summary["failed"] or summary["invalidBounds"] or summary["falseReleases"] or summary["compatibleRangeExclusions"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
