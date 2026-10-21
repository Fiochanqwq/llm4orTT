"""Zero-request analysis of frozen, naturally generated public LP outputs.

Reads existing scores and diagnostics; never regrades, changes references, or
mixes random geometry tests / artificial mutations into empirical error rates.
"""
from __future__ import annotations

from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "实验/决策契约研究_2026-10-21_01"
ARMS = ("A", "B", "abstract", "witness")


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def share(num, den):
    return None if not den else num / den


def paired(rows, before, after):
    gains = [r["id"] for r in rows if not r["arms"][before]["success"] and r["arms"][after]["success"]]
    losses = [r["id"] for r in rows if r["arms"][before]["success"] and not r["arms"][after]["success"]]
    d = len(gains) + len(losses)
    p = min(1.0, 2 * sum(math.comb(d, k) for k in range(min(len(gains), len(losses)) + 1)) / 2**d) if d else 1.0
    return {"n": len(rows), "before": before, "after": after,
            "before_correct": sum(r["arms"][before]["success"] for r in rows),
            "after_correct": sum(r["arms"][after]["success"] for r in rows),
            "gains": len(gains), "losses": len(losses), "gain_ids": gains, "loss_ids": losses,
            "difference": share(len(gains) - len(losses), len(rows)),
            "exact_two_sided_p_descriptive": p if rows else None}


def value_equal(left, right):
    if left.get("status") != "optimal" or right.get("status") != "optimal":
        return False
    return Fraction(left["value"]) == Fraction(right["value"])


def analyze_split(split, cases):
    summary = read(OUT / f"{split}-summary.json")
    scores = read(OUT / f"{split}-scores.json")
    diagnostics = {r["id"]: r for r in read(OUT / f"{split}-diagnostics.json")}
    ids = [r["id"] for r in scores]
    expected_ids = [c["id"] for c in cases if c["split"] == split]
    assert len(ids) == len(set(ids)) == summary["n"]
    assert set(ids) == set(expected_ids) == set(diagnostics)
    for arm in ARMS:
        assert summary["scores"][arm] == sum(r["arms"][arm]["success"] for r in scores)
        assert summary["valid"][arm] == sum(r["arms"][arm]["valid"] for r in scores)

    groups = {key: [] for key in ("both_correct", "only_A_correct", "only_B_correct", "both_incorrect")}
    same_wrong, same_wrong_order, both_invalid_or_one, witnesses, no_witnesses = [], [], [], [], []
    parse_failure_ids, valid_pair_ids = [], []
    for row in scores:
        a, b = row["arms"]["A"]["success"], row["arms"]["B"]["success"]
        key = "both_correct" if a and b else "only_A_correct" if a else "only_B_correct" if b else "both_incorrect"
        groups[key].append(row["id"])
        diag = diagnostics[row["id"]]
        (witnesses if diag["witnesses"] else no_witnesses).append(row)
        valid_pair = row["arms"]["A"]["valid"] and row["arms"]["B"]["valid"]
        (valid_pair_ids if valid_pair else parse_failure_ids).append(row["id"])
        if not valid_pair:
            both_invalid_or_one.append(row["id"])
        verdict = diag["verdict"]
        if not a and not b and valid_pair and verdict.get("feasible_sets_equal") and verdict.get("optimal_faces_equal"):
            same_wrong.append(row["id"])
            if verdict.get("objective_order_equal") is True:
                same_wrong_order.append(row["id"])

    blindspots = {}
    wrong_components = {}
    all_error_examples = []
    for arm in ARMS:
        raw_same, same_direction, different_direction, comparable, full_order_fail = [], [], [], [], []
        components = {"invalid": [], "feasible_set_mismatch": [], "optimal_face_mismatch": [],
                      "primary_pass_but_objective_order_mismatch": []}
        for row in scores:
            result = row["arms"][arm]
            if not result["valid"]:
                components["invalid"].append(row["id"])
                continue
            comparison = result["comparison"]
            gold, predicted = comparison["left"], comparison["right"]
            if gold["status"] == predicted["status"] == "optimal":
                comparable.append(row["id"])
            if not comparison["feasible_sets_equal"]:
                components["feasible_set_mismatch"].append(row["id"])
            if not comparison["optimal_faces_equal"]:
                components["optimal_face_mismatch"].append(row["id"])
            if result["success"] and comparison["objective_order_equal"] is False:
                components["primary_pass_but_objective_order_mismatch"].append(row["id"])
            if not result["success"] and value_equal(gold, predicted):
                raw_same.append(row["id"])
                (same_direction if gold["sense"] == predicted["sense"] else different_direction).append(row["id"])
                all_error_examples.append({"id": row["id"], "arm": arm,
                                           "gold_value": gold["value"], "generated_value": predicted["value"],
                                           "gold_sense": gold["sense"], "generated_sense": predicted["sense"],
                                           "feasible_sets_equal": comparison["feasible_sets_equal"],
                                           "optimal_faces_equal": comparison["optimal_faces_equal"]})
        blindspots[arm] = {"finite_optimum_comparable": len(comparable),
                          "raw_equal_value_but_primary_failed": len(raw_same), "raw_equal_ids": raw_same,
                          "same_direction_equal_value_but_primary_failed": len(same_direction),
                          "same_direction_ids": same_direction, "different_direction_ids": different_direction}
        wrong_components[arm] = {k: {"count": len(v), "ids": v} for k, v in components.items()}

    # A/B numerical consensus is a distinct comparison from either candidate vs annotation.
    ab_value_consensus_wrong = []
    for row in scores:
        a, b = row["arms"]["A"], row["arms"]["B"]
        if not (a["valid"] and b["valid"]):
            continue
        pa, pb = a["comparison"]["right"], b["comparison"]["right"]
        if value_equal(pa, pb) and pa["sense"] == pb["sense"] and not (a["success"] and b["success"]):
            ab_value_consensus_wrong.append(row["id"])

    primary_check = paired(scores, "abstract", "witness")
    assert primary_check["gains"] == summary["primary"]["gains"]
    assert primary_check["losses"] == summary["primary"]["losses"]
    assert primary_check["exact_two_sided_p_descriptive"] == summary["primary"]["pExact"]
    return {"n": len(scores), "frozen_summary": summary,
            "initial_pair_outcomes": {k: {"count": len(v), "ids": v} for k, v in groups.items()},
            "valid_initial_pair_count": len(valid_pair_ids), "parse_failure_pair_ids": parse_failure_ids,
            "both_wrong_same_feasible_region_and_optimal_face": {"count": len(same_wrong), "ids": same_wrong,
                "fraction_of_both_wrong": share(len(same_wrong), len(groups["both_incorrect"]))},
            "both_wrong_also_same_objective_order": {"count": len(same_wrong_order), "ids": same_wrong_order},
            "selection_ceiling_with_oracle_choosing_A_or_B": len(scores) - len(groups["both_incorrect"]),
            "same_value_blindspots_vs_annotation": blindspots,
            "same_value_error_examples": all_error_examples,
            "A_B_same_direction_value_consensus_with_at_least_one_primary_failure": {
                "count": len(ab_value_consensus_wrong), "ids": ab_value_consensus_wrong},
            "error_components_overlapping": wrong_components,
            "witness_exposure": {"count": len(witnesses), "fraction": share(len(witnesses), len(scores)),
                                 "ids": [r["id"] for r in witnesses]},
            "repair_comparison_by_exposure": {"with_exact_witness": paired(witnesses, "abstract", "witness"),
                                              "without_exact_witness": paired(no_witnesses, "abstract", "witness")},
            "A_to_repairs": {arm: paired(scores, "A", arm) for arm in ("abstract", "witness")},
            "A_to_repairs_by_exposure": {
                name: {arm: paired(group, "A", arm) for arm in ("abstract", "witness")}
                for name, group in (("with_exact_witness", witnesses), ("without_exact_witness", no_witnesses))}}


def main():
    # Existence of this final summary is the release barrier: do not inspect
    # partial held-out scores while requests or their frozen scoring are pending.
    if not (OUT / "heldout-summary.json").is_file():
        raise SystemExit("Waiting for frozen heldout-summary.json; no audit written.")
    cases = read(OUT / "cases.private.json")
    inputs = [OUT / "cases.private.json", OUT / "protocol.json"]
    inputs += [OUT / f"{split}-{kind}.json" for split in ("development", "heldout")
               for kind in ("summary", "scores", "diagnostics")]
    hashes = {p.name: sha256(p) for p in inputs}
    report = {
        "schema": "natural-error-audit.v1", "new_model_requests": 0,
        "population": "Unmodified, naturally generated candidate and repair responses on the frozen public LP cohort.",
        "excluded_evidence": "Random geometry-test instances and any manually perturbed formulations are excluded from every empirical count.",
        "primary_unchanged": True,
        "reference_policy": "Existing official-annotation scores are read without rewriting or regrading; any annotation concern is sensitivity-only.",
        "value_comparison_policy": "Raw exact rational optimal values are compared only when both optima are finite. Matching objective direction is separately required for the reported same-direction count. No rescaling is inferred or applied. Numerical equality, especially at zero, is not scale-invariant evidence of semantic equivalence.",
        "subgroup_policy": "Witness presence is determined before final repair from initial A/B; subgroup tests are descriptive and do not replace the frozen primary test. Differences without witnesses cannot establish a concrete-witness mechanism.",
        "selection_ceiling_policy": "Oracle selection ceiling applies only to choosing an existing A or B; it is not a bound on creating a new repaired model.",
        "splits": {split: analyze_split(split, cases) for split in ("development", "heldout")},
        "input_sha256": hashes, "script_sha256": sha256(Path(__file__))}
    assert hashes == {p.name: sha256(p) for p in inputs}, "Frozen files changed during audit"
    destination = OUT / "natural-error-audit.json"
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    compact = {}
    for split, result in report["splits"].items():
        compact[split] = {"n": result["n"], "initial_outcomes": {k: v["count"] for k, v in result["initial_pair_outcomes"].items()},
                          "common_wrong_equivalent": result["both_wrong_same_feasible_region_and_optimal_face"]["count"],
                          "witness_exposure": result["witness_exposure"]["count"],
                          "repair_subgroups": result["repair_comparison_by_exposure"], "A_to_repairs": result["A_to_repairs"]}
    print(json.dumps(compact, ensure_ascii=False))


if __name__ == "__main__":
    main()
