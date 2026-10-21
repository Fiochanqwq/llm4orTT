"""Prespecified paired effect with an instance-level stratified bootstrap."""
import argparse
import json
import random
import statistics as stats
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def percentile(values, p):
    values = sorted(values)
    position = (len(values) - 1) * p
    lo = int(position)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (position - lo)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="outputs/comparison-20261020")
    args = parser.parse_args()
    output = ROOT / args.out
    frozen = json.loads((output / "freeze.json").read_text("utf-8"))
    protocol = frozen["protocol"]
    records = {}
    for path in (output / "runs").glob("*.json"):
        row = json.loads(path.read_text("utf-8"))
        key = (row["caseId"], row["method"], row["budget"])
        if key in records:
            raise RuntimeError("Duplicate run")
        records[key] = row
    cases = {p.stem: json.loads(p.read_text("utf-8")) for p in (output / "cases").glob("*.json")}
    groups = []
    for split in ("development", "evaluation", "misspecification"):
        for budget in protocol["lp_budgets"]:
            for method in protocol["methods"]:
                planned = [p for p in frozen["schedule"] if (p["split"], p["budget"], p["method"]) == (split, budget, method)]
                counts = {s: 0 for s in ("safe", "risk_witness", "unresolved", "incompatible", "failed", "missing")}
                times, calls, truth_outside, actual_false_safe = [], [], 0, 0
                for entry in planned:
                    row = records.get((entry["caseId"], method, budget))
                    if row is None:
                        counts["missing"] += 1
                        continue
                    if row["executionStatus"] != "complete" or not row.get("verification", {}).get("verified"):
                        counts["failed"] += 1
                        continue
                    result, check = row["result"], row["verification"]
                    counts[result["status"]] += 1
                    if check.get("truthContained") is False:
                        truth_outside += 1
                    if check.get("exactTrueRegretRational") is not None and result["status"] == "safe":
                        from fractions import Fraction
                        actual_false_safe += Fraction(check["exactTrueRegretRational"]) > Fraction(result["thresholdRational"])
                    resources = result.get("resources", {})
                    if "elapsedMs" in resources:
                        times.append(resources["elapsedMs"])
                    if "lpCalls" in resources:
                        calls.append(resources["lpCalls"])
                groups.append({"split": split, "method": method, "budget": budget, "planned": len(planned),
                    "counts": counts, "resolved": counts["safe"] + counts["risk_witness"] + counts["incompatible"],
                    "resolvedFraction": (counts["safe"] + counts["risk_witness"] + counts["incompatible"]) / len(planned),
                    "medianElapsedMsCompleted": stats.median(times) if times else None,
                    "meanLPCallsCompleted": stats.mean(calls) if calls else None,
                    "truthOutsideDeclaredSet": truth_outside, "actualFalseSafe": actual_false_safe})
    def score(case_id, method, budget):
        row = records.get((case_id, method, budget))
        return int(row is not None and row.get("executionStatus") == "complete"
                   and row.get("verification", {}).get("verified")
                   and row["result"]["status"] in ("safe", "risk_witness", "incompatible"))
    budget = protocol["primary_lp_budget"]
    candidate, baseline = protocol["primary_candidate"], protocol["primary_comparator"]
    strata, instances = {}, []
    for family in protocol["families"]:
        differences = []
        for seed in protocol["evaluation_seeds"]:
            relevant = [c for c in cases.values() if c["metadata"]["split"] == "evaluation"
                        and c["metadata"]["family"] == family and c["metadata"]["seed"] == seed]
            # Use planned names even when an entire case is missing.
            ids = [f"evaluation-{family}-s{seed}-n{noise}" for noise in protocol["noise_absolute"]]
            difference = stats.mean(score(i, candidate, budget) - score(i, baseline, budget) for i in ids)
            differences.append(difference)
            instances.append({"family": family, "seed": seed, "caseCount": len(relevant),
                              "candidateMinusBaseline": difference})
        strata[family] = differences
    estimate = stats.mean(stats.mean(values) for values in strata.values())
    rng = random.Random(protocol["analysis"]["bootstrap_seed"])
    draws = [stats.mean(stats.mean(rng.choices(values, k=len(values))) for values in strata.values()) for _ in range(10000)]
    lower, upper = percentile(draws, .025), percentile(draws, .975)
    expected = len(frozen["schedule"])
    failed = sum(r["executionStatus"] != "complete" for r in records.values())
    invalid = sum(r["executionStatus"] != "complete" and "result" in r for r in records.values())
    complete = len(records) == expected and failed == 0
    primary = {"candidate": candidate, "baseline": baseline, "budget": budget,
               "independentInstances": len(instances), "pairedResolutionDifference": estimate,
               "exploratory95PercentileBootstrapInterval": [lower, upper],
               "continueRuleMet": bool(complete and estimate >= .10 and lower > 0 and invalid == 0),
               "instanceDifferences": instances}
    answer = {"schema": "certificate-comparison-analysis.v1", "plannedRuns": expected, "savedRuns": len(records),
              "missingRuns": expected - len(records), "failedRuns": failed, "runsFailingValidation": invalid,
              "allPlannedRunsComplete": complete, "primary": primary, "groups": groups,
              "limitations": protocol["analysis"], "scope": protocol["comparison_scope"],
              "interpretation": "Advance candidate only if the prespecified continueRuleMet is true; no novelty or external validity claim."}
    (output / "analysis.json").write_text(json.dumps(answer, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({k: answer[k] for k in ("plannedRuns", "savedRuns", "missingRuns", "failedRuns", "runsFailingValidation")}))
    print(json.dumps({k: v for k, v in primary.items() if k != "instanceDifferences"}))
    if not complete:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
