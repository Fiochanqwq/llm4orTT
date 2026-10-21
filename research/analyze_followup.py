"""Frozen paired analysis with all planned outcomes retained."""
import argparse
import csv
import json
import random
import statistics as stats
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def percentile(values, probability):
    values = sorted(values)
    position = (len(values) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def load(path):
    return json.loads(path.read_text("utf-8"))


def valid(run):
    return bool(run and run.get("executionStatus") == "complete"
                and run.get("verification", {}).get("verified"))


def score(run):
    return int(valid(run) and run["result"]["status"] in ("safe", "risk_witness", "incompatible"))


def false_safe(status, audit):
    regret = audit.get("exactTrueRegretRational")
    return bool(status == "safe" and regret is not None and
                Fraction(regret) > Fraction(audit["thresholdRational"]))


def analyze_directory(out):
    out = Path(out)
    frozen = load(out / "freeze.json")
    p = frozen["protocol"]
    runs = {}
    for path in (out / "comparison/runs").glob("*.json"):
        run = load(path)
        key = (run["caseId"], run["method"], run["budget"])
        if key in runs:
            raise ValueError("Duplicate comparison run")
        runs[key] = run
    groups = []
    raw_costs = []
    for budget in p["lp_budgets"]:
        for method in p["methods"]:
            scheduled = [r for r in frozen["comparisonSchedule"] if (r["budget"], r["method"]) == (budget, method)]
            counts = {s: 0 for s in ("safe", "risk_witness", "unresolved", "incompatible", "failed", "missing")}
            times, calls, rows, iterations, accepted = [], [], [], [], []
            invalid_releases = 0
            for entry in scheduled:
                run = runs.get((entry["caseId"], method, budget))
                if run is None:
                    counts["missing"] += 1
                    continue
                if not valid(run):
                    counts["failed"] += 1
                    continue
                result = run["result"]
                counts[result["status"]] += 1
                invalid_releases += false_safe(result["status"], run["verification"])
                resource = result["resources"]
                seconds = resource.get("dispatchElapsedSeconds", resource["elapsedSeconds"])
                times.append(seconds * 1000)
                calls.append(resource["lpCalls"])
                rows.append(resource["cumulativeLpRows"])
                if "simplexIterations" in resource:
                    iterations.append(resource["simplexIterations"])
                    accepted.append(resource["basisAccepted"])
                raw_costs.append({**entry, **resource, "reportedTotalMs": seconds * 1000})
            groups.append({
                "method": method, "budget": budget, "planned": len(scheduled), "counts": counts,
                "resolved": sum(counts[s] for s in ("safe", "risk_witness", "incompatible")),
                "resolvedFraction": sum(counts[s] for s in ("safe", "risk_witness", "incompatible")) / len(scheduled),
                "medianMs": stats.median(times) if times else None,
                "meanLpCalls": stats.mean(calls) if calls else None,
                "meanCumulativeLpRows": stats.mean(rows) if rows else None,
                "simplexIterationObservations": len(iterations),
                "totalSimplexIterations": sum(iterations) if iterations else None,
                "totalBasisAccepted": sum(accepted) if accepted else None,
                "actualFalseSafe": invalid_releases,
            })
    strata, instances = {}, []
    for family in p["families"]:
        values = []
        for seed in p["comparison_seeds"]:
            differences = []
            for noise in p["comparison_noise"]:
                identifier = f"comparison-{family}-s{seed}-n{noise}"
                differences.append(score(runs.get((identifier, p["primary_candidate"], p["primary_lp_budget"]))) -
                                   score(runs.get((identifier, p["primary_comparator"], p["primary_lp_budget"]))))
            value = stats.mean(differences)
            values.append(value)
            instances.append({"family": family, "seed": seed, "difference": value})
        strata[family] = values
    estimate = stats.mean(stats.mean(v) for v in strata.values())
    rng = random.Random(p["analysis"]["bootstrap_seed"])
    draws = [stats.mean(stats.mean(rng.choices(v, k=len(v))) for v in strata.values())
             for _ in range(p["analysis"]["bootstrap_replicates"])]
    interval = [percentile(draws, .025), percentile(draws, .975)]
    scheduled_keys = {(r["caseId"], r["method"], r["budget"]) for r in frozen["comparisonSchedule"]}
    complete = set(runs) == scheduled_keys and all(valid(r) for r in runs.values())
    audit_path = out / "independent-followup-audit.json"
    independent_passed = audit_path.exists() and load(audit_path).get("allPassed") is True
    primary = {"candidate": p["primary_candidate"], "comparator": p["primary_comparator"],
               "budget": p["primary_lp_budget"], "independentInstances": len(instances),
               "pairedDifference": estimate, "exploratory95Interval": interval,
               "candidatePromotionGateMet": complete and independent_passed and estimate >= .10 and interval[0] > 0,
               "instanceDifferences": instances}
    profiles = {}
    for path in (out / "sensitivity/profiles").glob("*.json"):
        row = load(path)
        key = (row["caseId"], row["cap"])
        if key in profiles:
            raise ValueError("Duplicate sensitivity profile")
        profiles[key] = row
    sensitivity = []
    for cap in p["sensitivity_caps"]:
        scheduled = [r for r in frozen["sensitivitySchedule"] if r["cap"] == cap]
        group = {
            "cap": cap, "planned": len(scheduled), "missing": 0, "failed": 0,
            "nominalCounts": {s: 0 for s in ("safe", "risk_witness", "incompatible", "unresolved")},
            "upperCounts": {s: 0 for s in ("safe", "risk_witness", "incompatible", "unresolved")},
            "nominalActualFalseSafe": 0, "upperActualFalseSafe": 0,
            "nominalFalseSafeNotReleasedAtUpper": 0,
            "nominalTruthExcluded": 0, "upperTruthExcluded": 0,
            "nominalSafeNotRangeSafe": 0, "rangeSafe": 0,
        }
        elapsed = []
        for entry in scheduled:
            row = profiles.get((entry["caseId"], cap))
            if row is None:
                group["missing"] += 1
                continue
            checks = row.get("verification", {})
            if (row["executionStatus"] != "complete" or not checks.get("nominal", {}).get("verified")
                    or not checks.get("upper", {}).get("verified")):
                group["failed"] += 1
                continue
            result = row["result"]
            nominal = result["decisionCertificate"]["status"]
            upper = result["noiseSensitivity"]["upperCertificate"]["status"]
            group["nominalCounts"][nominal] += 1
            group["upperCounts"][upper] += 1
            bad_nominal = false_safe(nominal, checks["nominal"])
            bad_upper = false_safe(upper, checks["upper"])
            group["nominalActualFalseSafe"] += bad_nominal
            group["upperActualFalseSafe"] += bad_upper
            group["nominalFalseSafeNotReleasedAtUpper"] += bad_nominal and not result["noiseSensitivity"]["rangeSafe"]
            group["nominalTruthExcluded"] += checks["nominal"]["truthContained"] is False
            group["upperTruthExcluded"] += checks["upper"]["truthContained"] is False
            group["nominalSafeNotRangeSafe"] += nominal == "safe" and not result["noiseSensitivity"]["rangeSafe"]
            group["rangeSafe"] += result["noiseSensitivity"]["rangeSafe"]
            elapsed.append(result["noiseSensitivity"]["resources"]["totalElapsedMs"])
        group["medianTwoEndpointMs"] = stats.median(elapsed) if elapsed else None
        sensitivity.append(group)
    planned_profiles = {(r["caseId"], r["cap"]) for r in frozen["sensitivitySchedule"]}
    sensitivity_complete = (set(profiles) == planned_profiles
                            and all(g["missing"] == g["failed"] == 0 for g in sensitivity))
    result = {
        "schema": "inverse-followup-analysis.v1",
        "independentAuditPassed": independent_passed,
        "comparisonPlanned": len(frozen["comparisonSchedule"]), "comparisonSaved": len(runs),
        "comparisonComplete": complete, "primary": primary, "comparisonGroups": groups,
        "sensitivityPlanned": len(frozen["sensitivitySchedule"]), "sensitivitySaved": len(profiles),
        "sensitivityComplete": sensitivity_complete, "sensitivityGroups": sensitivity,
        "scope": p["limitations"], "inference": p["analysis"],
    }
    (out / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    keys = sorted({key for row in raw_costs for key in row})
    with (out / "comparison-costs.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        writer.writerows(raw_costs)
    print(json.dumps({"comparisonComplete": complete, "sensitivityComplete": sensitivity_complete,
                      "primary": {k: v for k, v in primary.items() if k != "instanceDifferences"},
                      "sensitivityGroups": sensitivity}, ensure_ascii=False))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="outputs/followup-20261020")
    args = parser.parse_args()
    result = analyze_directory(ROOT / args.out)
    return 0 if (result["comparisonComplete"] and result["sensitivityComplete"]
                 and result["independentAuditPassed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
