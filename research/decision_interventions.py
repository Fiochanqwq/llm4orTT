"""Exact T8 round measurements and T11 transformations; no network or label generation."""
from __future__ import annotations

from fractions import Fraction as F
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from decision_geometry import analyze_model, compare_models, compile_model, rational


def accepts(model, point):
    compiled = compile_model(model)
    if not isinstance(point, (list, tuple)) or len(point) != 2:
        raise ValueError("A witness must have exactly two coordinates")
    x, y = map(rational, point)
    return all(a*x + b*y <= c for a, b, c in compiled.rows)


def row_is_implied(model, row):
    """Check the whole feasible region, including rays, against one reference row."""
    compile_model(model)
    compile_model({"sense": "min", "objective": [0, 0], "constraints": [row]})
    geometry = analyze_model(model)
    if geometry["status"] == "infeasible":
        return None  # An empty model is not credited for preserving every row.
    a = list(map(rational, row["a"]))
    b = rational(row["b"])
    signs = (1, -1) if row["op"] == "=" else (1,) if row["op"] == "<=" else (-1,)
    for sign in signs:
        for point in geometry["vertices"]:
            if sign * sum(u*rational(v) for u, v in zip(a, point)) > sign*b:
                return False
        for ray in geometry["recession_rays"]:
            if sign * sum(u*rational(v) for u, v in zip(a, ray)) > 0:
                return False
    return True


def round_metrics(reference, before, after, previous_point=None):
    """Score privately; none of these reference-derived fields belongs in a prompt.

    Compliance literally records feasible membership of the previous point.
    Its correct membership is separate: some counterexamples must be excluded.
    Damage means losing a reference row implied by the previous feasible region.
    """
    compile_model(reference)
    result = {"compliance": None, "compliance_reason": "no_previous_witness",
              "reference_accepts_point": None, "point_membership_correct": None,
              "damage": None, "protected_rows": [], "damaged_rows": [],
              "damage_reason": None, "success": False, "valid": False}
    if previous_point is not None:
        result["reference_accepts_point"] = accepts(reference, previous_point)
    try:
        compile_model(after)
    except (ValueError, TypeError) as exc:
        result.update(compliance_reason="invalid_new_model", damage_reason="invalid_new_model", error=str(exc))
        return result
    result["valid"] = True
    comparison = compare_models(reference, after)
    result["success"] = comparison["equivalent"]
    if previous_point is not None:
        result["compliance"] = accepts(after, previous_point)
        result["compliance_reason"] = "observed"
        result["point_membership_correct"] = result["compliance"] == result["reference_accepts_point"]
    try:
        compile_model(before)
    except (ValueError, TypeError):
        result["damage_reason"] = "invalid_previous_model"
        return result
    if analyze_model(before)["status"] == "infeasible" or analyze_model(after)["status"] == "infeasible":
        result["damage_reason"] = "empty_feasible_region"
        return result
    for index, row in enumerate(reference["constraints"]):
        if row_is_implied(before, row):
            result["protected_rows"].append(index)
            if not row_is_implied(after, row):
                result["damaged_rows"].append(index)
    if not result["protected_rows"]:
        result["damage_reason"] = "no_previously_satisfied_reference_rows"
    else:
        result["damage"] = bool(result["damaged_rows"])
        result["damage_reason"] = "observed"
    return result


def source_span(text, span):
    """Check a supplied anchor verbatim; textual identity is not semantic validation."""
    start, end = span["start"], span["end"]
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
        raise ValueError("Invalid source span offsets")
    if text[start:end] != span["text"]:
        raise ValueError("Anchor does not match the original source")
    return {"start": start, "end": end, "text": text[start:end]}


def validate_ladder_cohort(cases):
    """The 60+20 quota is a requirement, not a reason to duplicate scarce cases."""
    ids = [c["id"] for c in cases]
    texts = [" ".join(c["text"].lower().split()) for c in cases]
    if len(ids) != 80 or len(set(ids)) != 80 or len(set(texts)) != 80:
        raise ValueError("T8 requires 80 distinct problems")
    protocols = {c["stratum_protocol"] for c in cases}
    if len(protocols) != 1:
        raise ValueError("Do not pool differently defined screening strata")
    counts = {s: sum(c["stratum"] == s for c in cases) for s in ("divergent", "all_consistent_wrong")}
    if counts != {"divergent": 60, "all_consistent_wrong": 20}:
        raise ValueError("T8 requires exactly 60 divergent and 20 all-consistent wrong problems")
    for case in cases:
        models = case["screening_models"]
        if len(models) < 2:
            raise ValueError("Screening evidence requires at least two complete models")
        compile_model(case["reference"])
        same = all(compare_models(models[0], model)["equivalent"] for model in models)
        if (case["stratum"] == "divergent") == same:
            raise ValueError("Stratum disagrees with the exact screening evidence")
        if same and compare_models(case["reference"], models[0])["equivalent"]:
            raise ValueError("An all-consistent correct problem is not in the wrong stratum")
    return counts


def ladder_request(case, before, peer, arm, round_number, anchor=None, allow_missing_anchor=False):
    """Build matched feedback from candidates only; private references are excluded."""
    from decision_contract_study import public_prompt, request
    if arm not in ("verdict", "point", "point+anchor") or type(round_number) is not int or not 1 <= round_number <= 3:
        raise ValueError("T8 has exactly three named arms and at most three rounds")
    comparison = compare_models(before, peer)
    witness = comparison["witnesses"][0] if comparison["witnesses"] else None
    payload = public_prompt(case)
    payload.update(candidate=before, peer_candidate=peer,
                   relation={k: comparison[k] for k in ("feasible_sets_equal", "optimal_faces_equal", "statuses_equal")},
                   instruction="Revise the candidate using the original text and the supplied feedback. Return the complete LP. Check all original requirements after each edit.")
    if arm != "verdict":
        payload["previous_witness"] = witness
    if arm == "point+anchor":
        if witness is not None:
            if anchor is None:
                if not allow_missing_anchor:
                    raise ValueError("A point+anchor request requires a source span for its witness row")
                payload["source_anchor"] = None
            # Enforce row identity as well as verbatim offsets. Semantic alignment
            # must be supplied in the input; matching text alone is insufficient.
            def rows(row):
                return compile_model({"sense": "min", "objective": [0, 0], "constraints": [row]}).rows
            if anchor is not None:
                if rows(anchor["row"]) != rows(witness["target_row"]):
                    raise ValueError("Source anchor is assigned to a different witness row")
                payload["source_anchor"] = source_span(case["text"], anchor)
        else:
            payload["source_anchor"] = None
    return {"request": request(f'{case["id"]}_{arm.replace("+", "_")}_r{round_number}', payload),
            "scoring_context": {"previous_point": witness["point"] if witness else None,
                                "witness_exposed": arm != "verdict" and witness is not None,
                                "anchor_exposed": arm == "point+anchor" and witness is not None and anchor is not None}}


def coordinate_transform(model, scales=(1, 1), permutation=(0, 1)):
    """Substitute old x[i] = scales[i] * new x[permutation[i]], exactly."""
    compile_model(model)
    if len(scales) != 2 or len(permutation) != 2 or sorted(permutation) != [0, 1]:
        raise ValueError("Expected two positive scales and a coordinate permutation")
    factors = list(map(rational, scales))
    if any(v <= 0 for v in factors) or any(type(i) is not int for i in permutation):
        raise ValueError("Coordinate map must preserve the nonnegative domain")
    def coefficients(values):
        result = [F(0), F(0)]
        for i, value in enumerate(values):
            result[permutation[i]] = rational(value)*factors[i]
        return list(map(str, result))
    result = {"sense": model["sense"], "objective": coefficients(model["objective"]),
              "constraints": [{"a": coefficients(r["a"]), "op": r["op"], "b": str(rational(r["b"]))}
                              for r in model["constraints"]]}
    compile_model(result)
    return result


def replace_spans(text, replacements):
    ordered = sorted(replacements, key=lambda s: s["start"])
    for i, item in enumerate(ordered):
        source_span(text, item)
        if i and ordered[i-1]["end"] > item["start"]:
            raise ValueError("Overlapping edits would change the transformation")
        if not isinstance(item["replacement"], str) or not item["replacement"]:
            raise ValueError("A replacement must be nonempty text")
    for item in reversed(ordered):
        text = text[:item["start"]] + item["replacement"] + text[item["end"]:]
    return text


def transform_problem(case, kind, *, scale=10, rename_spans=None):
    """Prepare public text and an algebraic map; human preservation remains pending.

    Unit conversion changes the requested coordinate unit explicitly. Renaming
    uses supplied mention spans. Percentage rewriting only touches '...% of'.
    Unsupported text is rejected instead of padded with identity transformations.
    """
    text, variables = case["text"], list(case["variables"])
    if len(variables) != 2:
        raise ValueError("This protocol requires two supplied variables")
    edits, scales = [], ["1", "1"]
    if kind == "unit_scale":
        factor = rational(scale)
        if factor <= 0 or factor == 1:
            raise ValueError("Unit scaling must be positive and nonidentity")
        scales = [str(factor)] * 2
        text += (f"\nExpress each decision quantity in groups of {factor} original units. "
                 f"One unit of each new decision variable represents {factor} original units of its corresponding quantity. "
                 "All requirements, totals, and the objective in the preceding description remain in their original units.")
        variables = [f"groups of {factor} original units of {v}" for v in variables]
    elif kind == "variable_rename":
        if not rename_spans or {s["variable_index"] for s in rename_spans} != {0, 1}:
            raise ValueError("Provide source mention spans for both variables")
        names = ["item A", "item B"]
        if any(name.lower() in text.lower() for name in names):
            raise ValueError("Replacement names already occur in the original text")
        for span in rename_spans:
            if type(span["variable_index"]) is not int:
                raise ValueError("Variable index must be an integer")
            edits.append({**source_span(text, span), "replacement": names[span["variable_index"]]})
        text = replace_spans(text, edits)
        variables = names
    elif kind == "percent_ratio":
        for match in re.finditer(r"(?<![\w./-])(\d+(?:\.\d+)?)\s*(?:%|percent\b)(?=\s+of\b)", text, re.I):
            edits.append({"start": match.start(), "end": match.end(), "text": match.group(),
                          "replacement": str(F(match.group(1))/100)})
        if not edits:
            raise ValueError("No supported percentage-of expression; do not invent one")
        text = replace_spans(text, edits)
    else:
        raise ValueError("Unknown T11 transformation")
    return {"kind": kind, "public_problem": {"id": case["id"], "text": text, "variables": variables},
            "coordinate_map": {"scales": scales, "permutation": [0, 1]}, "edits": edits,
            "human_meaning_preserved": None, "status": "prepared_awaiting_human_review"}


def metamorphic_check(original_model, transformed_model, coordinate_map):
    try:
        expected = coordinate_transform(original_model, **coordinate_map)
        comparison = compare_models(expected, transformed_model)
    except (ValueError, TypeError) as exc:
        return {"valid_pair": False, "violation": None, "failure": str(exc)}
    return {"valid_pair": True, "violation": not comparison["equivalent"],
            "feasible_sets_equal": comparison["feasible_sets_equal"],
            "optimal_faces_equal": comparison["optimal_faces_equal"],
            "statuses_equal": comparison["statuses_equal"]}


def explicit_ratio_rewrite(case):
    """Convert dimensionless percentage and multiplier literals with an exact map.

    'times more' is deliberately excluded: its natural-language readings differ.
    Original units and comparison directions are not edited.
    """
    text, edits = case['text'], []
    for match in re.finditer(r'(?<![\w./-])(\d+(?:\.\d+)?)\s*(?:%|percent\b)', text, re.I):
        value = F(match.group(1))/100
        edits.append({'start': match.start(), 'end': match.end(), 'text': match.group(),
                      'replacement': f'({value} as a proportion)', 'rule': 'percentage_to_explicit_proportion', 'value': str(value)})
    pattern = r'\b((?:(?:\d+(?:\.\d+)?|two|three|four|five) times)|twice|thrice|(?:(?:a |one )?(?:half|third|quarter)))\b(?!\s+more\b)(?=\s+(?:the|as|of|that)\b)'
    values = {'twice': F(2), 'thrice': F(3), 'half': F(1, 2), 'third': F(1, 3), 'quarter': F(1, 4),
              'two': F(2), 'three': F(3), 'four': F(4), 'five': F(5)}
    for match in re.finditer(pattern, text, re.I):
        word = match.group().lower()
        if text[max(0, match.start()-4):match.start()].lower() == 'the ': continue
        key = re.sub(r'^(?:a|one) ', '', re.sub(r' times$', '', word))
        value = values[key] if key in values else F(key)
        percent = value*100
        representation = str(percent) if percent.denominator == 1 else f'({percent})'
        following = re.match(r'\s+(\w+)', text[match.end():]).group(1).lower()
        replacement = representation+'%'+(' of' if following in ('the', 'that') else '')
        edits.append({'start': match.start(), 'end': match.end(), 'text': match.group(),
                      'replacement': replacement, 'rule': 'multiplicative_ratio_to_percentage', 'value': str(value)})
    if not edits: raise ValueError('No unambiguous supported dimensionless ratio expression')
    transformed = replace_spans(text, edits)
    return {'kind': 'percent_ratio', 'public_problem': {'id': case['id'], 'text': transformed, 'variables': list(case['variables'])},
            'coordinate_map': {'scales': ['1', '1'], 'permutation': [0, 1]}, 'edits': edits,
            'semantic_basis': 'Explicit dimensionless numeric rewrite; original comparison words, variables and units are unchanged.',
            'human_meaning_preserved': None, 'status': 'rule_checked_not_human_annotated'}


def false_positive_decision(flagged_ids, reviews):
    """All flagged outputs require actual human adjudication; missing is never zero.

    False-positive fraction here means false alarms among manually checked flags,
    not the population FPR among all correct outputs. Review files are inputs.
    """
    if len(flagged_ids) != len(set(flagged_ids)):
        raise ValueError("Duplicate flagged IDs")
    ids = [r["id"] for r in reviews]
    if len(ids) != len(set(ids)) or not set(ids) <= set(flagged_ids):
        raise ValueError("Reviews must uniquely identify flagged outputs")
    complete = []
    for row in reviews:
        if row.get("is_false_positive") is None:
            continue
        if type(row["is_false_positive"]) is not bool or not str(row.get("reviewer_id", "")).strip() or not str(row.get("reason", "")).strip():
            raise ValueError("A completed human review needs a Boolean decision, reviewer, and reason")
        complete.append(row)
    n = len(complete)
    k = sum(r["is_false_positive"] for r in complete)
    discard = bool(n and F(k, n) > F(1, 20))
    status = "discarded" if discard else "awaiting_human_review" if n < len(flagged_ids) else "no_flags_to_review" if not n else "accepted"
    return {"flagged_n": len(flagged_ids), "reviewed_n": n, "false_positive_n": k,
            "false_positive_rate": k/n if n else None,
            "status": status, "discard_module": discard,
            "missing_ids": sorted(set(flagged_ids) - {r["id"] for r in complete})}
