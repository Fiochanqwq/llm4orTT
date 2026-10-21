"""Post-hoc single-reviewer sensitivity analysis; frozen scores stay untouched."""
from __future__ import annotations

import hashlib
from itertools import combinations
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "实验/决策契约研究_2026-10-21_01"
sys.path.insert(0, str(ROOT / "research"))
from decision_contract_study import candidate
from decision_geometry import analyze_model, compare_models

ARMS = ("A", "B", "abstract", "witness")


def read(path):
    return json.loads(path.read_text("utf-8-sig"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def paired(rows, before, after):
    gains = [r["id"] for r in rows if not r["arms"][before]["success"] and r["arms"][after]["success"]]
    losses = [r["id"] for r in rows if r["arms"][before]["success"] and not r["arms"][after]["success"]]
    discordant = len(gains) + len(losses)
    p = min(1.0, 2 * sum(math.comb(discordant, i) for i in range(min(len(gains), len(losses)) + 1)) / 2**discordant) if discordant else 1.0
    return {"before": before, "after": after, "n": len(rows),
            "gains": len(gains), "losses": len(losses), "gain_ids": gains, "loss_ids": losses,
            "difference": (len(gains) - len(losses)) / len(rows), "p_exact_two_sided": p}


def main():
    protected = [OUT / name for name in ("protocol.json", "cases.private.json", "heldout-scores.json", "heldout-summary.json", "annotation-review.json")]
    before_hashes = {p.name: digest(p) for p in protected}
    cases = [c for c in read(OUT / "cases.private.json") if c["split"] == "heldout"]
    frozen = {r["id"]: r for r in read(OUT / "heldout-scores.json")}
    summary = read(OUT / "heldout-summary.json")
    review = read(OUT / "annotation-review.json")
    edits = {entry["id"]: entry for entry in review["entries"]
             if entry["classification"] == "clear_annotation_issue" and entry.get("suggested_reference_sensitivity_only") is not None}
    assert len(cases) == len(frozen) == summary["n"] == 60
    assert set(edits) == {"-272035411", "-1864917274"}, "Only the two explicitly reviewed omissions are authorized"
    assert set(frozen) == {c["id"] for c in cases}
    rows = []
    response_hashes = {}
    for case in cases:
        reference = edits[case["id"]]["suggested_reference_sensitivity_only"] if case["id"] in edits else case["reference"]
        assert analyze_model(reference)["status"] == "optimal"
        row = {"id": case["id"], "reference_modified": case["id"] in edits, "arms": {}}
        for arm in ARMS:
            saved = OUT / "network" / f'{case["id"]}_{arm}.result.json'
            response_hashes[saved.name] = digest(saved)
            prediction = candidate(case, arm)
            original = frozen[case["id"]]["arms"][arm]
            assert prediction["valid"] == original["valid"], "Parser drift from frozen scoring"
            if not prediction["valid"]:
                result = {"valid": False, "success": False, "error": prediction["error"]}
            else:
                comparison = compare_models(reference, prediction["model"])
                result = {"valid": True,
                          "success": bool(comparison["feasible_sets_equal"] and comparison["optimal_faces_equal"]),
                          "feasible_sets_equal": comparison["feasible_sets_equal"],
                          "optimal_faces_equal": comparison["optimal_faces_equal"],
                          "objective_order_equal": comparison["objective_order_equal"],
                          "reference_status": comparison["left"]["status"],
                          "generated_status": comparison["right"]["status"],
                          "reference_value": comparison["left"]["value"],
                          "generated_value": comparison["right"]["value"]}
            result["frozen_primary_success"] = original["success"]
            if not row["reference_modified"]:
                assert result["success"] == original["success"], "Unmodified reference score changed"
            row["arms"][arm] = result
        rows.append(row)
    changes = {}
    for arm in ARMS:
        changes[arm] = {"false_to_true_ids": [r["id"] for r in rows if not r["arms"][arm]["frozen_primary_success"] and r["arms"][arm]["success"]],
                        "true_to_false_ids": [r["id"] for r in rows if r["arms"][arm]["frozen_primary_success"] and not r["arms"][arm]["success"]]}
    report = {"schema": "annotation-sensitivity.v1", "new_model_requests": 0, "n": 60,
              "status": "Post-hoc single-analyst sensitivity, not independent reannotation and not a replacement for frozen primary results.",
              "selection_limitation": "The two edits were identified after observing outcomes among seven shared annotation mismatches. No claim of an exhaustive or unbiased reference audit.",
              "reference_policy": "Only the two explicit omission corrections are substituted; all other 58 official references, all responses, validity rules and scoring rules remain unchanged. Three-times interpretation cases are not edited.",
              "modified_ids": sorted(edits),
              "modified_references": {key: {"official": frozen_case["reference"], "sensitivity_only": edits[key]["suggested_reference_sensitivity_only"]}
                  for key in edits for frozen_case in cases if frozen_case["id"] == key},
              "frozen_primary_counts": summary["scores"], "frozen_primary_comparison": summary["primary"],
              "sensitivity_counts": {arm: sum(r["arms"][arm]["success"] for r in rows) for arm in ARMS},
              "valid_counts": {arm: sum(r["arms"][arm]["valid"] for r in rows) for arm in ARMS},
              "score_changes": changes, "sensitivity_abstract_vs_witness": paired(rows, "abstract", "witness"),
              "all_pairwise_descriptive_tests": [paired(rows, a, b) for a, b in combinations(ARMS, 2)],
              "testing_limit": "Additional pairwise p-values are descriptive, post-hoc and unadjusted for multiplicity; they do not establish confirmatory superiority.",
              "rows": rows, "frozen_input_sha256": before_hashes, "response_sha256": response_hashes,
              "source_sha256": {p.name: digest(p) for p in (Path(__file__), ROOT / "research/decision_geometry.py", ROOT / "research/decision_contract_study.py")}}
    assert before_hashes == {p.name: digest(p) for p in protected}, "Protected files changed while auditing"
    with (OUT / "annotation-sensitivity.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: report[k] for k in ("n", "modified_ids", "sensitivity_counts", "score_changes", "sensitivity_abstract_vs_witness")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
