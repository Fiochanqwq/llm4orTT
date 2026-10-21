"""Independent audit of the frozen algorithm and noise-sensitivity follow-up.

This module uses the standard library and the previous independent exact
polygon checker. It never imports the new wrapper, v2 method, or runner, and
never trusts their stored verification objects. Conditional mathematical
validity is kept separate from simulated true regret when assumptions fail.
"""
import argparse
import copy
import hashlib
import json
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path

from verify_comparison import (
    audit_directory, contains, evaluate, number, prepare_case, rational_record,
    serialized_bound, verify_prepared,
)


ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def threshold_of(data):
    return number(data["certification"].get("threshold", 0))


def endpoint_audit(data, full_result, chosen, truth, prepared=None):
    """Verify reported evidence; a missing unresolved candidate is not evidence."""
    prepared = prepared or prepare_case(data, chosen, truth)
    certificate = copy.deepcopy(full_result.get("decisionCertificate", {}))
    candidate_reported = bool(certificate.get("chosenDecision"))
    if not candidate_reported:
        require(certificate.get("status", "unresolved") == "unresolved"
                and certificate.get("lowerBound") is None
                and certificate.get("upperBound") is None,
                "Missing candidate accompanies an asserted decision claim")
        certificate["status"] = "unresolved"
        certificate["chosenDecision"] = chosen
    expected_threshold = threshold_of(data)
    for key in ("threshold", "thresholdRational"):
        if key in certificate:
            require(rational_record(certificate[key]) == expected_threshold,
                    "Reported threshold differs from the frozen input")
    certificate["thresholdRational"] = str(expected_threshold)
    certificate["witnesses"] = full_result.get("witnesses", [])
    audit = verify_prepared(prepared, certificate)
    audit["candidateReported"] = candidate_reported
    if "noiseModel" in full_result:
        require(full_result["noiseModel"] == data["certification"]["noise"],
                "Reported endpoint noise model differs from its input")
    # Coordinates are not interchangeable with the joint polygon. Audit every
    # reported coordinate bound without pretending an incomplete list is full.
    seen = set()
    for interval in full_result.get("ranges", []):
        identifier = interval["id"]
        require(identifier in prepared["identifiers"] and identifier not in seen,
                "Unknown or duplicate coordinate interval")
        seen.add(identifier)
        if prepared["vertices"]:
            coordinate = prepared["identifiers"].index(identifier)
            minimum = min(point[coordinate] for point in prepared["vertices"])
            maximum = max(point[coordinate] for point in prepared["vertices"])
            require(serialized_bound(interval["lower"]) <= minimum,
                    "Invalid reported coordinate lower bound")
            require(serialized_bound(interval["upper"]) >= maximum,
                    "Invalid reported coordinate upper bound")
    actual = prepared["truth"]
    chosen_cost = evaluate(prepared["chosenAffine"], actual) if actual is not None else None
    optimum = min(evaluate(affine, actual) for _, affine in prepared["deploymentActions"]) \
        if actual is not None else None
    audit["exactTrueChosenCostRational"] = None if chosen_cost is None else str(chosen_cost)
    audit["exactTrueOptimalCostRational"] = None if optimum is None else str(optimum)
    actual_false_safe = (audit["status"] == "safe" and chosen_cost is not None
                         and chosen_cost - optimum > expected_threshold)
    audit["actualFalseSafe"] = actual_false_safe
    audit["actualFalseSafeIsConditionalMathFailure"] = bool(
        actual_false_safe and audit["truthContained"])
    # A conditional safe certificate with a contained truth must protect it.
    require(not audit["actualFalseSafeIsConditionalMathFailure"],
            "Contained truth exceeds a purportedly safe threshold")
    return prepared, audit


def verify_profile(case, profile, case_path):
    """Reconstruct both endpoints and independently verify the wrapper policy."""
    require(profile.get("executionStatus") == "complete", "Profile execution did not complete")
    require(profile["caseId"] == case_path.stem, "Profile case identifier differs from its case file")
    require(profile.get("caseSha256") == sha(case_path), "Profile case SHA256 mismatch")
    if "id" in case:
        require(case["id"] == case_path.stem, "Case payload identifier differs from filename")
    cap = number(profile["cap"])
    require(cap >= 0, "Negative profile cap")
    data, truth, chosen = case["input"], case.get("truth"), case["chosenDecision"]
    nominal_noise = data["certification"]["noise"]
    require(nominal_noise.get("kind") == "absolute" and "budget" in nominal_noise,
            "This follow-up requires a scalar absolute nominal budget")
    require(number(nominal_noise["budget"]) <= cap, "Profile cap decreases the nominal budget")
    result = profile["result"]
    sensitivity = result["noiseSensitivity"]
    upper_noise = sensitivity["upperNoise"]
    require(upper_noise.get("kind") == "absolute" and "budget" in upper_noise
            and "budgets" not in upper_noise and number(upper_noise["budget"]) == cap,
            "Profile cap differs from the explicitly reported upper noise")
    require(sensitivity.get("schema") == "noise-budget-sensitivity.v1",
            "Unexpected noise sensitivity schema")
    require(sensitivity.get("criticalBudgetEstimated") is False,
            "Two endpoint checks cannot assert an estimated critical budget")
    require(sensitivity.get("budgetUpperBoundValidated") is False,
            "Declared upper noise must not be presented as validated")
    assumptions = result["assumptionAudit"]
    require(assumptions.get("trainingFitValidatesNoiseBudget") is False,
            "Training fit was incorrectly used to validate the noise cap")
    require(assumptions.get("noiseBudget") == "declared_not_independently_verified",
            "Noise cap is not marked as an unverified modeling assumption")
    require(assumptions.get("modelStructure") == "declared_not_independently_verified",
            "Model structure is not marked as an unverified modeling assumption")
    upper_result = sensitivity["upperAnalysis"]
    require(sensitivity.get("upperCertificate") == upper_result.get("decisionCertificate", {}),
            "Displayed upper certificate differs from its retained endpoint result")
    upper_data = copy.deepcopy(data)
    upper_data["certification"].pop("sensitivity", None)
    upper_data["certification"]["noise"] = copy.deepcopy(upper_noise)
    nominal_prepared, nominal_audit = endpoint_audit(data, result, chosen, truth)
    upper_prepared, upper_audit = endpoint_audit(upper_data, upper_result, chosen, truth)
    require(all(contains(upper_prepared, vertex) for vertex in nominal_prepared["vertices"]),
            "Independent endpoint sets fail the declared nesting relation")
    if nominal_prepared["vertices"] and upper_prepared["vertices"]:
        require(Fraction(nominal_audit["exactWorstRegretRational"])
                <= Fraction(upper_audit["exactWorstRegretRational"]),
                "Independent fixed-decision regret is not monotone")
    fixed = nominal_audit["candidateReported"] and upper_audit["candidateReported"]
    require(sensitivity.get("fixedDecisionVerified") is fixed,
            "Reported fixed-decision flag does not match endpoint evidence")
    low_status, high_status = nominal_audit["status"], upper_audit["status"]
    require(sensitivity.get("nominalStatus") == low_status
            and sensitivity.get("upperStatus") == high_status,
            "Endpoint status was hidden or relabeled in the sensitivity summary")
    expected = "unresolved"
    if fixed and high_status == "safe":
        expected = "stable_safe"
    elif fixed and high_status == "risk_witness":
        expected = "sensitive" if low_status == "safe" else "risk_in_envelope"
    elif fixed and high_status == "incompatible":
        expected = "incompatible"
    require(sensitivity.get("status") == expected, "Invalid noise-sensitivity classification")
    require(sensitivity.get("rangeSafe") is (expected == "stable_safe"),
            "Range-safe flag does not match the verified upper-endpoint certificate")
    if sensitivity["rangeSafe"]:
        require(not upper_audit["feasibleSetEmpty"] and upper_audit["verifiedWitnesses"] > 0,
                "Range-safe result has no nonempty upper-set evidence")
    guidance = result["decisionGuidance"]
    expected_guidance = (
        "conditional_safe" if expected == "stable_safe" else
        "risk_witness" if expected in ("sensitive", "risk_in_envelope") else
        "incompatible" if expected == "incompatible" else "unresolved")
    require(guidance.get("status") == expected_guidance,
            "Primary decision guidance does not match sensitivity evidence")
    require(guidance.get("scope") == "declared_upper_budget",
            "Decision guidance hides the upper-budget scope")
    require(guidance.get("chosenDecision") == result.get("decisionCertificate", {}).get("chosenDecision"),
            "Decision guidance changed its chosen decision")
    return {
        "capRational": str(cap), "sensitivityStatus": expected,
        "guidanceStatus": expected_guidance, "rangeSafe": expected == "stable_safe",
        "nominal": nominal_audit, "upper": upper_audit,
        "actualFalseSafeIsMathFailure": False,
        "interpretation": "Truth outside the declared set is an assumption failure, not automatically invalid certificate arithmetic.",
    }


def sensitivity_audit(directory):
    cases, profiles, reports, errors = {}, [], [], []
    for path in sorted((directory / "cases").glob("*.json")):
        try:
            cases[path.stem] = (path, read(path))
        except (OSError, ValueError, TypeError) as error:
            errors.append({"file": str(path), "error": str(error)})
    seen = set()
    for path in sorted((directory / "profiles").glob("*.json")):
        entry = {"file": str(path.relative_to(directory)), "status": "failed"}
        try:
            profile = read(path)
            entry.update(caseId=profile.get("caseId"), cap=profile.get("cap"))
            require(profile.get("caseId") in cases, "Profile has no matching saved case")
            key = (profile["caseId"], str(number(profile["cap"])))
            require(key not in seen, "Duplicate case-cap profile")
            seen.add(key)
            case_path, case = cases[profile["caseId"]]
            entry["verification"] = verify_profile(case, profile, case_path)
            entry["status"] = "passed"
            profiles.append(profile)
        except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as error:
            entry["error"] = str(error)
        reports.append(entry)
    if not cases:
        errors.append({"error": "No sensitivity cases found"})
    if not reports:
        errors.append({"error": "No sensitivity profiles found"})
    summary = Counter()
    by_cap = defaultdict(Counter)
    for report in reports:
        if report["status"] != "passed":
            continue
        audit = report["verification"]
        metrics = {
            "profiles": 1,
            "rangeSafe": int(audit["rangeSafe"]),
            "nominalActualFalseSafe": int(audit["nominal"]["actualFalseSafe"]),
            "upperActualFalseSafe": int(audit["upper"]["actualFalseSafe"]),
            "nominalTruthExcluded": int(audit["nominal"]["truthContained"] is False),
            "upperTruthExcluded": int(audit["upper"]["truthContained"] is False),
            "nominalEmpty": int(audit["nominal"]["feasibleSetEmpty"]),
            "upperEmpty": int(audit["upper"]["feasibleSetEmpty"]),
            audit["sensitivityStatus"]: 1,
        }
        summary.update(metrics)
        by_cap[audit["capRational"]].update(metrics)
    failed = sum(report["status"] != "passed" for report in reports)
    return {
        "cases": len(cases), "profiles": len(reports), "passed": len(reports) - failed,
        "failed": failed, "errors": errors, "allPassed": not failed and not errors,
        "summary": dict(summary),
        "byCap": {key: dict(value) for key, value in sorted(by_cap.items(), key=lambda item: Fraction(item[0]))},
        "reports": reports,
    }


def comparison_audit(directory):
    """Use the old independent oracle and add file/protocol identity checks."""
    report = audit_directory(directory)
    associations, seen = [], set()
    for path in sorted((directory / "runs").glob("*.json")):
        entry = {"file": str(path.relative_to(directory)), "status": "failed"}
        try:
            saved = read(path)
            case_id = saved["caseId"]
            case_path = directory / "cases" / (case_id + ".json")
            require(case_path.is_file(), "No saved case for comparison run")
            require(saved.get("caseSha256") == sha(case_path), "Comparison case SHA256 mismatch")
            require(saved.get("executionStatus") == "complete", "Comparison method execution failed")
            key = (case_id, saved["method"], saved["budget"])
            require(key not in seen, "Duplicate comparison method run")
            seen.add(key)
            expected = threshold_of(read(case_path)["input"])
            result = saved["result"]
            for name in ("threshold", "thresholdRational", "thresholdExact"):
                if name in result:
                    require(rational_record(result[name]) == expected,
                            "Comparison threshold differs from frozen input")
            resources = result.get("resources", {})
            if "lpCalls" in resources:
                require(resources["lpCalls"] <= saved["budget"], "Comparison exceeded the LP-call budget")
            entry.update(status="passed", caseId=case_id, method=saved["method"], budget=saved["budget"])
        except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as error:
            entry["error"] = str(error)
        associations.append(entry)
    failed = sum(entry["status"] != "passed" for entry in associations)
    report.update(associationFailures=failed, associations=associations,
                  allPassed=report["allPassed"] and not failed)
    return report


def planned_inventory(freeze):
    """Reconstruct planned keys from the protocol and check saved schedules."""
    protocol = freeze.get("protocol", {})
    comparison = freeze.get("comparisonSchedule", freeze.get("schedule", []))
    sensitivity = freeze.get("sensitivitySchedule", freeze.get("profileSchedule", []))
    expected_comparison = set()
    expected_sensitivity = set()
    if isinstance(comparison, list):
        for item in comparison:
            if isinstance(item, dict) and {"caseId", "method", "budget"} <= set(item):
                expected_comparison.add((item["caseId"], item["method"], item["budget"]))
    if isinstance(sensitivity, list):
        for item in sensitivity:
            if isinstance(item, dict) and {"caseId", "cap"} <= set(item):
                expected_sensitivity.add((item["caseId"], str(number(item["cap"]))))
    require(len(expected_comparison) == len(comparison), "Malformed or duplicate comparison schedule")
    require(len(expected_sensitivity) == len(sensitivity), "Malformed or duplicate sensitivity schedule")
    derived_comparison = {
        (f"comparison-{family}-s{seed}-n{noise}", method, budget)
        for family in protocol["families"]
        for seed in protocol["comparison_seeds"]
        for noise in protocol["comparison_noise"]
        for method in protocol["methods"]
        for budget in protocol["lp_budgets"]
    }
    derived_sensitivity = {
        (f"sensitivity-{family}-s{seed}-n{protocol['sensitivity_actual_noise']}",
         str(number(cap)))
        for family in protocol["families"]
        for seed in protocol["sensitivity_seeds"]
        for cap in protocol["sensitivity_caps"]
    }
    require(expected_comparison == derived_comparison,
            "Saved comparison schedule does not equal protocol-derived schedule")
    require(expected_sensitivity == derived_sensitivity,
            "Saved sensitivity schedule does not equal protocol-derived schedule")
    require(len(derived_comparison) == protocol["planned_comparison_runs"],
            "Declared comparison count differs from the protocol factors")
    require(len(derived_sensitivity) == protocol["planned_sensitivity_profiles"],
            "Declared sensitivity count differs from the protocol factors")
    require(2 * len(derived_sensitivity) == protocol["planned_sensitivity_endpoint_checks"],
            "Declared endpoint count differs from the profile schedule")
    return protocol, expected_comparison, expected_sensitivity


def completeness_audit(root, freeze):
    """Never let deleted/missing/duplicated outcomes disappear from the audit."""
    protocol, expected_comparison, expected_sensitivity = planned_inventory(freeze)
    observed_comparison, observed_sensitivity = set(), set()
    for path in sorted((root / "comparison" / "runs").glob("*.json")):
        saved = read(path)
        observed_comparison.add((saved["caseId"], saved["method"], saved["budget"]))
    for path in sorted((root / "sensitivity" / "profiles").glob("*.json")):
        saved = read(path)
        observed_sensitivity.add((saved["caseId"], str(number(saved["cap"]))))
    errors = []
    if not expected_comparison:
        errors.append("Frozen expected comparison schedule is unavailable")
    if not expected_sensitivity:
        errors.append("Frozen expected sensitivity schedule is unavailable")
    missing_comparison = sorted(expected_comparison - observed_comparison)
    extra_comparison = sorted(observed_comparison - expected_comparison)
    missing_sensitivity = sorted(expected_sensitivity - observed_sensitivity)
    extra_sensitivity = sorted(observed_sensitivity - expected_sensitivity)
    expected_comparison_cases = {item[0] for item in expected_comparison}
    expected_sensitivity_cases = {item[0] for item in expected_sensitivity}
    comparison_cases = {path.stem for path in (root / "comparison" / "cases").glob("*.json")}
    sensitivity_cases = {path.stem for path in (root / "sensitivity" / "cases").glob("*.json")}
    require(len(expected_comparison_cases) == protocol["planned_comparison_cases"],
            "Declared comparison-case count differs from protocol factors")
    require(len(expected_sensitivity_cases) == protocol["planned_sensitivity_cases"],
            "Declared sensitivity-case count differs from protocol factors")
    missing_cases = {
        "comparison": sorted(expected_comparison_cases - comparison_cases),
        "sensitivity": sorted(expected_sensitivity_cases - sensitivity_cases),
    }
    extra_cases = {
        "comparison": sorted(comparison_cases - expected_comparison_cases),
        "sensitivity": sorted(sensitivity_cases - expected_sensitivity_cases),
    }
    return {
        "expectedComparisonRuns": len(expected_comparison),
        "observedComparisonRuns": len(observed_comparison),
        "expectedSensitivityProfiles": len(expected_sensitivity),
        "observedSensitivityProfiles": len(observed_sensitivity),
        "missingComparisonRuns": missing_comparison, "extraComparisonRuns": extra_comparison,
        "missingSensitivityProfiles": missing_sensitivity, "extraSensitivityProfiles": extra_sensitivity,
        "missingCases": missing_cases, "extraCases": extra_cases,
        "errors": errors,
        "allPassed": not any((errors, missing_comparison, extra_comparison,
                              missing_sensitivity, extra_sensitivity,
                              *missing_cases.values(), *extra_cases.values())),
    }


def frozen_source_audit(root, freeze):
    """Verify archived source bytes, without executing or trusting those files."""
    reports = []
    hashes = freeze.get("sourceHashes", {})
    require(bool(hashes), "Missing frozen source hashes")
    for name, expected_hash in hashes.items():
        relative = Path(name)
        require(not relative.is_absolute() and ".." not in relative.parts,
                "Frozen source path is not project relative")
        snapshot = root / "frozen-source" / relative
        entry = {"file": name, "expectedSha256": expected_hash, "status": "failed"}
        if snapshot.is_file():
            actual = sha(snapshot)
            entry["snapshotSha256"] = actual
            if actual == expected_hash:
                entry["status"] = "passed"
            else:
                entry["error"] = "Frozen source snapshot hash mismatch"
        else:
            entry["error"] = "Frozen source snapshot missing"
        live = ROOT / relative
        entry["currentWorkspaceMatchesSnapshot"] = live.is_file() and sha(live) == expected_hash
        reports.append(entry)
    protocol_name = Path(freeze.get("protocolPath", "research/followup_protocol.json"))
    require(not protocol_name.is_absolute() and ".." not in protocol_name.parts,
            "Frozen protocol path is not project relative")
    frozen_protocol = root / "frozen-source" / protocol_name
    require(read(frozen_protocol) == freeze["protocol"], "Frozen protocol payloads disagree")
    return {"allPassed": all(entry["status"] == "passed" for entry in reports),
            "files": len(reports), "reports": reports}


def regression_audit(root):
    """Keep the known previous counterexample outside new-sample denominators."""
    path = root / "regression" / "prior-false-safe.json"
    record = read(path)
    require(record.get("countsAsNewIndependentEvidence") is False,
            "Known regression was incorrectly counted as new independent evidence")
    source = Path(record["sourcePath"])
    local_source = root / "regression" / source.name
    if local_source.is_file():
        # Prefer the retained, hash-checked local copy when an archive is moved.
        require(sha(local_source) == record["sourceSha256"],
                "Local regression source SHA256 mismatch")
        source = local_source
    if not source.is_file():
        # Resolve the explicitly relocated project; keep original evidence and hash intact.
        previous_root = Path(r"D:\scr\llm4orTT 0.1")
        try:
            relative = source.relative_to(previous_root)
        except ValueError:
            relative = None
        if relative is not None and ".." not in relative.parts:
            source = ROOT / relative
    require(source.is_file(), "Regression original case source missing")
    require(sha(source) == record["sourceSha256"], "Regression source SHA256 mismatch")
    require(read(source) == record["case"], "Regression case differs from retained original case")
    normalized = {
        "caseId": source.stem, "cap": record["cap"], "caseSha256": record["sourceSha256"],
        "executionStatus": "complete", "result": record["result"],
    }
    audit = verify_profile(record["case"], normalized, source)
    return {"allPassed": True, "countsAsNewIndependentEvidence": False,
            "sourceSha256": record["sourceSha256"], "verification": audit}


def audit_followup(root):
    errors = []
    try:
        freeze = read(root / "freeze.json")
    except (OSError, ValueError, TypeError) as error:
        freeze = {}
        errors.append({"part": "freeze", "error": str(error)})
    parts = {}
    for name, function, argument in (
        ("comparison", comparison_audit, root / "comparison"),
        ("sensitivity", sensitivity_audit, root / "sensitivity"),
    ):
        try:
            parts[name] = function(argument)
        except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as error:
            parts[name] = {"allPassed": False, "error": str(error)}
            errors.append({"part": name, "error": str(error)})
    try:
        completeness = completeness_audit(root, freeze)
    except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as error:
        completeness = {"allPassed": False, "error": str(error)}
    for name, function in (("frozenSources", lambda: frozen_source_audit(root, freeze)),
                           ("regression", lambda: regression_audit(root))):
        try:
            parts[name] = function()
        except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as error:
            parts[name] = {"allPassed": False, "error": str(error)}
            errors.append({"part": name, "error": str(error)})
    return {
        "schema": "independent-followup-audit.v1",
        "checkerSha256": sha(Path(__file__)),
        "polygonCheckerSha256": sha(ROOT / "research" / "verify_comparison.py"),
        "freezeSha256": sha(root / "freeze.json") if (root / "freeze.json").is_file() else None,
        "allPassed": (not errors and completeness["allPassed"]
                      and all(part["allPassed"] for part in parts.values())),
        "errors": errors, "completeness": completeness, **parts,
        "interpretation": (
            "Every conditional claim is independently audited. Actual false-safe "
            "outcomes caused by excluded simulated truth remain visible and are "
            "not relabeled as mathematical certificate failures. The upper cap, "
            "parameter box and model structure remain unvalidated assumptions."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, nargs="?",
                        default=ROOT / "outputs" / "followup-20261020")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = audit_followup(arguments.directory)
    output = arguments.output or arguments.directory / "independent-followup-audit.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({
        "allPassed": report["allPassed"], "output": str(output),
        "comparisonRuns": report["comparison"].get("runs"),
        "comparisonFailures": report["comparison"].get("failed"),
        "sensitivityProfiles": report["sensitivity"].get("profiles"),
        "sensitivityFailures": report["sensitivity"].get("failed"),
        "sensitivitySummary": report["sensitivity"].get("summary"),
        "completeness": report["completeness"],
    }, ensure_ascii=False, allow_nan=False))
    return 0 if report["allPassed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
