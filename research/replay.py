"""Offline task-board replay. Frozen inputs are read-only; outputs live separately."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from copy import deepcopy
from fractions import Fraction as F
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "实验/决策契约研究_2026-10-21_01"
OUTPUT = ROOT / "实验/任务板执行_2026-10-22_01"
ARMS = ("A", "B", "abstract", "witness")
sys.path.insert(0, str(ROOT / "research"))


def read(path):
    return json.loads(Path(path).read_text("utf-8-sig"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", "utf-8")


def safe_member(root, name):
    path = (root / name.replace("\\", "/")).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Evidence path escapes its root")
    return path


def inventory(source):
    return {p.relative_to(source).as_posix(): {"bytes": p.stat().st_size, "sha256": sha(p)}
            for p in sorted(source.rglob("*")) if p.is_file()}


def freeze_check(source=SOURCE, project=ROOT):
    """Verify original sealed bytes, explicitly recorded moves, and call ledger."""
    source, project = Path(source).resolve(), Path(project).resolve()
    before = inventory(source)
    manifest = read(source / "manifest.json")
    seal = read(source / "seal-result.json")
    protocol = read(source / "protocol.json")
    issues, relocated, amendments = [], [], []
    moved_record = project / "_归档_自我否定/cleanup.json"
    moved = set(read(moved_record).get("moved", [])) if moved_record.exists() else set()
    manifest_entries = {e["path"]: e for e in manifest["files"]}
    if len(manifest_entries) != len(manifest["files"]):
        issues.append({"kind": "duplicate_manifest_paths"})
    for name, entry in manifest_entries.items():
        p = safe_member(source, name)
        if not p.is_file():
            relative = p.relative_to(project).as_posix()
            moved_to = safe_member(project / "_归档_自我否定", relative)
            if relative in moved and moved_to.is_file() and sha(moved_to) == entry["sha256"]:
                relocated.append({"path": name, "current": moved_to.relative_to(project).as_posix(),
                                  "sha256": entry["sha256"], "record": "_归档_自我否定/cleanup.json"})
            else:
                issues.append({"kind": "missing_file", "path": name})
        elif sha(p) != entry["sha256"] or p.stat().st_size != entry["bytes"]:
            issues.append({"kind": "changed_file", "path": name})
    archive = source / "证据包.zip"
    if sha(archive) != seal["zipSha256"]:
        issues.append({"kind": "archive_hash_mismatch"})
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        expected_names = set(manifest_entries) | {"manifest.json"}
        if len(names) != len(set(names)) or set(names) != expected_names:
            issues.append({"kind": "archive_inventory_mismatch"})
        if z.testzip() is not None:
            issues.append({"kind": "archive_crc_failure"})
        if z.read("manifest.json") != (source / "manifest.json").read_bytes():
            issues.append({"kind": "archive_manifest_mismatch"})
        for name, entry in manifest_entries.items():
            if name not in names or hashlib.sha256(z.read(name)).hexdigest() != entry["sha256"]:
                issues.append({"kind": "archive_member_mismatch", "path": name})
    amendment = read(source / "amendment-001-parser-validation.json").get("changed", {})
    for name, original in protocol["sourceHashes"].items():
        p = safe_member(source / "source-snapshot", name)
        actual = sha(p) if p.is_file() else None
        if actual != original:
            edit = amendment.get(name, {})
            if edit.get("frozen") == original and edit.get("corrected") == actual:
                amendments.append({"path": name, "sha256": actual,
                                   "record": "amendment-001-parser-validation.json"})
            else:
                issues.append({"kind": "unregistered_source_drift", "path": name})
    events = [json.loads(line) for line in (source / "calls.jsonl").read_text("utf-8-sig").splitlines() if line.strip()]
    starts = [e for e in events if e["event"] == "started"]
    ends = [e for e in events if e["event"] == "finished"]
    start_ids, end_ids = [e["id"] for e in starts], [e["id"] for e in ends]
    expected_calls = protocol["budget"]["totalAuthorizedRequests"]
    ledger_ok = (len(events) == 2 * expected_calls and len(starts) == len(ends) == expected_calls
                 and len(set(start_ids)) == len(set(end_ids)) == expected_calls
                 and set(start_ids) == set(end_ids)
                 and sorted(e["sequence"] for e in starts) == list(range(1, expected_calls + 1)))
    if not ledger_ok:
        issues.append({"kind": "call_ledger_mismatch"})
    end_by_id = {e["id"]: e for e in ends}
    for e in starts:
        request = read(safe_member(source / "network", e["id"] + ".request.json"))
        result = read(safe_member(source / "network", e["id"] + ".result.json"))
        prompt_hash = hashlib.sha256(json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        if prompt_hash != e["promptSha256"] or result["status"] != end_by_id.get(e["id"], {}).get("status"):
            issues.append({"kind": "request_or_response_mismatch", "id": e["id"]})
    key_files = {}
    for name in ("calls.jsonl", "heldout-scores.json"):
        entry = manifest_entries.get(name)
        ok = entry is not None and sha(source / name) == entry["sha256"]
        key_files[name] = {"sha256": sha(source / name), "registration": "manifest.json", "matched": ok}
        if not ok:
            issues.append({"kind": "key_file_hash_mismatch", "path": name})
    after = inventory(source)
    if before != after:
        issues.append({"kind": "source_changed_during_check"})
    return {"schema": "task-board-freeze.v1", "passed": not issues, "new_model_requests": 0,
            "manifest_entries": len(manifest_entries), "current_files": len(before),
            "unique_calls": len(set(start_ids)), "ledger_events": len(events),
            "key_files": key_files, "relocated_files": relocated, "registered_source_amendments": amendments,
            "discrepancies": issues, "source_unchanged": before == after,
            "task_text_correction": "Result hashes are registered in manifest.json; protocol.json registers design and source hashes.",
            "unlisted_current_files": sorted(set(before) - set(manifest_entries)),
            "anchors": {name: sha(source / name) for name in ("protocol.json", "manifest.json", "seal-result.json", "证据包.zip")}}, before


def write_freeze(source=SOURCE, output=OUTPUT):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output == source or output.is_relative_to(source):
        raise ValueError("Outputs must be outside frozen evidence")
    if not (output / "prereg.json").is_file():
        raise ValueError("Register prereg.json before execution")
    result, files = freeze_check(source)
    save(output / "freeze-check.json", result)
    (output / "manifest.tsv").write_text("path\tbytes\tsha256\n" + "".join(
        f'{name}\t{entry["bytes"]}\t{entry["sha256"]}\n' for name, entry in files.items()), "utf-8")
    return result


def row_satisfied(row, point):
    lhs = sum((F(str(a)) * F(str(x)) for a, x in zip(row["a"], point)), F(0))
    rhs = F(str(row["b"]))
    return {"<=": lhs <= rhs, ">=": lhs >= rhs, "=": lhs == rhs}[row["op"]]


def memberships(model, point):
    return all(F(str(x)) >= 0 for x in point) and all(row_satisfied(r, point) for r in model["constraints"])


def make_readings(source=SOURCE):
    from decision_geometry import compile_model
    review = read(source / "annotation-review.json")
    witnesses = {"1605420061": ["3", "1"], "-756853497": ["15", "5"],
                 "2137478401": ["0", "30"], "-272035411": ["5", "15/2"],
                 "-1864917274": ["5", "5"], "-1587539848": ["15", "5"],
                 "-1715698555": ["12", "4"]}
    kinds = {"clear_generated_error": "generated_error", "clear_annotation_issue": "annotation_issue",
             "ambiguous_or_undetermined": "ambiguous"}
    entries, policies = [], {}
    for record in review["entries"]:
        official = record["frozen_reference_ir"]
        kind = kinds[record["classification"]]
        corrected = deepcopy(record["suggested_reference_sensitivity_only"] or official)
        alternatives = []
        if kind == "ambiguous":
            rows = [r for r in corrected["constraints"] if list(map(F, r["a"])) == [F(1), F(-3)]]
            if len(rows) != 1:
                raise ValueError("Ambiguous relation cannot be uniquely located")
            rows[0]["op"] = "="
            alternatives = [deepcopy(official)]
        for model in [corrected, *alternatives]:
            compile_model(model)
            if not memberships(model, witnesses[record["id"]]):
                raise ValueError("Exact feasible witness failed: " + record["id"])
        point = record["exact_difference_witness"]["point"]
        member = {"official": memberships(official, point), "corrected": memberships(corrected, point)}
        for arm in ("A", "B"):
            member[arm] = memberships(record["generated_models"][arm], point)
            if member[arm] != record["exact_difference_witness"]["membership"][arm]:
                raise ValueError("Historical counterexample membership drift")
        entry = {"id": record["id"], "type": kind, "original_span": record["quoted_evidence"],
                 "variables": record["variable_order"], "sense": corrected["sense"], "objective": corrected["objective"],
                 "correct_rows": corrected["constraints"], "official_rows": official["constraints"],
                 "alternative_rows": [a["constraints"] for a in alternatives],
                 "witness_point": witnesses[record["id"]], "witness_role": "feasible_for_correct_rows",
                 "counterexample_point": point, "counterexample_membership": member,
                 "review_provenance": "frozen annotation-review.json; single analyst, outcome-selected"}
        entries.append(entry)
        policies[record["id"]] = [corrected, *alternatives]
    sensitivity = sorted(e["id"] for e in entries if e["type"] == "annotation_issue")
    assert len(entries) == 7 and len(sensitivity) == 2
    overrides = {"schema": "gold-overrides.v1", "entries": entries, "sensitivity_correction_ids": sensitivity,
                 "additional_unique_annotation_ids": [], "source_sha256": sha(source / "annotation-review.json")}
    readings = {"schema": "admissible-readings.v1", "variants": {
        "seven_case": policies, "seven_plus_all_annotation": deepcopy(policies)},
        "unchanged_policy": "Use the frozen official model for all unlisted cases.",
        "variant_identity_reason": "Both reviewed annotation corrections are already in the seven-case set.",
        "corrected_annotation_policy": "Replace the two erroneous references; keep both readings only for explicit ambiguity."}
    return overrides, readings


def load_candidate(source, case, arm):
    from decision_geometry import analyze_model
    path = source / "network" / f'{case["id"]}_{arm}.result.json'
    try:
        result = read(path)
        if result["status"] != "complete":
            raise ValueError("transport_or_finish_failure")
        text = result["text"].strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        model = json.loads(text)
        analyze_model(model)
        return {"valid": True, "model": model}
    except (ValueError, KeyError, TypeError, OSError) as error:
        return {"valid": False, "error": str(error)}


def exact_binomial_interval(k, n, alpha=0.05):
    """Clopper-Pearson equal-tailed interval by binomial-tail inversion."""
    if not 0 <= k <= n or n <= 0 or not 0 < alpha < 1:
        raise ValueError("Invalid binomial interval arguments")
    def tail(p, start, stop):
        return math.fsum(math.comb(n, i) * p**i * (1-p)**(n-i) for i in range(start, stop))
    def invert(start, stop, increasing):
        lo, hi = 0.0, 1.0
        for _ in range(64):
            mid = (lo + hi) / 2
            if (tail(mid, start, stop) < alpha / 2) == increasing:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2
    return [0.0 if k == 0 else invert(k, n + 1, True),
            1.0 if k == n else invert(0, k + 1, False)]


def score_summary(rows):
    n = len(rows)
    counts = {arm: sum(r["arms"][arm]["success"] for r in rows) for arm in ARMS}
    return {arm: {"correct": k, "n": n, "rate": k/n, "exact_ci95": exact_binomial_interval(k, n),
                  "rank": 1 + sum(v > k for v in counts.values())} for arm, k in counts.items()}


def rescore(source, readings):
    from decision_geometry import compare_models
    cases = read(source / "cases.private.json")
    replayed, predictions = {}, {}
    for split in ("development", "heldout"):
        stored = {r["id"]: r for r in read(source / (split + "-scores.json"))}
        cohort = [c for c in cases if c["split"] == split]
        assert [c["id"] for c in cohort] == read(source / "protocol.json")["frozenCaseIds"][split]
        rows = []
        for case in cohort:
            row = {"id": case["id"], "arms": {}}
            for arm in ARMS:
                prediction = load_candidate(source, case, arm)
                predictions[(case["id"], arm)] = prediction
                old = stored[case["id"]]["arms"][arm]
                assert prediction["valid"] == old["valid"], "Frozen parser validity drift"
                comparison = compare_models(case["reference"], prediction["model"]) if prediction["valid"] else None
                if comparison is not None:
                    assert comparison == old["comparison"], "Frozen geometry comparison drift"
                success = bool(comparison and comparison["feasible_sets_equal"] and comparison["optimal_faces_equal"])
                assert success == old["success"], "Frozen per-case score drift"
                row["arms"][arm] = {"valid": prediction["valid"], "success": success}
            rows.append(row)
        replayed[split] = rows
    old_summary = score_summary(replayed["heldout"])
    assert [old_summary[a]["correct"] for a in ARMS] == [42, 46, 44, 43]
    by_id = {r["id"]: r for r in replayed["heldout"]}
    variants = {}
    for name, edits in readings["variants"].items():
        rows = []
        for case in (c for c in cases if c["split"] == "heldout"):
            row = {"id": case["id"], "arms": {}}
            for arm in ARMS:
                prediction = predictions[(case["id"], arm)]
                matched = []
                if prediction["valid"]:
                    for i, model in enumerate(edits.get(case["id"], [case["reference"]])):
                        cmp = compare_models(model, prediction["model"])
                        if cmp["feasible_sets_equal"] and cmp["optimal_faces_equal"]:
                            matched.append(i)
                row["arms"][arm] = {"valid": prediction["valid"], "success": bool(matched),
                                     "matched_readings": matched, "frozen_success": by_id[case["id"]]["arms"][arm]["success"]}
            rows.append(row)
        summary = score_summary(rows)
        for arm in ARMS:
            summary[arm].update(delta=summary[arm]["correct"]-old_summary[arm]["correct"],
                gain_ids=[r["id"] for r in rows if r["arms"][arm]["success"] and not r["arms"][arm]["frozen_success"]],
                loss_ids=[r["id"] for r in rows if not r["arms"][arm]["success"] and r["arms"][arm]["frozen_success"]])
        variants[name] = {"summary": summary, "rows": rows}
    return {"schema": "admissible-rescore.v1", "new_model_requests": 0,
            "replayed_raw_responses": len(predictions), "frozen_summary": old_summary,
            "variants": variants, "variant_identity_reason": readings["variant_identity_reason"],
            "interpretation": "Post-hoc, outcome-selected single-reviewer sensitivity. CI covers binomial sampling only, not annotation uncertainty.",
            "rows_frozen": replayed["heldout"]}


def write_readings(source=SOURCE, output=OUTPUT):
    if not read(output / "freeze-check.json")["passed"]:
        raise ValueError("T0 must pass")
    overrides, readings = make_readings(source)
    save(output / "gold_overrides.json", overrides)
    save(output / "admissible_readings.json", readings)
    return {"cases": len(overrides["entries"]), "exact_witness_checks": "passed"}


def write_rescore(source=SOURCE, output=OUTPUT):
    result = rescore(source, read(output / "admissible_readings.json"))
    save(output / "rescore.json", result)
    lines = ["# 可接受读法重打分", "", "数据源：本目录 `rescore.json`；冻结参考与原始响应路径见 `prereg.json`。", "",
             "| 口径 | 臂 | 正确 / 总数 | 比例 | 精确 95% 区间 | 正确数变化 | 排名 |", "|---|---|---|---|---|---|---|"]
    groups = [("冻结参考", result["frozen_summary"])] + [(name, v["summary"]) for name, v in result["variants"].items()]
    for name, summary in groups:
        for arm, s in summary.items():
            lo, hi = s["exact_ci95"]
            lines.append(f'| {name} | {arm} | {s["correct"]}/{s["n"]} | {s["rate"]:.1%} | {lo:.1%}–{hi:.1%} | {s.get("delta",0):+d} | {s["rank"]} |')
    lines.extend(["", "两处标注修正已包含在七例中，两种敏感性口径使用相同的题目与读法。", "",
                  "## 局限", "", "- 7 例来自观察结果后的单人审读；区间仅覆盖二项抽样误差，人工复核结果另行登记。"])
    (output / "rescore.md").write_text("\n".join(lines) + "\n", "utf-8")
    return {name: {a: s["correct"] for a, s in v["summary"].items()} for name, v in result["variants"].items()}


def write_geometry(source=SOURCE, output=OUTPUT):
    import exact_lp
    old = {r["id"]: r for r in read(source / "heldout-scores.json")}
    old_pairs = {r["id"]: r for r in read(source / "heldout-diagnostics.json")}
    rows, proofs, discrepancies = [], [], []
    counts = dict.fromkeys(ARMS, 0)
    for case in read(source / "cases.private.json"):
        if case["split"] != "heldout":
            continue
        candidates = {arm: load_candidate(source, case, arm) for arm in ARMS}
        for arm, prediction in candidates.items():
            if not prediction["valid"]:
                assert not old[case["id"]]["arms"][arm]["valid"]
                rows.append({"id": case["id"], "arm": arm, "valid": False, "success": False})
                continue
            result = exact_lp.compare_models(case["reference"], prediction["model"])
            expected = old[case["id"]]["arms"][arm]["comparison"]
            for flag in ("feasible_sets_equal", "optimal_faces_equal"):
                if result[flag] != expected[flag]:
                    discrepancies.append({"id": case["id"], "arm": arm, "flag": flag})
            counts[arm] += result["feasible_sets_equal"] and result["optimal_faces_equal"]
            rows.append({"id": case["id"], "arm": arm, "valid": True,
                         **{key: result[key] for key in ("feasible_sets_equal", "optimal_faces_equal")}})
            proofs.append({"id": case["id"], "arm": arm, "comparison": result})
        if candidates["A"]["valid"] and candidates["B"]["valid"]:
            result = exact_lp.compare_models(candidates["A"]["model"], candidates["B"]["model"])
            expected = old_pairs[case["id"]]["verdict"]
            for flag in ("feasible_sets_equal", "optimal_faces_equal"):
                if result[flag] != expected[flag]:
                    discrepancies.append({"id": case["id"], "arm": "A_vs_B", "flag": flag})
            proofs.append({"id": case["id"], "arm": "A_vs_B", "comparison": result})
    expected_counts = {arm: value["correct"] for arm, value in read(output / "rescore.json")["frozen_summary"].items()}
    report = {"schema": "exact-lp-regression.v1", "passed": not discrepancies and counts == expected_counts,
        "counts": counts, "cases": len(old), "comparisons": len(proofs), "discrepancies": discrepancies,
        "rows": rows, "method_source_sha256": sha(ROOT / "research/exact_lp.py"),
        "reference_source_sha256": sha(ROOT / "research/decision_geometry.py"), "new_model_requests": 0,
        "implementation_policy": "Existing 2D implementation preserved; new implementation is separate.",
        "proof_file": "geometry-certificates.json", "highs_version": exact_lp.hs.Highs().version()}
    save(output / "geometry-certificates.json", proofs)
    save(output / "geometry-regression.json", report)
    return {k: v for k, v in report.items() if k != "rows"}


def baselines(result, source=SOURCE):
    rows = result["rows_frozen"]
    n = len(rows)
    scores = {"pick-A": sum(r["arms"]["A"]["success"] for r in rows),
              "pick-B": sum(r["arms"]["B"]["success"] for r in rows),
              "oracle-select": sum(r["arms"]["A"]["success"] or r["arms"]["B"]["success"] for r in rows)}
    old = read(source / "natural-error-audit.json")["splits"]["heldout"]
    assert scores["pick-A"] == old["frozen_summary"]["scores"]["A"]
    assert scores["pick-B"] == old["frozen_summary"]["scores"]["B"]
    assert scores["oracle-select"] == old["selection_ceiling_with_oracle_choosing_A_or_B"]
    return {"schema": "selection-baselines.v1", "n": n, "new_model_requests": 0,
        "reference_policy": "Frozen official annotations; oracle is an existing-candidate selection ceiling, not a deployable method.",
        "methods": {name: {"correct": k, "rate": k/n, "exact_ci95": exact_binomial_interval(k, n)} for name, k in scores.items()},
        "rows": [{"id": r["id"], "A": r["arms"]["A"]["success"], "B": r["arms"]["B"]["success"]} for r in rows]}


def write_baselines(source=SOURCE, output=OUTPUT):
    result = baselines(read(output / "rescore.json"), source)
    save(output / "baselines.json", result)
    return result["methods"]


def paper_tables(result, baseline):
    """Each row names its canonical source field; tables never embed hand scores."""
    def row(label, s, field, tag, policy=None):
        return {"label": label, "policy": policy, "correct": s["correct"],
                "n": s.get("n", baseline["n"]), "rate": s["rate"], "exact_ci95": s["exact_ci95"],
                "delta": s.get("delta", 0), "rank": s.get("rank"), "source": tag, "field": field}
    first = [row(name, baseline["methods"][name], "methods."+name, "R1") for name in ("pick-B", "pick-A")]
    first += [row(a, result["frozen_summary"][a], "frozen_summary."+a, "R2") for a in ARMS]
    first += [row("oracle-select", baseline["methods"]["oracle-select"], "methods.oracle-select", "R1")]
    groups = [("Frozen", "frozen_summary", result["frozen_summary"])]
    groups += [(name, "variants."+name+".summary", v["summary"]) for name, v in result["variants"].items()]
    second = [row(a, s[a], field+"."+a, "R2", name) for name, field, s in groups for a in ARMS]
    return {"schema": "paper-tables.v1", "source_directory": "../ (relative to paper/main.tex)",
            "sources": {"R1": "../baselines.json", "R2": "../rescore.json"},
            "table1": first, "table2": second}


def render_tables(tables):
    def mark(value, row):
        return str(value).replace("_", r"\_") + r"\textsuperscript{"+row["source"]+"}"
    lines = ["% Generated by research.replay. Do not edit numerical cells."]
    for key, environment, columns in (("table1", "table*", "lrrl"), ("table2", "table*", "llrrlrr")):
        lines += [r"\begin{"+environment+"}[t]", r"\centering", r"\small", r"\begin{tabular}{"+columns+"}", r"\hline"]
        lines += [r"Method & Correct/$n$ & Rate (\%) & 95\% CI (\%) \\" if key == "table1" else
                  r"Reference policy & Arm & Correct/$n$ & Rate (\%) & 95\% CI (\%) & $\Delta k$ & Rank \\", r"\hline"]
        for row in tables[key]:
            lo, hi = row["exact_ci95"]
            cells = [row["label"], f'{row["correct"]}/{row["n"]}', f'{100*row["rate"]:.1f}', f'{100*lo:.1f}--{100*hi:.1f}']
            if key == "table2":
                policy = {"Frozen": "Frozen", "seven_case": "Seven-case", "seven_plus_all_annotation": "Seven + all annotation"}[row["policy"]]
                cells = [policy]+cells+[f'{row["delta"]:+d}', row["rank"]]
            lines.append(" & ".join(mark(c, row) for c in cells)+r" \\")
        caption = ("Frozen-reference results. Pick-A and pick-B reuse the corresponding candidate; oracle-select uses the reference to choose an existing candidate."
                   if key == "table1" else "Post-hoc admissible-reading sensitivity. The annotation corrections are a subset of the seven cases, so the two sensitivity policies coincide. Delta is the change from the frozen count; ranks use competition ranking.")
        lines += [r"\hline", r"\end{tabular}", r"\caption{"+caption+
                  r" Every data cell carries its source-directory tag: R1 = \texttt{../baselines.json}; R2 = \texttt{../rescore.json}. Both paths are relative to this paper's experiment directory. Exact field paths are in \texttt{../tables.json}. Intervals are marginal Clopper--Pearson intervals.}",
                  r"\label{tab:"+key+"}", r"\end{"+environment+"}"]
    return "\n".join(lines)+"\n"


def paper_facts(source, result):
    audit = read(source / "natural-error-audit.json")["splits"]["heldout"]
    primary = read(source / "heldout-summary.json")["primary"]
    values = {"HeldoutN": result["frozen_summary"]["A"]["n"], "ResponseN": result["replayed_raw_responses"],
              "SharedWrong": audit["both_wrong_same_feasible_region_and_optimal_face"]["count"],
              "BothWrong": audit["initial_pair_outcomes"]["both_incorrect"]["count"],
              "ExposureN": audit["witness_exposure"]["count"], "PrimaryGains": primary["gains"],
              "PrimaryLosses": primary["losses"], "PrimaryP": f'{primary["pExact"]:.2f}'}
    return "% Generated from frozen source fields listed in facts_sheet.md.\n" + "".join(
        "\\newcommand{\\"+key+"}{"+str(value)+"}\n" for key, value in values.items())


def write_tables(source=SOURCE, output=OUTPUT):
    result, baseline = read(output / "rescore.json"), read(output / "baselines.json")
    tables = paper_tables(result, baseline)
    save(output / "tables.json", tables)
    (output / "paper").mkdir(exist_ok=True)
    (output / "paper/tables.tex").write_text(render_tables(tables), "utf-8")
    (output / "paper/facts.tex").write_text(paper_facts(source, result), "utf-8")
    return {"tables": len([k for k in tables if k.startswith("table")]), "data_rows": len(tables["table1"])+len(tables["table2"])}


def check_replay(source=SOURCE, output=OUTPUT):
    """Recompute from frozen raw responses, compare saved artifacts without rewriting them."""
    source, output = Path(source).resolve(), Path(output).resolve()
    if output == source or output.is_relative_to(source):
        raise ValueError("Outputs must be outside frozen evidence")
    frozen, before = freeze_check(source)
    differences = [] if frozen["passed"] else ["frozen evidence integrity"]
    initial = read(output / "freeze-check.json")
    if initial["anchors"] != frozen["anchors"]:
        differences.append("frozen anchor fingerprints changed since T0")
    expected_inventory = "path\tbytes\tsha256\n" + "".join(
        f'{name}\t{e["bytes"]}\t{e["sha256"]}\n' for name, e in before.items())
    if (output / "manifest.tsv").read_text("utf-8") != expected_inventory:
        differences.append("frozen inventory changed since T0")
    overrides, readings = make_readings(source)
    result = rescore(source, readings)
    baseline = baselines(result, source)
    tables = paper_tables(result, baseline)
    rebuilt = {"gold_overrides.json": overrides, "admissible_readings.json": readings,
               "rescore.json": result, "baselines.json": baseline, "tables.json": tables}
    for name, expected in rebuilt.items():
        if read(output / name) != expected:
            differences.append(name)
    for name, expected in {"paper/tables.tex": render_tables(tables), "paper/facts.tex": paper_facts(source, result)}.items():
        if (output / name).read_text("utf-8") != expected:
            differences.append(name)
    if inventory(source) != before:
        differences.append("frozen source changed during replay")
    report = {"schema": "paper-replay-check.v1", "passed": not differences,
              "new_model_requests": 0, "replayed_raw_responses": result["replayed_raw_responses"],
              "table_data_rows": len(tables["table1"])+len(tables["table2"]),
              "differences": differences, "comparison": "exact structures and rendered text; no numeric tolerance",
              "source_unchanged": inventory(source) == before}
    save(output / "replay-check.json", report)
    return report


def prepare_consistency(source=SOURCE, output=OUTPUT):
    """Register T7 before dispatch, retaining the board's sample size and six draws."""
    import decision_contract_study as study
    output = Path(output).resolve()
    if output.exists() or output.is_relative_to(Path(source).resolve()):
        raise ValueError("A fresh experiment directory outside frozen inputs is required")
    frozen, files = freeze_check(source)
    if not frozen["passed"]:
        raise ValueError("Frozen evidence failed integrity checks")
    admission = read(source / "admission.json")
    prior_cases = read(source / "cases.private.json")
    ids = [c["id"] for c in prior_cases] + admission["unselectedEligible"]
    ids = sorted(set(ids), key=lambda i: hashlib.sha256(("T7-20261022:"+i).encode()).hexdigest())[:100]
    if len(ids) != 100:
        raise ValueError("T7 needs 100 distinct eligible representatives")
    raw = {}
    for line in (source / "source-snapshot/datasets/llm-grounding-v1/nl4opt-test.jsonl").read_text("utf-8-sig").splitlines():
        raw.update(json.loads(line))
    cases, queue = [], []
    for identifier in ids:
        r = raw[identifier]
        case = {"id": identifier, "text": r["document"], "variables": r["vars"], "reference": study.canonical_record(identifier, r)}
        cases.append(case)
        prompt = study.public_prompt(case)
        prompt["instruction"] = "Construct the complete LP directly from the original description."
        for repeat in range(6):
            queue.append(study.request(f"{identifier}_s{repeat}", prompt))
    # Use only frozen A/B observations, excluding later transfer/consultation calls.
    observations = [read(source / "network" / f'{c["id"]}_{a}.result.json')["usage"] for c in prior_cases for a in ("A", "B")]
    averages = {k: sum(u[k] for u in observations)/len(observations) for k in ("prompt_tokens", "completion_tokens")}
    prices = {"off_peak": {"hit": .02, "miss": 1, "output": 4}, "peak": {"hit": .04, "miss": 2, "output": 8}}
    estimate = {name: {"input_CNY": 600*averages["prompt_tokens"]*p["miss"]/1e6,
        "output_CNY": 600*averages["completion_tokens"]*p["output"]/1e6} for name,p in prices.items()}
    for v in estimate.values():
        v["total_CNY"] = v["input_CNY"]+v["output_CNY"]
    prereg = {"schema": "task-board-paid.v1", "task": "T7", "n": 100, "MDE": None,
        "MDE_reason": "Descriptive conditional error probabilities, no between-arm effect threshold.",
        "arms": ["same_prompt_temperature_0"], "draws_per_problem": 6, "model": "deepseek-flash",
        "max_tokens": 3072, "budget": {"total_CNY": 6, "stop_remaining_CNY": 1.2, "max_model_calls": 600, "automatic_retries": 0},
        "source_board": "实验/任务板执行_2026-10-22_01/source-snapshot/任务.md",
        "source_board_sha256": sha(OUTPUT / "source-snapshot/任务.md"),
        "selection": "First 100 of the 160 frozen eligible group representatives sorted by SHA256(T7-20261022:<id>), before new outcomes.",
        "case_ids": ids, "temperature": 0, "thinking": "disabled", "reference_policy": "Frozen official annotations; no sensitivity overrides.",
        "cluster_rule": "Exact feasible-region and attained-optimal-face equivalence. Invalid responses are failures, never an equivalence class. Largest class wins; ties choose earliest draw.",
        "conditioning": "All-consistent requires 6 valid draws and 1 class. Divergent requires 6 valid draws and >=2 classes. Incomplete cases reported separately, retained in overall denominator.",
        "CI": "Equal-tail 95% Clopper-Pearson for binomial cells; problem-level fixed-seed percentile bootstrap for mean modal share and textual repetition.",
        "switching_rules": ["No requests before numeric estimate and log exist.", "Run only if estimated peak cost <= remaining budget.", "Stop before dispatch if accounted spend plus in-flight peak reservations would consume the 20% floor.", "Unknown-charge failures retain their maximum reservation; never retry.", "No expansion of T8 screening cohort or change of its 60+20 target.", "T11 remains dependent on actual T3 human work."],
        "pricing": {"checked_on": "2026-10-22", "url": "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/", "model_version": "DeepSeek-V4.1-Flash-1017", "CNY_per_million_tokens": prices,
                    "peak_Beijing": "Working weekdays excluding statutory holidays: 09:00-12:00 and 14:00-18:00; other times off-peak."},
        "estimate": {"calls": 600, "basis": "Mean measured prompt/output tokens of all frozen initial A/B responses; input billed as all cache misses.", "observations": len(observations), "mean_tokens": averages, "costs": estimate},
        "observations": ["T7 conditional authorization follows user item 1: execute when estimate fits; no calls for quoting.", "T8 requires actual distinct outcome strata. T11's stated 300 problems times 3 transformations means 900 transformed evaluations; human validation is still required."]}
    output.mkdir(parents=True)
    save(output / "prereg.json", prereg)
    (output / "execution.log").write_text(f'预估调用数：600；预估费用：高峰 ¥{estimate["peak"]["total_CNY"]:.6f}（输入 ¥{estimate["peak"]["input_CNY"]:.6f}、输出 ¥{estimate["peak"]["output_CNY"]:.6f}），谷值 ¥{estimate["off_peak"]["total_CNY"]:.6f}（输入 ¥{estimate["off_peak"]["input_CNY"]:.6f}、输出 ¥{estimate["off_peak"]["output_CNY"]:.6f}）；预算 ¥6。\n', "utf-8")
    save(output / "cases.private.json", cases)
    save(output / "consistency-queue.json", queue)
    save(output / "freeze-check.json", frozen)
    save(output / "frozen-before.json", files)
    save(output / "paper-before.json", inventory(OUTPUT / "paper"))
    budget = {"total_CNY": 6, "stop_remaining_CNY": 1.2, "max_model_calls": 600, "model": "deepseek-flash", "prices": prices,
        "queue_sha256": sha(output / "consistency-queue.json"), "prereg_sha256": sha(output / "prereg.json")}
    save(output / "budget.json", budget)
    return prereg["estimate"]


def score_consistency(source=SOURCE, output=OUTPUT):
    from decision_geometry import compare_models
    import random
    prereg = read(output / "prereg.json")
    cases = read(output / "cases.private.json")
    rows = []
    def same(a, b):
        c = compare_models(a, b)
        return c["feasible_sets_equal"] and c["optimal_faces_equal"]
    for case in cases:
        groups, draws, texts = [], [], []
        for repeat in range(6):
            candidate = load_candidate(output, case, f"s{repeat}")
            row = {"draw": repeat, "valid": candidate["valid"], "success": False}
            if candidate["valid"]:
                model = candidate["model"]
                comp = compare_models(case["reference"], model)
                row.update(success=comp["feasible_sets_equal"] and comp["optimal_faces_equal"],
                           feasible_sets_equal=comp["feasible_sets_equal"], optimal_faces_equal=comp["optimal_faces_equal"])
                row["error_type"] = "none" if row["success"] else "both" if not comp["feasible_sets_equal"] and not comp["optimal_faces_equal"] else "feasible_region" if not comp["feasible_sets_equal"] else "optimal_face"
                matched = next((g for g in groups if same(g["model"], model)), None)
                if matched is None:
                    matched = {"model": model, "draws": []}
                    groups.append(matched)
                matched["draws"].append(repeat)
                texts.append(read(output / "network" / f'{case["id"]}_s{repeat}.result.json')["text"])
            else:
                row.update(error_type="invalid", error=candidate.get("error"))
            draws.append(row)
        ordered = sorted(groups, key=lambda g: (-len(g["draws"]), g["draws"][0]))
        selected = draws[ordered[0]["draws"][0]] if ordered else {"success": False, "error_type": "invalid"}
        complete = all(d["valid"] for d in draws)
        rows.append({"id": case["id"], "draws": draws, "clusters": [g["draws"] for g in ordered],
            "complete": complete, "stratum": "incomplete" if not complete else "all_consistent" if len(groups)==1 else "divergent",
            "modal_share": len(ordered[0]["draws"])/6 if ordered else 0,
            "text_repeated": len(texts)-len(set(texts)), "valid_texts": len(texts),
            "selected_success": selected["success"], "selected_error_type": selected["error_type"]})
    def cell(k, n):
        return {"k": k, "n": n, "rate": k/n if n else None, "exact_ci95": exact_binomial_interval(k,n) if n else None}
    strata = {}
    for name in ("all_consistent", "divergent", "incomplete"):
        group = [r for r in rows if r["stratum"] == name]
        strata[name] = {"wrong": cell(sum(not r["selected_success"] for r in group), len(group)),
            "by_error_type": {e: cell(sum(r["selected_error_type"]==e for r in group),len(group)) for e in ("invalid", "feasible_region", "optimal_face", "both")},
            "ids": [r["id"] for r in group]}
    def average_ci(values):
        rng = random.Random(202610227)
        boot = sorted(sum(rng.choice(values) for _ in values)/len(values) for _ in range(10000))
        return {"n": len(values), "mean": sum(values)/len(values), "problem_bootstrap95": [boot[249],boot[9749]]}
    result = {"schema": "consistency-at-six.v1", "n": len(rows), "planned_calls": prereg["budget"]["max_model_calls"],
        "majority_success": cell(sum(r["selected_success"] for r in rows),len(rows)), "conditional_errors": strata,
        "modal_share": average_ci([r["modal_share"] for r in rows]),
        "text_repetition": average_ci([r["text_repeated"]/r["valid_texts"] if r["valid_texts"] else 0 for r in rows]),
        "rows": rows, "reference_policy": prereg["reference_policy"], "invalid_policy": prereg["conditioning"],
        "budget": read(output / "budget-spend.json"), "retries": 0}
    save(output / "consistency.json", result)
    lines = ["# T7 同提示重复采样", "", "数值来源：本目录 `consistency.json`；抽样、聚类与费用规则见 `prereg.json`。", "",
             "| 条件 | 错误数 / n | 错误率 | 精确 95% 区间 |", "|---|---|---|---|"]
    for name, group in strata.items():
        for label, c in [(name,group["wrong"])]+[(name+" / "+e,c) for e,c in group["by_error_type"].items()]:
            interval = "无可估计样本" if c["exact_ci95"] is None else f'{c["exact_ci95"][0]:.1%}–{c["exact_ci95"][1]:.1%}'
            rate = "—" if c["rate"] is None else f'{c["rate"]:.1%}'
            lines.append(f'| {label} | {c["k"]}/{c["n"]} | {rate} | {interval} |')
    for key in ("modal_share", "text_repetition"):
        c=result[key]
        lines.append(f'\n{key}：均值 {c["mean"]:.1%}，题目级 n={c["n"]}，bootstrap 95% 区间 {c["problem_bootstrap95"][0]:.1%}–{c["problem_bootstrap95"][1]:.1%}。')
    lines += ["", "## 局限", "", "- 1 个模型、固定温度下的重复采样；同题响应按题目聚类计算区间。", "- 6 份有效响应才进入全一致或分歧条件分母；失败样本保留在总体和不完整层。"]
    (output / "consistency.md").write_text("\n".join(lines)+"\n", "utf-8")
    return {"n": len(rows), "majority_success": result["majority_success"], "strata": {k:v["wrong"] for k,v in strata.items()}}


def summarize_ladder(cases, observations):
    """T8 problem-level denominators; repeated rounds never inflate sample size."""
    from decision_interventions import validate_ladder_cohort
    validate_ladder_cohort(cases)
    arms = ("verdict", "point", "point+anchor")
    ids = {c["id"] for c in cases}
    indexed, terminal_failures = {}, set()
    for row in observations:
        key = (row["id"], row["arm"], row["round"])
        if row["id"] not in ids or row["arm"] not in arms or type(row["round"]) is not int or not 1 <= row["round"] <= 3 or key in indexed:
            raise ValueError("Invalid or duplicated ladder observation")
        for field in ("success", "valid"):
            if type(row["metrics"][field]) is not bool:
                raise ValueError("A ladder outcome must be Boolean")
        if row["metrics"]["success"] and not row["metrics"]["valid"]:
            raise ValueError("An invalid response cannot be successful")
        for field in ("compliance", "damage"):
            if row["metrics"][field] is not None and type(row["metrics"][field]) is not bool:
                raise ValueError("Missing round measurements must be null")
        indexed[key] = row["metrics"]
        if row.get("terminal_failure"):
            if row["metrics"]["valid"]:
                raise ValueError("A terminal parse failure cannot have a valid model")
            terminal_failures.add(key)
    def cell(values):
        n, k = len(values), sum(values)
        return {"k": k, "n": n, "rate": k/n if n else None, "exact_ci95": exact_binomial_interval(k, n) if n else None}
    table = {}
    for stratum in ("all", "divergent", "all_consistent_wrong"):
        selected = [c["id"] for c in cases if stratum == "all" or c["stratum"] == stratum]
        table[stratum] = {}
        for arm in arms:
            success = cell([any(indexed.get((i, arm, r), {}).get("success", False) for r in (1, 2, 3)) for i in selected])
            rounds = {}
            for r in (1, 2, 3):
                observed = [indexed[(i, arm, r)] for i in selected if (i, arm, r) in indexed]
                rounds[str(r)] = {"observed_n": len(observed), "planned_n": len(selected),
                                  **{m: {**cell([o[m] for o in observed if o[m] is not None]),
                                         "missing_n": len(selected)-sum(o[m] is not None for o in observed)} for m in ("compliance", "damage")}}
            table[stratum][arm] = {"success@3": success, "rounds": rounds}
    incomplete = []
    for identifier in ids:
        for arm in arms:
            rounds = sorted(r for i, a, r in indexed if i == identifier and a == arm)
            if not rounds or rounds != list(range(1, max(rounds)+1)) or (max(rounds) < 3 and not indexed[(identifier, arm, max(rounds))]["success"] and (identifier, arm, max(rounds)) not in terminal_failures):
                incomplete.append({"id": identifier, "arm": arm})
    return {"schema": "ladder-summary.v1", "planned_n": 80, "observed_rounds": len(indexed),
            "unused_round_budget": 720-len(indexed), "incomplete_trajectories": incomplete,
            "status": "incomplete" if incomplete else "complete",
            "MDE": {"all": {"n": 80, "approximate_pp": 15, "type": "task_board_planning_threshold"}},
            "main_table": table, "observation_unit": "problem; per-round rates use separate denominators"}


def summarize_metamorphic(planned_ids, observations, human_reviews):
    """T11 rates by transformation; a complete problem is the pooled unit."""
    from decision_interventions import false_positive_decision
    if len(planned_ids) != 300 or len(set(planned_ids)) != 300:
        raise ValueError("T11 requires 300 distinct problems")
    kinds = ("unit_scale", "variable_rename", "percent_ratio")
    indexed, flags = {}, []
    for row in observations:
        key = (row["case_id"], row["kind"])
        if row["case_id"] not in planned_ids or row["kind"] not in kinds or key in indexed:
            raise ValueError("Invalid or duplicated transformation observation")
        if type(row["valid_pair"]) is not bool or (row["valid_pair"] and type(row["violation"]) is not bool) or (not row["valid_pair"] and row["violation"] is not None):
            raise ValueError("An invalid model pair cannot be an observed equivariance verdict")
        indexed[key] = row
        if row["violation"]:
            flags.append(row["case_id"] + "__" + row["kind"])
    def cell(values):
        n, k = len(values), sum(values)
        return {"k": k, "n": n, "rate": k/n if n else None, "exact_ci95": exact_binomial_interval(k, n) if n else None}
    by_kind = {}
    for kind in kinds:
        valid = [r for (i, k), r in indexed.items() if k == kind and r["valid_pair"]]
        by_kind[kind] = {**cell([r["violation"] for r in valid]), "planned_n": 300,
                         "invalid_n": sum(not r["valid_pair"] for (i, k), r in indexed.items() if k == kind),
                         "unobserved_n": 300-sum(k == kind for i, k in indexed)}
    complete = [i for i in planned_ids if all(indexed.get((i, k), {}).get("valid_pair", False) for k in kinds)]
    problem_rate = cell([any(indexed[(i, k)]["violation"] for k in kinds) for i in complete])
    human = false_positive_decision(flags, human_reviews)
    return {"schema": "metamorphic-summary.v1", "planned_n": 300, "observed_pairs": len(indexed),
            "by_transformation": by_kind, "any_violation_complete_problem": problem_rate,
            "incomplete_problem_n": 300-len(complete), "human_false_positive": human,
            "status": "discarded" if human["discard_module"] else "awaiting_complete_inputs_and_human_validation",
            "observation_unit": "one problem within each transform; one complete problem for any-transform rate"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-check", action="store_true")
    parser.add_argument("--readings", action="store_true")
    parser.add_argument("--rescore", action="store_true")
    parser.add_argument("--geometry", action="store_true")
    parser.add_argument("--baselines", action="store_true")
    parser.add_argument("--tables", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--consistency-prepare", action="store_true")
    parser.add_argument("--consistency-score", action="store_true")
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--out", type=Path, default=OUTPUT)
    args = parser.parse_args()
    action = (write_freeze if args.freeze_check else write_readings if args.readings else write_rescore if args.rescore
              else write_geometry if args.geometry else write_baselines if args.baselines else write_tables if args.tables
              else check_replay if args.check else prepare_consistency if args.consistency_prepare
              else score_consistency if args.consistency_score else None)
    if action is None:
        parser.error("Select --freeze-check, --readings, --rescore, --geometry, --baselines, --tables or --check")
    result = action(args.source, args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("passed", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
