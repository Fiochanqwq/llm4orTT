"""Blind annotation packages and nominal reliability for independently filled sheets."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from replay import ROOT, SOURCE, OUTPUT, read, save, sha

LABELS = ("unique", "ambiguous", "insufficient")


def nominal_alpha(pairs):
    valid = [(a, b) for a, b in pairs if a is not None and b is not None]
    if any(a not in LABELS or b not in LABELS for a, b in valid):
        raise ValueError("Unknown reading_status")
    if not valid:
        return {"alpha": None, "complete_pairs": 0, "status": "awaiting_human_annotations"}
    counts = Counter(v for pair in valid for v in pair)
    total = 2 * len(valid)
    observed = sum(a != b for a, b in valid) / len(valid)
    expected = 1 - sum(k * (k - 1) for k in counts.values()) / (total * (total - 1))
    return {"alpha": 1 - observed / expected if expected else None, "complete_pairs": len(valid),
            "observed_disagreement": observed, "expected_disagreement": expected,
            "label_counts": dict(counts), "status": "computed" if expected else "undefined_no_label_variation"}


def agreement(left, right):
    from decision_geometry import compare_models, compile_model
    def index(data):
        entries = data["annotations"]
        if len(entries) != len({r["id"] for r in entries}):
            raise ValueError("Duplicate annotation IDs")
        for row in entries:
            if row["reading_status"] is not None and row["reading_status"] not in LABELS:
                raise ValueError("Unknown reading_status")
            for model in row["models"]:
                compile_model(model)
            if row["reading_status"] == "unique" and len(row["models"]) != 1:
                raise ValueError("A unique reading requires one complete model")
            if row["reading_status"] == "ambiguous" and len(row["models"]) < 2:
                raise ValueError("Ambiguity requires at least two explicit models")
        return {r["id"]: r for r in entries}
    a, b = index(left), index(right)
    if set(a) != set(b):
        raise ValueError("Annotators must return the same case IDs")
    if left["annotator_id"] == right["annotator_id"]:
        raise ValueError("Two distinct annotator IDs are required")
    alpha = nominal_alpha([(a[i]["reading_status"], b[i]["reading_status"]) for i in a])
    model_checks = []
    def covered(first, second):
        for model in first:
            if not any((cmp := compare_models(model, other))["feasible_sets_equal"] and cmp["optimal_faces_equal"] for other in second):
                return False
        return True
    for identifier in a:
        x, y = a[identifier], b[identifier]
        if x["reading_status"] is None or y["reading_status"] is None or not x["models"] or not y["models"]:
            continue
        model_checks.append({"id": identifier, "equal": covered(x["models"], y["models"]) and covered(y["models"], x["models"])})
    return {"schema": "annotation-agreement.v1", "n": len(a), "reading_status_nominal_alpha": alpha,
            "exact_reading_set_agreement": {"n": len(model_checks), "equal": sum(r["equal"] for r in model_checks),
                "rate": sum(r["equal"] for r in model_checks)/len(model_checks) if model_checks else None, "rows": model_checks},
            "interpretation": "Alpha measures the common reading-status categories, not mathematical correctness. Full model agreement is reported separately."}


def select_cases(source):
    frozen = read(source / "cases.private.json")
    admission = read(source / "admission.json")
    heldout = [c["id"] for c in frozen if c["split"] == "heldout"]
    development = [c["id"] for c in frozen if c["split"] == "development"]
    pool = admission["unselectedEligible"] + development
    assert len(heldout) == 60 and len(set(pool)) == 100 and not set(heldout) & set(pool)
    ranked = sorted(pool, key=lambda i: hashlib.sha256(("annotation-20261022:" + i).encode()).hexdigest())
    return heldout, ranked[:90], set(development)


def package(source=SOURCE, output=OUTPUT, size=60):
    prereg = read(output / "prereg.json")["stages"]["T3" if size == 60 else "T4"]
    assert prereg["n"] == size and prereg["budget_CNY"] == 0
    heldout, additional, development = select_cases(source)
    ids = heldout if size == 60 else heldout + additional
    raw_path = source / "source-snapshot/datasets/llm-grounding-v1/nl4opt-test.jsonl"
    raw = {}
    for line in raw_path.read_text("utf-8-sig").splitlines():
        raw.update(json.loads(line))
    public = [{"id": i, "text": raw[i]["document"], "variables": raw[i]["vars"]} for i in ids]
    assert len(public) == size and all(len(c["variables"]) == 2 for c in public)
    dest = output / ("annotation" if size == 60 else "annotation_150")
    # Regeneration must never overwrite returned human work.
    if dest.exists():
        raise FileExistsError("Annotation package already exists; preserve annotator work")
    dest.mkdir(parents=True)
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
        "required": ["annotator_id", "annotations"], "additionalProperties": False,
        "properties": {"annotator_id": {"type": "string", "minLength": 1},
            "annotations": {"type": "array", "minItems": size, "maxItems": size, "items": {
                "type": "object", "required": ["id", "reading_status", "models", "notes"], "additionalProperties": False,
                "properties": {"id": {"type": "string", "enum": ids}, "reading_status": {"enum": [None, *LABELS]},
                    "notes": {"type": "string"}, "models": {"type": "array", "items": {"$ref": "#/$defs/model"}}}}}},
        "$defs": {"number": {"type": ["number", "string"]}, "model": {
            "type": "object", "required": ["sense", "objective", "constraints"], "additionalProperties": False,
            "properties": {"sense": {"enum": ["min", "max"]}, "objective": {"type": "array", "minItems": 2, "maxItems": 2, "items": {"$ref": "#/$defs/number"}},
                "constraints": {"type": "array", "maxItems": 32, "items": {"type": "object", "required": ["a", "op", "b"], "additionalProperties": False,
                    "properties": {"a": {"type": "array", "minItems": 2, "maxItems": 2, "items": {"$ref": "#/$defs/number"}},
                        "op": {"enum": ["<=", ">=", "="]}, "b": {"$ref": "#/$defs/number"}}}}}}}}
    save(dest / "schema.json", schema)
    pages = []
    for case in public:
        pages.append(f'# 题目 {case["id"]}\n\n{case["text"]}\n\nx0：{case["variables"][0]}；x1：{case["variables"][1]}。\n\n'
            '读法状态：□ 唯一　□ 多种合理读法　□ 信息不足\n\n目标方向与系数：________\n\n'
            '| 原文约束片段 | a0 | a1 | 关系 | b |\n|---|---|---|---|---|\n| 待填写 | | | | |\n\n'
            '按 a0·x0 + a1·x1 与 b 的关系填写；每条约束新增一行，歧义读法分别填写完整模型。\n\n备注：________\n')
    sheet = '\n<div style="break-after: page;"></div>\n\n'.join(pages)
    (dest / "sheet.md").write_text(sheet, "utf-8")
    instructions = (f'# 独立标注说明\n\n本包含 {size} 道题，每题预计 4 分钟；独立完成后保存 annotations.json。\n\n'
        '仅根据原文与给定变量目录标注。变量连续且非负，所有额外上下界须显式填写。\n'
        '先填写目标，再逐条转换约束；系数可以写成有理数字符串。多种合理读法分别写完整模型。\n'
        'reading_status 使用 unique、ambiguous 或 insufficient；未完成保留 null。\n'
        'models 使用 schema.json 的模型结构。unique 填一个模型，ambiguous 至少填两个；信息不足时写明缺失信息。\n'
        '互相交流在两份独立结果锁定之后进行。标注期间关闭项目报告和历史模型回答。\n'
        '本包只含原文、变量目录和空白模板，原始官方答案及生成模型另由协调者保存。\n\n'
        '提交时保留 annotator_id 和题目 ID；勿修改原始题目。试标样例为人工构造，不进入评测。\n')
    (dest / "README.md").write_text(instructions, "utf-8")
    training = [
        {"id": "practice_1", "text": "两类物品总数不超过10，收益分别为2和3，最大化收益。", "variables": ["甲", "乙"],
         "reading_status": "unique", "models": [{"sense": "max", "objective": [2, 3], "constraints": [{"a": [1, 1], "op": "<=", "b": 10}]}]},
        {"id": "practice_2", "text": "乙至少占总数的四分之一，总数至少4，成本分别为1和2，最小化成本。", "variables": ["甲", "乙"],
         "reading_status": "unique", "models": [{"sense": "min", "objective": [1, 2], "constraints": [{"a": [-1, 3], "op": ">=", "b": 0}, {"a": [1, 1], "op": ">=", "b": 4}]}]},
        {"id": "practice_3", "text": "甲乙都可以生产，但未说明目标及资源限制。", "variables": ["甲", "乙"], "reading_status": "insufficient", "models": []}]
    save(dest / "practice.json", {"synthetic_training_only": True, "examples": training})
    copies = []
    for name in ("annotator_1", "annotator_2"):
        directory = dest / name
        directory.mkdir()
        for filename in ("sheet.md", "README.md", "schema.json", "practice.json"):
            (directory / filename).write_bytes((dest / filename).read_bytes())
        save(directory / "annotations.json", {"annotator_id": name, "annotations": [
            {"id": i, "reading_status": None, "models": [], "notes": ""} for i in ids]})
        copies.append({"path": directory.relative_to(output).as_posix(), "delivery_confirmed": False, "completed": False})
    manifest = {"schema": "annotation-package.v1", "n": size, "ids": ids, "raw_source_sha256": sha(raw_path),
        "heldout_ids": heldout, "new_annotation_ids": additional if size == 150 else [],
        "new_annotation_previously_development_ids": sorted(set(additional) & development) if size == 150 else [],
        "copies": copies, "blinding_fields": ["id", "text", "variables"], "human_work_status": "prepared_awaiting_delivery_and_annotation"}
    save(output / f"annotation-{size}-manifest.json", manifest)
    result = agreement(read(dest / "annotator_1/annotations.json"), read(dest / "annotator_2/annotations.json"))
    save(output / f"annotation-{size}-agreement.json", result)
    return manifest


def package_transform_reviews(source=SOURCE, output=OUTPUT):
    """Prepare T11 semantic checks alongside T3; this does not fill the 300-case quota."""
    from decision_interventions import source_span, transform_problem
    prereg = read(output / "prereg.json")
    ids = prereg["stages"]["T11"]["human_review_input_ids"]
    heldout, _, _ = select_cases(source)
    if ids != heldout:
        raise ValueError("The initial T11 review package must match the existing T3 cases")
    destination = output / "T11-review"
    if destination.exists() or (output / "T11-review-manifest.json").exists():
        raise ValueError("Never overwrite a review package or returned human work")
    raw_path = source / "source-snapshot/datasets/llm-grounding-v1/nl4opt-test.jsonl"
    raw = {}
    for line in raw_path.read_text("utf-8-sig").splitlines():
        raw.update(json.loads(line))
    entries, unsupported = [], []
    for identifier in ids:
        record = raw[identifier]
        public = {"id": identifier, "text": record["document"], "variables": record["vars"]}
        spans, rename_issue = [], None
        mapping = record["var_mention_to_first_var"]
        for span in record.get("spans", []):
            if span.get("label") == "VAR":
                mention = span.get("text", public["text"][span["start"]:span["end"]])
                try:
                    source_span(public["text"], {"start": span["start"], "end": span["end"], "text": mention})
                except ValueError as exc:
                    rename_issue = str(exc)
                    continue
                canonical = mapping.get(mention, mention)
                if canonical in public["variables"]:
                    spans.append({"start": span["start"], "end": span["end"], "text": mention,
                                  "variable_index": public["variables"].index(canonical)})
                else:
                    rename_issue = "An annotated variable mention is not mapped to the supplied catalog"
        for kind in ("unit_scale", "variable_rename", "percent_ratio"):
            try:
                if kind == "variable_rename" and rename_issue:
                    raise ValueError(rename_issue)
                transformed = transform_problem(public, kind, rename_spans=spans)
            except ValueError as exc:
                unsupported.append({"id": identifier, "kind": kind, "reason": str(exc)})
                continue
            entries.append({"id": identifier + "__" + kind, "case_id": identifier,
                            "original": public, "transformed": transformed})
    destination.mkdir(parents=True)
    instructions = ("# T11 变换保义性核验\n\n"
                    "这是已有 T3 题目的补充核验材料，完整实验队列仍按任务板定义。\n"
                    "独立比较每条原文、改写和变量目录，判断是否仍表达同一个优化问题。\n"
                    "单位缩放允许改变决策变量的计量单位；需求、资源总量和目标含义应保持。\n"
                    "变量改名检查漏改、误改及代词指代；比例改写检查比例的基数和方向。\n"
                    "在 annotations.json 填写 meaning_preserved 为 true 或 false，并填写 reason；未判断保留 null。\n"
                    "reviewer_id 填实际标注者代号。不要互看另一份答案。本包不含模型响应或正确答案。\n"
                    "本包只核验文本保义性；模型违例产生后，假阳率需要另行核验实际告警。\n")
    copies = []
    for annotator in ("annotator_1", "annotator_2"):
        directory = destination / annotator
        directory.mkdir()
        save(directory / "problems.json", {"entries": entries})
        save(directory / "annotations.json", {"reviewer_id": "", "annotations": [
            {"id": e["id"], "meaning_preserved": None, "reason": ""} for e in entries]})
        (directory / "README.md").write_text(instructions, "utf-8")
        copies.append({"path": directory.relative_to(output).as_posix(), "delivery_confirmed": False, "completed": False})
    manifest = {"task": "T11", "status": "prepared_awaiting_delivery_and_human_review", "experiment_complete": False,
                "planned_experiment_n": 300, "source_T3_n": len(ids), "prepared_transformations": len(entries),
                "complete_triplet_ids": [i for i in ids if sum(e["case_id"] == i for e in entries) == 3],
                "unsupported": unsupported, "copies": copies, "raw_source_sha256": sha(raw_path),
                "model_calls": 0, "false_positive_rate": None}
    save(output / "T11-review-manifest.json", manifest)
    return {k: v for k, v in manifest.items() if k not in ("unsupported", "complete_triplet_ids")}


def reuse_references(source=SOURCE, output=OUTPUT, previous=OUTPUT):
    """Import published answers for the previously selected IDs, without new labels."""
    from decision_contract_study import canonical_record
    from decision_geometry import analyze_model
    destination = output / "reference-reuse.json"
    if destination.exists():
        raise FileExistsError("Reference reuse already exists; preserve the completed record")
    registered = read(output / "prereg.json")
    if registered["n"]["T3"] != 60 or registered["n"]["T4"] != 150:
        raise ValueError("Registered sample sizes changed")
    small = read(previous / "annotation-60-manifest.json")["ids"]
    large = read(previous / "annotation-150-manifest.json")["ids"]
    if len(set(small)) != 60 or len(small) != 60 or len(set(large)) != 150 or len(large) != 150 or not set(small) <= set(large):
        raise ValueError("The original nested sample manifests are invalid")
    raw_path = source / "source-snapshot/datasets/llm-grounding-v1/nl4opt-test.jsonl"
    raw, locations = {}, {}
    for number, line in enumerate(raw_path.read_text("utf-8-sig").splitlines(), 1):
        for identifier, record in json.loads(line).items():
            if identifier in raw:
                raise ValueError("Duplicate source identifiers")
            raw[identifier], locations[identifier] = record, number
    sensitivity_path = previous / "admissible_readings.json"
    sensitivity = read(sensitivity_path)["variants"]
    records = []
    for identifier in large:
        record = raw[identifier]
        model = canonical_record(identifier, record)
        geometry = analyze_model(model)
        if geometry["status"] != "optimal":
            raise ValueError("Previously eligible official reference lost a finite optimum")
        records.append({"id": identifier, "text": record["document"], "variables": record["vars"],
                        "official_model": model, "geometry": geometry,
                        "source_line": locations[identifier],
                        "source_record_sha256": hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                        "reading_status": None, "reading_status_reason": "Not assessed by independent annotators",
                        "sensitivity_paths": {name: str(sensitivity_path.relative_to(ROOT)).replace('\\', '/') + '#/variants/' + name + '/' + identifier
                                              for name, policy in sensitivity.items() if identifier in policy}})
    result = {"schema": "published-reference-reuse.v1", "reference_source": raw_path.relative_to(ROOT).as_posix(),
              "source_sha256": sha(raw_path), "n": len(records), "records": records,
              "reference_kind": "single_published_structured_reference",
              "mathematical_check": "All imported models parse exactly and have a finite attained optimum; this is not an independent language annotation.",
              "human_alpha": {"value": None, "status": "not_applicable_single_reference_source"},
              "model_agreement": {"value": None, "status": "no_independent_per_problem_AI_labels"},
              "sensitivity_source_sha256": sha(sensitivity_path), "model_calls": 0}
    save(destination, result)
    for size, ids in ((60, small), (150, large)):
        save(output / f"reference-{size}.json", {"n": size, "ids": ids, "models_source": "reference-reuse.json#/records",
             "original_manifest_sha256": sha(previous / f"annotation-{size}-manifest.json"),
             "all_ids_present": all(i in {r['id'] for r in records} for i in ids), "exact_checks_passed": True})
    return {"T3_n": len(small), "T4_n": len(large), "independent_problem_n": len(large), "passed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, choices=(60, 150))
    parser.add_argument("--left", type=Path)
    parser.add_argument("--right", type=Path)
    parser.add_argument("--transform-reviews", action="store_true")
    parser.add_argument("--reuse-references", action="store_true")
    parser.add_argument("--out", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.reuse_references:
        result = reuse_references(output=args.out)
    elif args.transform_reviews:
        result = package_transform_reviews(output=args.out)
    elif args.size:
        result = package(output=args.out, size=args.size)
    elif args.left and args.right:
        result = agreement(read(args.left), read(args.right))
        save(args.out, result)
    else:
        parser.error("Choose --size or supply --left --right --out")
    print(json.dumps({k: v for k, v in result.items() if k not in ("ids", "heldout_ids", "new_annotation_ids")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
