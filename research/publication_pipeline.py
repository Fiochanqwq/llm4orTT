"""Frozen, restart-safe study using the project's internal scientific APIs."""
import argparse
import copy
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "solver"))
sys.path.insert(0, str(ROOT / "research"))

from analyze_followup import analyze_directory
from certificate_methods_v2 import METHODS, run_method_v2
from comparison_cases import make_case, prepare_problem, problem_from_case
from experiment_runtime import (
    exclusive_run, freeze_sources, load_record, read, save, seal_record, sha, utc_now,
)
from run_comparison import normalize_result
from run_followup import case_id, profile
from verify_comparison import prepare_case, verify_prepared
from verify_followup import audit_followup, planned_inventory
from language_call_records import count_language_calls

SOURCES = [
    "research/publication_pipeline.py", "research/experiment_runtime.py",
    "research/comparison_cases.py", "research/certificate_methods.py",
    "research/certificate_methods_v2.py", "research/run_comparison.py",
    "research/run_followup.py", "research/analyze_followup.py",
    "research/verify_comparison.py", "research/verify_followup.py",
    "solver/inverse.py", "solver/inverse_local.py",
    "solver/inverse_certified.py", "solver/inverse_sensitivity.py",
    "server/inverse.mjs", "server/http.mjs", "server/python-runtime.mjs",
    "research/language_call_records.py",
    "scripts/publication-api.mjs", "scripts/publication-study.mjs",
    "package.json", "package-lock.json",
    "examples/inverse/demo.json", "tests/test_experiment_runtime.py",
]
SOURCES = sorted(set(SOURCES) | {
    p.relative_to(ROOT).as_posix() for folder, pattern in (
        ("server", "*.mjs"), ("shared", "*.json"), ("tests", "*.py"),
    ) for p in (ROOT / folder).glob(pattern)
})


def schedules(protocol):
    for key in ("families", "methods", "comparison_seeds", "sensitivity_seeds",
                "comparison_noise", "lp_budgets", "sensitivity_caps"):
        values = protocol[key]
        if not values or len(values) != len(set(values)):
            raise ValueError("Empty or duplicate protocol factor: " + key)
    if not set(protocol["families"]) <= {"menu8", "knapsack7", "assignment3"}:
        raise ValueError("Unsupported family")
    if not set(protocol["methods"]) <= set(METHODS):
        raise ValueError("Unsupported method")
    if protocol["primary_candidate"] not in protocol["methods"] or protocol["primary_comparator"] not in protocol["methods"]:
        raise ValueError("Primary contrast is outside the method schedule")
    if protocol["primary_lp_budget"] not in protocol["lp_budgets"]:
        raise ValueError("Primary budget is outside the schedule")
    if set(protocol["comparison_seeds"]) & set(protocol["sensitivity_seeds"]):
        raise ValueError("Comparison and sensitivity cohorts must be disjoint")
    for key in ("comparison_seeds", "sensitivity_seeds", "lp_budgets"):
        if any(type(v) is not int or v <= 0 for v in protocol[key]):
            raise ValueError("Expected positive integers: " + key)
    for key in ("method_seconds", "sensitivity_endpoint_seconds"):
        if not 0 < protocol[key] <= 60:
            raise ValueError("Invalid bounded compute budget: " + key)
    if any(cap < protocol["sensitivity_nominal_noise"] for cap in protocol["sensitivity_caps"]):
        raise ValueError("Sensitivity cap is below the nominal budget")
    rng = random.Random(protocol["run_order_seed"])
    blocks = [(f, s, n) for f in protocol["families"] for s in protocol["comparison_seeds"]
              for n in protocol["comparison_noise"]]
    rng.shuffle(blocks)
    comparisons = []
    for family, seed, noise in blocks:
        budgets = list(protocol["lp_budgets"])
        rng.shuffle(budgets)
        for budget in budgets:
            methods = list(protocol["methods"])
            rng.shuffle(methods)
            comparisons.extend({"caseId": case_id("comparison", family, seed, noise),
                                "method": method, "budget": budget} for method in methods)
    blocks = [(f, s) for f in protocol["families"] for s in protocol["sensitivity_seeds"]]
    rng.shuffle(blocks)
    profiles = []
    for family, seed in blocks:
        caps = list(protocol["sensitivity_caps"])
        rng.shuffle(caps)
        profiles.extend({"caseId": case_id("sensitivity", family, seed, protocol["sensitivity_actual_noise"]),
                         "cap": cap} for cap in caps)
    result = {"comparisonSchedule": comparisons, "sensitivitySchedule": profiles}
    planned_inventory({"protocol": protocol, **result})
    return result


def execute_record(path, identity, action):
    """Persist an attempt before work. Interrupted attempts become explicit failures."""
    if path.exists():
        record = load_record(path)
        if any(record.get(k) != v for k, v in identity.items()):
            raise ValueError("Recorded outcome identity changed: " + str(path))
        return record
    attempt = Path(str(path) + ".attempt")
    record = {**identity, "executionStatus": "failed"}
    if attempt.exists():
        record.update(error="Interrupted prior attempt; retained without automatic retry",
                      startedUTC=load_record(attempt)["startedUTC"], interrupted=True)
    else:
        seal_record(attempt, {"startedUTC": utc_now(), **identity})
        tick = time.monotonic()
        try:
            record.update(action())
            record["executionStatus"] = "complete"
        except Exception as error:
            record["error"] = repr(error)
        record["wallSeconds"] = time.monotonic() - tick
    seal_record(path, record)
    return record


def get_case(out, phase, family, seed, actual, declared):
    identifier = case_id(phase, family, seed, actual)
    path = out / phase / "cases" / (identifier + ".json")
    generated, tables = make_case(family, seed, actual, declared, phase)
    generated["id"] = identifier
    if path.exists():
        case = load_record(path)
        if any(case[k] != generated[k] for k in ("input", "truth", "metadata", "id")):
            raise ValueError("Case regeneration differs from frozen input")
    else:
        attempt = Path(str(path) + ".attempt")
        case = generated
        if attempt.exists():
            load_record(attempt)
            case["preprocessingFailure"] = "Interrupted point-fit attempt; retained without refit"
        else:
            seal_record(attempt, {"startedUTC": utc_now(), "caseId": identifier})
            try:
                prepare_problem(case, tables)
            except Exception as error:
                case["preprocessingFailure"] = repr(error)
        seal_record(path, case)
    return case, tables, sha(path)


def archive_regression_case(out, source):
    """Keep the original case identifier in its filename for independent audits."""
    case = read(source)
    if case.get("id", source.stem) != source.stem:
        raise ValueError("Original regression case identity differs from its filename")
    local_source = out / "regression" / source.name
    if not local_source.exists():
        seal_record(local_source, case)
    if load_record(local_source) != case:
        raise ValueError("Archived regression input differs from its original")
    return local_source


def run_study(out, frozen):
    p = frozen["protocol"]
    descriptors = {
        case_id("comparison", f, s, n): (f, s, n, n)
        for f in p["families"] for s in p["comparison_seeds"] for n in p["comparison_noise"]
    }
    descriptors.update({
        case_id("sensitivity", f, s, p["sensitivity_actual_noise"]):
        (f, s, p["sensitivity_actual_noise"], p["sensitivity_nominal_noise"])
        for f in p["families"] for s in p["sensitivity_seeds"]
    })
    for phase, schedule_name, folder in (
        ("comparison", "comparisonSchedule", "runs"),
        ("sensitivity", "sensitivitySchedule", "profiles"),
    ):
        cached_id, case, tables, case_hash = None, None, None, None
        failed = 0
        for i, entry in enumerate(frozen[schedule_name], 1):
            if entry["caseId"] != cached_id:
                case, tables, case_hash = get_case(out, phase, *descriptors[entry["caseId"]])
                cached_id = entry["caseId"]
            suffix = f"__{entry['method']}__b{entry['budget']}" if phase == "comparison" else f"__cap{entry['cap']}"
            destination = out / phase / folder / (entry["caseId"] + suffix + ".json")

            def action():
                if case.get("preprocessingFailure"):
                    raise RuntimeError(case["preprocessingFailure"])
                if phase == "comparison":
                    problem = problem_from_case(case, tables)
                    result = normalize_result(run_method_v2(
                        problem, entry["method"], entry["budget"], p["method_seconds"]), case)
                    verification = verify_prepared(
                        prepare_case(case["input"], case["chosenDecision"], case["truth"]), result)
                else:
                    result, verification = profile(case, entry["cap"], p)
                return {"result": result, "verification": verification}

            record = execute_record(destination, {**entry, "caseSha256": case_hash}, action)
            failed += record["executionStatus"] != "complete"
            if i % (48 if phase == "comparison" else 9) == 0 or i == len(frozen[schedule_name]):
                progress = {"phase": phase, "completed": i, "planned": len(frozen[schedule_name]),
                            "failed": failed, "updatedUTC": utc_now()}
                save(out / "progress.json", progress)
                print(json.dumps(progress), flush=True)
    regression_path = out / "regression" / "prior-false-safe.json"
    if regression_path.exists():
        load_record(regression_path)
    else:
        sources = list((ROOT / "outputs/comparison-20261020/cases").glob(
            "misspecification-assignment3-s20011-*.json"))
        if len(sources) != 1:
            raise ValueError("Prior counterexample source missing or ambiguous")
        case = read(sources[0])
        local_source = archive_regression_case(out, sources[0])
        case = load_record(local_source)
        result, verification = profile(case, 1, p)
        seal_record(regression_path, {
            "sourcePath": str(local_source), "originalSource": str(sources[0]),
            "originalSourceSha256": sha(sources[0]), "sourceSha256": sha(local_source),
            "countsAsNewIndependentEvidence": False, "case": case, "cap": 1,
            "result": result, "verification": verification,
        })


def audit_and_analyze(out):
    # Every stored digest is checked, including interrupted and failed attempts.
    for digest in out.rglob("*.sha256"):
        if digest.is_relative_to(out / "language"):
            continue  # The language stage has its own request/source freeze.
        load_record(digest.with_suffix(""))
    report = audit_followup(out)
    save(out / "independent-followup-audit.json", report)
    analysis = analyze_directory(out)
    save(out / "study-status.json", {
        "schema": "publication-study-status.v1", "finishedUTC": utc_now(),
        "complete": report["allPassed"] and analysis["comparisonComplete"] and analysis["sensitivityComplete"],
        "promotionGateMet": analysis["primary"]["candidatePromotionGateMet"],
        "publicationReady": False, "newModelCalls": count_language_calls(out)["newModelCalls"],
        "reason": "Synthetic mechanism evidence only; external language evaluation and novelty remain unestablished.",
    })
    return report["allPassed"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--protocol", default="research/publication_protocol.json", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--language-only", action="store_true")
    args = parser.parse_args()
    out = args.out.resolve()
    if not out.is_relative_to((ROOT / "实验").resolve()):
        raise ValueError("Publication study output must stay inside the project experiment archive.")
    if args.language_only:
        calls = count_language_calls(out)
        summary = read(out / "language" / "summary.json")
        if calls != summary["calls"]:
            raise ValueError("Language summary disagrees with actual call records")
        save(out / "study-status.json", {
            "schema": "publication-study-status.v1", "finishedUTC": utc_now(),
            "stage": "language", "complete": summary["completed"] == 60,
            "newModelCalls": calls["newModelCalls"], "callAccounting": calls,
            "summaryPath": "language/summary.json",
        })
        print(json.dumps({"stage": "language", **calls, "completed": summary["completed"]}))
        return 0
    protocol_path = args.protocol.resolve()
    p = read(protocol_path)
    plan = schedules(p)
    with exclusive_run(out):
        frozen = freeze_sources(ROOT, out, protocol_path, p, SOURCES, plan,
                                resume=args.resume or args.audit_only)
        if not args.audit_only:
            run_study(out, frozen)
        return 0 if audit_and_analyze(out) else 1


if __name__ == "__main__":
    raise SystemExit(main())
