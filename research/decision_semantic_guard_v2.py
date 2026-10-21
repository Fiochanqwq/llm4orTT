"""Adaptively explored percentage guard, developed after old holdout inspection.

This module is NOT a prespecified revision of the original primary experiment.
It may be evaluated only as a separately labeled exploratory method. Extraction
uses text and ordered variable names, with no reference-model access. Exact
implication and conservative row-repair primitives are reused from version 1.
"""
from __future__ import annotations

from copy import deepcopy
import re

from decision_geometry import compile_model, rational, MAX_ROWS
from decision_semantic_guard import _implication, _reversed_homogeneous_row

PROVENANCE = "adaptive_exploration_after_old_holdout_error_inspection"
COUNT_NOUNS = ("bowls", "items", "trips", "crepes", "vehicles", "pancakes", "buns",
               "loaves", "sandwiches", "servings")
_PERCENT = re.compile(
    r"\b(?P<direction>at least|at most)\s+(?P<pct>\d+(?:\.\d+)?)\s*%\s+of\s+"
    r"(?P<denominator>(?:all\s+)?(?:the\s+)?(?:" + "|".join(COUNT_NOUNS) + r")(?:\s+made)?)"
    r"\s+(?:must|should)\s+be\s+(?:made\s+by\s+|by\s+)?(?P<item>[^.;!?\n]+)", re.I)
_UNSAFE = re.compile(r"\b(?:if|unless|when|whenever|provided|assuming|otherwise|except|not|never|either|or)\b|\bin\s+case\b|n't", re.I)
_WEIGHTED = re.compile(r"\b(?:weight|mass|revenue|cost|profit|calories|kilograms|kg|grams|liters|litres)\b", re.I)
_STOP = {"a", "an", "the", "and", "of", "for", "to", "by", "with", "type", "kind",
         "number", "amount", "total", "unit", "made", "produce", "production"}


def _singular(word: str) -> str:
    # Explicit count nouns plus simple plural-s are enough for transparent
    # name matching. No fuzzy spelling or semantic synonym inference occurs.
    irregular = {"loaves": "loaf", "sandwiches": "sandwich"}
    if word in irregular:
        return irregular[word]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us")):
        return word[:-1]
    return word


def _tokens(text: str) -> list[tuple[str, int, int]]:
    return [(_singular(m.group().lower()), m.start(), m.end()) for m in re.finditer(r"[A-Za-z]+", text)]


def _name_sets(variables: list[str]) -> tuple[list[set[str]], list[set[str]]]:
    names = [{word for word, _, _ in _tokens(name)} for name in variables]
    ignored = _STOP | {_singular(noun) for noun in COUNT_NOUNS}
    unique = [(names[i] - names[1-i]) - ignored for i in range(2)]
    return names, unique


def extract_percentage_constraints(text: str, variables: list[str]) -> dict:
    if not isinstance(text, str) or not isinstance(variables, list) or len(variables) != 2:
        raise ValueError("expected text and exactly two ordered variable names")
    if any(not isinstance(v, str) or not v.strip() for v in variables):
        raise ValueError("variable names must be nonempty strings")
    names, unique = _name_sets(variables)
    if not all(names) or names[0] == names[1]:
        return {"status": "abstain", "constraints": [], "reasons": ["ambiguous_variable_names"],
                "heuristic": True, "provenance": PROVENANCE}
    extracted, reasons = [], []
    for match in _PERCENT.finditer(text):
        start = max(text.rfind(c, 0, match.start()) for c in ".;!?\n") + 1
        tail = re.search(r"[.;!?\n]", text[match.end():])
        end = match.end() + tail.start() if tail else len(text)
        if _UNSAFE.search(text[start:end]):
            reasons.append("conditional_or_negated_percentage_clause")
            continue
        if _WEIGHTED.search(match["item"]):
            reasons.append("weighted_or_monetary_target")
            continue
        try:
            percentage = rational(match["pct"]) / 100
        except ValueError:
            reasons.append("invalid_percentage")
            continue
        if not 0 <= percentage <= 1:
            reasons.append("percentage_out_of_range")
            continue
        item_tokens = _tokens(match["item"])
        matches = [[(word, lo, hi) for word, lo, hi in item_tokens if word in unique[i]] for i in range(2)]
        candidates = [i for i in range(2) if matches[i]]
        if len(candidates) != 1:
            reasons.append("target_variable_not_uniquely_matched")
            continue
        index = candidates[0]
        a = [percentage, percentage]
        a[index] -= 1
        if match["direction"].lower() == "at most":
            a = [-v for v in a]
        spans = [{"start": match.start("item")+lo, "end": match.start("item")+hi,
                  "text": match["item"][lo:hi], "normalized_token": word}
                 for word, lo, hi in matches[index]]
        extracted.append({"constraint": {"a": [str(v) for v in a], "op": "<=", "b": "0"},
                          "evidence": {"start": match.start(), "end": match.end(), "text": match.group(),
                                       "denominator": match["denominator"], "percentage": str(percentage),
                                       "direction": match["direction"].lower(), "variable_index": index,
                                       "variable": variables[index], "match_method": "unique_content_tokens",
                                       "variable_spans": spans,
                                       "unique_name_tokens": sorted(unique[index])}})
    if not extracted and not reasons:
        reasons.append("no_supported_explicit_percentage_template")
    return {"status": "extracted" if extracted else "abstain", "constraints": extracted,
            "reasons": reasons, "heuristic": True, "provenance": PROVENANCE}


def audit_model(text: str, variables: list[str], ir: dict) -> dict:
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
    return {"status": status, "heuristic": True, "provenance": PROVENANCE,
            "checks": checks, "extraction": extraction,
            "scope": "Only supported percentage statements; no claim of complete model correctness."}


def repair_model(text: str, variables: list[str], ir: dict) -> dict:
    """Reuse version-1 exact implication and reversed-row repair criteria."""
    before = audit_model(text, variables, ir)
    repaired, edits, blocked = deepcopy(ir), [], []
    for check in before["checks"]:
        if check["implied"] is not False:
            continue
        expected = check["constraint"]
        if _implication(repaired, expected)["implied"] is not False:
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
    return {"model": repaired, "changed": bool(edits), "heuristic": True, "provenance": PROVENANCE,
            "guarantee": "No global semantic correctness guarantee.",
            "before": before, "after": audit_model(text, variables, repaired), "edits": edits, "blocked": blocked}
