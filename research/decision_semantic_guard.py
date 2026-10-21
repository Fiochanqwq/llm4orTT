"""Conservative percentage-language checks for a two-variable continuous LP.

This is an exploratory heuristic, not a general semantic verifier. Extraction
uses only source text and the supplied ordered variable names. References,
answers, candidate quality, and dataset identity never inform extraction.
Strict inequalities, rounding, integrality, and general English are not inferred.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction as F
import re

from decision_geometry import analyze_model, compile_model, rational, MAX_ROWS

# These count-denominator templates were fixed using development examples.
# Weighted totals (revenue, mass, time, cost) are intentionally unsupported.
_PERCENT = re.compile(
    r"\b(?P<direction>at least|at most)\s+(?P<pct>\d+(?:\.\d+)?)\s*%"
    r"\s+of\s+(?P<denominator>(?:all\s+)?(?:the\s+)?(?:bowls|items|trips)"
    r"(?:\s+made)?)\s+must\s+be\s+(?:made\s+by\s+)?(?P<item>[^.;!?\n]+)", re.I)
_UNSAFE = re.compile(r"\b(?:if|unless|except|not|never|either|or)\b|n't", re.I)


def _variable_pattern(name: str) -> re.Pattern:
    tokens = re.findall(r"\w+", name.lower())
    if not tokens:
        raise ValueError("variable names must contain letters or digits")
    return re.compile(r"(?<!\w)" + r"\W+".join(map(re.escape, tokens)) + r"(?!\w)", re.I)


def extract_percentage_constraints(text: str, variables: list[str]) -> dict:
    """Return explicit source-grounded <= rows, or abstain with reasons.

    E.g. at least 25% ... chicken means .25*x0 - .75*x1 <= 0 when
    chicken is variable 1. There is no artificial positive minimum count.
    """
    if not isinstance(text, str) or not isinstance(variables, list) or len(variables) != 2:
        raise ValueError("expected text and exactly two ordered variable names")
    if any(not isinstance(v, str) or not v.strip() for v in variables):
        raise ValueError("variable names must be nonempty strings")
    patterns = [_variable_pattern(v) for v in variables]
    if patterns[0].pattern == patterns[1].pattern:
        return {"status": "abstain", "constraints": [], "reasons": ["ambiguous_variable_names"],
                "heuristic": True}
    extracted, reasons = [], []
    for match in _PERCENT.finditer(text):
        # Inspect the entire sentence to avoid silently removing an antecedent
        # such as 'if demand increases' or a negation before 'at least'.
        start = max(text.rfind(c, 0, match.start()) for c in ".;!?\n") + 1
        tail = re.search(r"[.;!?\n]", text[match.end():])
        end = match.end() + tail.start() if tail else len(text)
        sentence = text[start:end]
        if _UNSAFE.search(sentence):
            reasons.append("conditional_or_negated_percentage_clause")
            continue
        try:
            percentage = rational(match["pct"]) / 100
        except ValueError:
            reasons.append("invalid_percentage")
            continue
        if not 0 <= percentage <= 1:
            reasons.append("percentage_out_of_range")
            continue
        item = match["item"]
        hits = [(i, list(pattern.finditer(item))) for i, pattern in enumerate(patterns)]
        hits = [(i, matches) for i, matches in hits if matches]
        if len(hits) != 1 or len(hits[0][1]) != 1:
            reasons.append("target_variable_not_uniquely_matched")
            continue
        index, matches = hits[0]
        variable_match = matches[0]
        a = [percentage, percentage]
        a[index] -= 1
        if match["direction"].lower() == "at most":
            a = [-v for v in a]
        variable_start = match.start("item") + variable_match.start()
        variable_end = match.start("item") + variable_match.end()
        extracted.append({"constraint": {"a": [str(v) for v in a], "op": "<=", "b": "0"},
                          "evidence": {"start": match.start(), "end": match.end(),
                                       "text": match.group(), "denominator": match["denominator"],
                                       "percentage": str(percentage), "direction": match["direction"].lower(),
                                       "variable_index": index, "variable": variables[index],
                                       "variable_start": variable_start, "variable_end": variable_end,
                                       "variable_text": text[variable_start:variable_end]}})
    if not extracted and not reasons:
        reasons.append("no_supported_explicit_percentage_template")
    return {"status": "extracted" if extracted else "abstain", "constraints": extracted,
            "reasons": reasons, "heuristic": True}


def _implication(ir: dict, row: dict) -> dict:
    trial = deepcopy(ir)
    trial["sense"], trial["objective"] = "max", row["a"]
    result = analyze_model(trial)
    if result["status"] == "infeasible":
        return {"status": "infeasible_candidate", "implied": None, "witness": None}
    b = rational(row["b"])
    a = list(map(rational, row["a"]))
    if result["status"] == "optimal":
        maximum = F(result["value"])
        return {"status": "implied" if maximum <= b else "not_implied", "implied": maximum <= b,
                "maximum_lhs": str(maximum),
                "witness": None if maximum <= b else result["optimal_face"]["vertices"][0]}
    vertex = list(map(F, result["vertices"][0]))
    for raw in result["recession_rays"]:
        d = list(map(F, raw))
        slope = sum(x*y for x, y in zip(a, d))
        if slope > 0:
            lhs = sum(x*y for x, y in zip(a, vertex))
            step = max(F(0), (b-lhs)/slope) + 1/slope
            return {"status": "not_implied", "implied": False, "maximum_lhs": "unbounded",
                    "witness": [str(x+step*y) for x, y in zip(vertex, d)]}
    raise AssertionError("unbounded linear objective must have an improving ray")


def audit_model(text: str, variables: list[str], ir: dict) -> dict:
    """Check implication by exact optimization, not coefficient string equality."""
    compile_model(ir)
    extraction = extract_percentage_constraints(text, variables)
    checks = [dict(item, **_implication(ir, item["constraint"])) for item in extraction["constraints"]]
    if not checks:
        status = "abstain"
    elif any(check["implied"] is None for check in checks):
        status = "inconclusive_infeasible_candidate"
    elif any(not check["implied"] for check in checks):
        status = "percentage_mismatch"
    else:
        status = "supported_percentages_implied"
    return {"status": status, "heuristic": True, "checks": checks,
            "extraction": extraction,
            "scope": "Only supported percentage statements; no claim of complete model correctness."}


def _reversed_homogeneous_row(row: dict, expected: dict) -> bool:
    if row["op"] == "=" or rational(row["b"]) != 0:
        return False
    a = list(map(rational, row["a"]))
    if row["op"] == ">=":
        a = [-v for v in a]
    e = list(map(rational, expected["a"]))
    return a[0]*e[1] == a[1]*e[0] and sum(x*y for x, y in zip(a, e)) < 0


def repair_model(text: str, variables: list[str], ir: dict) -> dict:
    """Heuristic repair: only opposite homogeneous rows or appended text rows.

    No unrelated constraints are deleted. Implied rows are untouched. At the
    schema capacity limit an append is blocked, not silently truncated.
    Infeasible candidates are left unchanged because implication is vacuous.
    """
    before = audit_model(text, variables, ir)
    repaired, edits, blocked = deepcopy(ir), [], []
    for check in before["checks"]:
        if check["implied"] is not False:
            continue
        expected = check["constraint"]
        current = _implication(repaired, expected)
        if current["implied"] is not False:
            continue
        opposite = [i for i, row in enumerate(repaired["constraints"])
                    if _reversed_homogeneous_row(row, expected)]
        if opposite:
            for index in opposite:
                previous = deepcopy(repaired["constraints"][index])
                repaired["constraints"][index] = deepcopy(expected)
                edits.append({"operation": "replace_reversed_homogeneous_row", "index": index,
                              "before": previous, "after": deepcopy(expected), "evidence": check["evidence"]})
        elif len(repaired["constraints"]) < MAX_ROWS:
            repaired["constraints"].append(deepcopy(expected))
            edits.append({"operation": "append_supported_percentage", "index": len(repaired["constraints"])-1,
                          "after": deepcopy(expected), "evidence": check["evidence"]})
        else:
            blocked.append({"reason": "row_capacity", "constraint": deepcopy(expected)})
    after = audit_model(text, variables, repaired)
    return {"model": repaired, "changed": bool(edits), "heuristic": True,
            "guarantee": "No global semantic correctness guarantee.",
            "before": before, "after": after, "edits": edits, "blocked": blocked}
