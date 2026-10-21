"""One paired construction cohort; generation and pre-call checks only."""
import argparse
import copy
import hashlib
import json
import math
import random
import re
import sys
from fractions import Fraction
from pathlib import Path

sys.dont_write_bytecode = True
from language_instances import FORBIDDEN, normalized
from language_io_guard import zero_call_guard, prompt_io_guard

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "实验" / "结构构造_2026-10-21_exec_01"
SEED = 2026102101
DOMAINS = {
    "dispatch": ["转车登记", "冷房暂存", "空车返程", "货签重贴", "路线复查", "车门封验",
                 "货箱清点", "油量记录", "托盘回收", "预约改期", "车辆清洗", "通行登记"],
    "staffing": ["窗口交接", "跨站支援", "表单重填", "预约改签", "柜台轮换", "证件核对",
                 "电话回访", "物资领取", "培训签到", "午间换班", "档案归还", "钥匙登记"],
    "workshop": ["夹具拆装", "冷机启动", "原料转运", "刀具归还", "量具校验", "废料回收",
                 "工单复查", "包装重封", "工位清扫", "润滑登记", "托架更换", "成品入库"],
}
PRIVATE_KEYS = ["truth", "terms", "theta", "activeFactor", "pair_id", "seed", "domain",
                "attempt", "answer", "positive_atom", "negative_atom", "history_sha256"]
FORBIDDEN_WORDS = sorted(set(FORBIDDEN + PRIVATE_KEYS + [
    "系数", "权重", "目标公式", "答案", "标准解", "ground truth", "cost coefficient",
]))
PUBLIC_KEYS = {"description", "facts", "logs", "dictionary", "histories", "deployment"}


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode("utf-8")).hexdigest()


def create(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2))
        stream.write("\n")


def paths(attempt):
    suffix = "" if attempt == 1 else f".attempt{attempt}"
    return OUT / f"cases{suffix}.jsonl", OUT / f"truth{suffix}.jsonl"


def read_lines(path):
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def event_log(attempt, events, direction):
    """direction is an observed qualitative change, never a coefficient."""
    if attempt == 1:
        event = "，".join(f"{label}发生了{count}次" for label, count in events)
        result = {0: "与此前相同", 1: "比此前增加", -1: "比此前减少"}[direction]
        return event + "；其余记录未变，留待处理的份额" + result + "。"
    if attempt == 2:
        # The single-event probe is a retraction, reversing the observed effect.
        retract = len(events) == 1 and direction != 0
        event = "，同时".join(f"{label}{'撤回' if retract else '新增'}{count}次" for label, count in events)
        effect = -direction if retract else direction
        result = {0: "没有变化", 1: "增加了", -1: "减少了"}[effect]
        return event + "；其余记录未变，交班前后的待办份额" + result + "。"
    if attempt == 3:
        retract = len(events) == 1 and direction != 0
        event = "与".join(f"{count}次{label}" for label, count in events)
        effect = -direction if retract else direction
        result = {0: "没有变化", 1: "增加了", -1: "减少了"}[effect]
        line = "复核后保留记录：" + ("撤销" if retract else "计入") + event
        line += "；其余记录未变，待办份额" + result + "。"
        if direction:
            rejected = "减少了" if effect > 0 else "增加了"
            line += "此前有人说“待办份额" + rejected + "”，但这条说法已作废。"
        return line
    raise ValueError("Only three prespecified surfaces are allowed")


def generate(attempt):
    if not OUT.is_dir():
        raise FileNotFoundError("Step 1 directory is required")
    case_path, truth_path = paths(attempt)
    if case_path.exists() or truth_path.exists():
        raise FileExistsError("Never replace generated evidence")
    if attempt > 1:
        previous = json.loads((OUT / f"rule_gate.attempt{attempt-1}.json").read_text("utf-8"))
        if previous["correct"] < 42:
            raise ValueError("Regeneration is prohibited after a passing rule gate")
    cases, truths, inventory = [], [], []
    for pair in range(30):
        domain = list(DOMAINS)[pair // 10]
        seed = SEED + pair
        # Every surface keeps the same semantics, seed and histories.
        rng = random.Random(seed)
        labels = DOMAINS[domain].copy()
        rng.shuffle(labels)
        dictionary = [{"id": f"x{j}", "measurement": label, "unit": "次"} for j, label in enumerate(labels)]
        i, j = rng.sample(range(12), 2)
        a, b = rng.choice([(a, b) for a in range(1, 8) for b in range(1, 8) if math.gcd(a, b) == 1])
        histories = []
        for h in range(6):
            common = rng.randrange(1, 8)
            histories.append({"actions": [
                {"id": f"a{k}", "known_cost": k, "atoms": {f"x{n}": common for n in range(12)}}
                for k in range(4)], "chosen": "a0"})
        deployment = {"actions": [
            {"id": f"a{k}", "known_cost": k, "atoms": {f"x{n}": rng.randrange(8) for n in range(12)}}
            for k in range(4)]}
        row_order = list(range(12))
        rng.shuffle(row_order)
        sign_order = rng.sample([-1, 1], 2)
        for member, sign in enumerate(sign_order):
            # Ten isolated invariances, one joint invariance and one directional probe.
            # A cross-record ratio and orientation must both be constructed.
            records = [event_log(attempt, [(labels[n], 1)], 0) for n in range(12) if n not in (i, j)]
            records += [event_log(attempt, [(labels[i], b), (labels[j], a)], 0),
                        event_log(attempt, [(labels[i], 1)], sign)]
            public = {
                "description": "现场交接记录。需要解释留待处理份额的日增量，它允许增加或减少。",
                "facts": ["各类登记使用同一份交接台账。记录中的其他流程没有同时变动。"],
                "logs": [records[n] for n in row_order], "dictionary": copy.deepcopy(dictionary),
                "histories": copy.deepcopy(histories), "deployment": copy.deepcopy(deployment),
            }
            instance_id = f"i{2 * pair + member + 1:03d}"
            cases.append({"id": instance_id, "public": public})
            truths.append({"id": instance_id, "pair_id": f"p{pair+1:02d}",
                           "terms": {f"x{i}": sign * a, f"x{j}": -sign * b}, "scale": 1})
        inventory.append({"pair_id": f"p{pair+1:02d}", "seed": seed, "domain": domain,
                          "ids": [r["id"] for r in cases[-2:]], "history_sha256": digest(encode(histories))})
    create(case_path, "\n".join(encode(row) for row in cases))
    create(truth_path, "\n".join(encode(row) for row in truths))
    create(OUT / f"inventory.attempt{attempt}.json", inventory)
    summary = {"attempt": attempt, "cases": len(read_lines(case_path)), "truth": len(read_lines(truth_path)),
               "pairs_identical_histories": sum(encode(cases[k]["public"]["histories"]) == encode(cases[k+1]["public"]["histories"]) for k in range(0, 60, 2)),
               "cases_sha256": digest(case_path.read_bytes()), "truth_sha256": digest(truth_path.read_bytes()),
               "model_calls": 0}
    assert summary["cases"] == summary["truth"] == 60
    assert summary["pairs_identical_histories"] == 30
    create(OUT / f"generation.attempt{attempt}.json", summary)
    return summary


def validate_public(public):
    if set(public) != PUBLIC_KEYS:
        raise ValueError("Unexpected public metadata or private field")
    if len(public["dictionary"]) != 12:
        raise ValueError("Atom dictionary size")
    for j, atom in enumerate(public["dictionary"]):
        if set(atom) != {"id", "measurement", "unit"} or atom["id"] != f"x{j}":
            raise ValueError("Dictionary metadata or candidate formula")
    text = normalized("\n".join([public["description"], *public["facts"], *public["logs"]]))
    forbidden = [*FORBIDDEN_WORDS, *[f"x{j}" for j in range(12)],
                 "cases.jsonl", "truth.jsonl", ".json", ".csv", ":\\", "../", "./"]
    leaks = [word for word in forbidden if normalized(word) in text]
    if leaks or re.search(r"[=×*]|\b[a-z]\d+\b|[0-9]\s*[-+]\s*[0-9]", text):
        raise ValueError("Forbidden text content: " + repr(leaks))
    if len(public["histories"]) != 6:
        raise ValueError("History count")
    for context in public["histories"]:
        if set(context) != {"actions", "chosen"} or context["chosen"] != "a0":
            raise ValueError("History metadata or choice leakage")
        for k, action in enumerate(context["actions"]):
            if set(action) != {"id", "known_cost", "atoms"} or action["id"] != f"a{k}" or action["known_cost"] != k:
                raise ValueError("History numeric or metadata leakage")
            if set(action["atoms"]) != {f"x{j}" for j in range(12)}:
                raise ValueError("Numeric dictionary mismatch")
            if len(set(action["atoms"].values())) != 1 or action["atoms"] != context["actions"][0]["atoms"]:
                raise ValueError("Nonzero historical atom contrast; identifiable numeric information")
    if set(public["deployment"]) != {"actions"}:
        raise ValueError("Deployment metadata")
    for k, action in enumerate(public["deployment"]["actions"]):
        if set(action) != {"id", "known_cost", "atoms"} or action["id"] != f"a{k}" or action["known_cost"] != k:
            raise ValueError("Deployment numeric or metadata leakage")
        if set(action["atoms"]) != {f"x{j}" for j in range(12)}:
            raise ValueError("Deployment atom keys")
    return True


def public_payload(case):
    with prompt_io_guard():
        public = copy.deepcopy(case["public"])
        validate_public(public)
        return encode(public)  # no seed, ordinal, file path, pair or private truth


def canonical_terms(terms):
    if not isinstance(terms, dict) or not terms:
        raise ValueError("Empty structure")
    values = {k: Fraction(str(v)) for k, v in terms.items() if Fraction(str(v))}
    if not values:
        raise ValueError("Zero structure")
    unit = abs(values[sorted(values)[0]])
    return tuple((k, v / unit) for k, v in sorted(values.items()))


def leakage_gate(attempt):
    case_path, truth_path = paths(attempt)
    cases, truths = read_lines(case_path), read_lines(truth_path)
    assert len(cases) == len(truths) == 60
    for case, truth in zip(cases, truths):
        assert set(case) == {"id", "public"} and case["id"] == truth["id"]
        assert len(truth["terms"]) == 2
        a, b = truth["terms"].values()
        assert a * b < 0 and math.gcd(abs(a), abs(b)) == 1 and 1 <= abs(a) <= 7 and 1 <= abs(b) <= 7
        public_payload(case)
    history_hashes, numeric_hashes = [], []
    for k in range(0, 60, 2):
        a, b = cases[k]["public"], cases[k+1]["public"]
        assert a["logs"] != b["logs"]
        assert {name: val for name, val in a.items() if name != "logs"} == {name: val for name, val in b.items() if name != "logs"}
        assert canonical_terms(truths[k]["terms"]) != canonical_terms(truths[k+1]["terms"])
        history_hashes.append([digest(encode(v["histories"])) for v in (a, b)])
        numeric_hashes.append([digest(encode({name: v[name] for name in ("histories", "deployment")})) for v in (a, b)])
    # Negative controls are corrupted copies in memory, never replacement evidence.
    failed_as_expected = []
    for label, field, poison in [("atom_id", "logs", "x0"), ("truth_key", "facts", "activeFactor"),
                                  ("forbidden_word", "logs", "真实权重"), ("answer_label", "facts", "标准答案"),
                                  ("filename", "logs", "truth.jsonl"), ("formula", "logs", "2*x1-x2")]:
        bad = copy.deepcopy(cases[0]["public"])
        bad[field].append(poison)
        try:
            validate_public(bad)
        except ValueError:
            failed_as_expected.append(label)
        else:
            raise AssertionError("Leakage negative control unexpectedly passed: " + label)
    for label in ("metadata", "history_contrast", "history_choice", "dictionary_metadata", "deployment_metadata"):
        bad = copy.deepcopy(cases[0]["public"])
        if label == "metadata":
            bad["seed"] = SEED
        elif label == "history_contrast":
            bad["histories"][0]["actions"][1]["atoms"]["x0"] += 1
        elif label == "history_choice":
            bad["histories"][0]["chosen"] = "a1"
        elif label == "dictionary_metadata":
            bad["dictionary"][0]["truth"] = True
        else:
            bad["deployment"]["truth"] = True
        try:
            validate_public(bad)
        except ValueError:
            failed_as_expected.append(label)
        else:
            raise AssertionError("Leakage negative control unexpectedly passed: " + label)
    # Every pair differs only in event relations. Histories have zero atom contrasts,
    # so ALL 12-dimensional signed coefficient vectors give the same chosen actions.
    result = {"attempt": attempt, "passed": True, "cases_checked": 60,
              "identical_history_pairs": 30, "identical_all_numeric_pairs": 30,
              "history_difference_rank": 0, "compatible_structure_dimension": 12,
              "negative_tests_rejected": failed_as_expected, "negative_tests_count": len(failed_as_expected),
              "history_hashes": history_hashes, "numeric_hashes": numeric_hashes,
              "forbidden_words": FORBIDDEN_WORDS, "model_calls": 0,
              "scope": "Finite forbidden-string and schema gates plus exact history nonidentifiability; not a semantic-leakage proof. Rule gate is separate."}
    create(OUT / f"leakage_gate.attempt{attempt}.json", result)
    return {k: v for k, v in result.items() if k not in ("history_hashes", "numeric_hashes", "forbidden_words")}


def rule_gate(attempt):
    from language_instances import signed_event_rule
    from experiment_runtime import sha
    gate = json.loads((OUT / f"leakage_gate.attempt{attempt}.json").read_text("utf-8"))
    assert gate["passed"]
    frozen = json.loads((OUT / "precall_gate_spec.json").read_text("utf-8"))
    assert frozen["rule_source_sha256"] == sha(ROOT / "research" / "language_instances.py")
    assert frozen["generator_source_sha256"] == sha(Path(__file__))
    cases, truths = [read_lines(p) for p in paths(attempt)]
    predictions = []
    for case in cases:
        # This function receives no histories, seed, filename, id or truth.
        with prompt_io_guard():
            try:
                proposal = signed_event_rule(case["public"]["logs"], case["public"]["dictionary"])
                predictions.append({"id": case["id"], "proposal": proposal, "error": None})
            except Exception as error:
                predictions.append({"id": case["id"], "proposal": None, "error": str(error)})
    create(OUT / f"rule_predictions.attempt{attempt}.jsonl", "\n".join(encode(row) for row in predictions))
    for row, truth in zip(predictions, truths):
        row["correct"] = bool(row["proposal"] and canonical_terms(row["proposal"]["hypotheses"][0]["terms"]) == canonical_terms(truth["terms"]))
    correct = sum(row["correct"] for row in predictions)
    collapsed = sum(predictions[k]["proposal"] is not None and predictions[k+1]["proposal"] is not None and
                    canonical_terms(predictions[k]["proposal"]["hypotheses"][0]["terms"]) == canonical_terms(predictions[k+1]["proposal"]["hypotheses"][0]["terms"])
                    for k in range(0, 60, 2))
    result = {"attempt": attempt, "correct": correct, "denominator": 60, "threshold": 42,
              "gate_passed": correct < 42, "collapse_count": collapsed, "collapse_denominator": 30,
              "errors": sum(row["error"] is not None for row in predictions), "rows": predictions,
              "model_calls": 0, "rule_source_sha256": frozen["rule_source_sha256"]}
    create(OUT / f"rule_gate.attempt{attempt}.json", result)
    return {k: v for k, v in result.items() if k != "rows"}


def freeze_gates():
    from experiment_runtime import sha
    spec = {"seed_base": SEED, "pairs": 30, "instances": 60,
            "seed_domain_mapping": [{"seed": SEED + k, "domain": list(DOMAINS)[k // 10]} for k in range(30)],
            "attempts": {"1": "joint invariance plus direct directional event", "2": "joint invariance plus retraction", "3": "cross-sentence correction with rejected contrary claim"},
            "rule_threshold": 42, "maximum_attempts": 3, "maximum_model_calls": 240,
            "model_calls_before_gate_passes": 0, "pilots": 0, "retries": 0,
            "rule_policy": "One frozen text-to-constraint rule, unchanged across all three attempts. No truth or numeric history access. It is a stronger compositional rule, not a word-presence-only strawman.",
            "forbidden_words": FORBIDDEN_WORDS,
            "rule_source_sha256": sha(ROOT / "research" / "language_instances.py"),
            "generator_source_sha256": sha(Path(__file__)),
            "regeneration_policy": "Keep initial cases.jsonl and truth.jsonl byte-identical; later surfaces use attempt-numbered files in the same batch. Never create a second batch.",
            "stop_policy": "If attempt 3 has rule correctness >=42/60, write infeasible evidence and stop with zero calls. Model and audit outcomes then remain unmeasured, never zero-filled."}
    create(OUT / "precall_gate_spec.json", spec)
    create(OUT / "precall_gate_spec.sha256", sha(OUT / "precall_gate_spec.json"))
    return {"precall_gate_spec_sha256": sha(OUT / "precall_gate_spec.json"), "rule_source_sha256": spec["rule_source_sha256"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("generate", "leakage", "rule", "freeze-gates"))
    parser.add_argument("--attempt", type=int, choices=(1, 2, 3), default=1)
    args = parser.parse_args()
    with zero_call_guard():
        result = freeze_gates() if args.mode == "freeze-gates" else {"generate": generate, "leakage": leakage_gate, "rule": rule_gate}[args.mode](args.attempt)
    print(json.dumps(result, ensure_ascii=False, indent=2))
