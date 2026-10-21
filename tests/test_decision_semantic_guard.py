"""Handwritten tests; no reference annotations or held-out files are loaded."""
from copy import deepcopy
from fractions import Fraction as F
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))
from decision_semantic_guard import extract_percentage_constraints, audit_model, repair_model


TEXT = "At least 25% of the bowls made must be chicken curry."
VARS = ["goat", "chicken"]


def model(rows=()):
    return {"sense": "min", "objective": [1, 1], "constraints": list(deepcopy(rows))}


def row(a, op="<=", b=0):
    return {"a": a, "op": op, "b": b}


class SemanticGuardTests(unittest.TestCase):
    def test_percentage_direction_and_evidence(self):
        r = extract_percentage_constraints(TEXT, VARS)
        self.assertEqual(r["constraints"][0]["constraint"], row(["1/4", "-3/4"], b="0"))
        evidence = r["constraints"][0]["evidence"]
        self.assertEqual(TEXT[evidence["start"]:evidence["end"]], evidence["text"])
        self.assertEqual(TEXT[evidence["variable_start"]:evidence["variable_end"]], "chicken")
        self.assertEqual(extract_percentage_constraints(TEXT.replace("least", "most"), VARS)["constraints"][0]["constraint"]["a"], ["-1/4", "3/4"])

    def test_explicit_transport_and_decimal_percent(self):
        text = "At least 30% of all the trips must be made by car."
        self.assertEqual(extract_percentage_constraints(text, ["truck", "car"])["constraints"][0]["constraint"]["a"], ["3/10", "-7/10"])
        r = extract_percentage_constraints("At most 12.5% of the items made must be red toys.", ["red toys", "blue toys"])
        self.assertEqual(r["constraints"][0]["constraint"]["a"], ["7/8", "-1/8"])

    def test_abstain_ambiguous_unsupported_negation_condition(self):
        texts = [TEXT.replace("chicken curry", "chicken and goat curry"),
                 TEXT.replace("chicken curry", "fish curry"),
                 TEXT.replace("bowls", "revenue"),
                 "If demand rises, " + TEXT, "It is not true that " + TEXT,
                 TEXT.replace("25%", "125%"), "Chicken must exceed goat."]
        for text in texts:
            with self.subTest(text=text):
                self.assertEqual(extract_percentage_constraints(text, VARS)["status"], "abstain")

    def test_strict_comparison_does_not_invent_one(self):
        source = "The number of chickens must exceed goats."
        original = model([row([1, -1])])
        result = repair_model(source, ["goats", "chickens"], original)
        self.assertFalse(result["changed"])
        self.assertEqual(result["model"], original)

    def test_geometric_implication_can_follow_from_other_rows(self):
        original = model([row([1, 0], b=3), row([0, 1], ">=", 1)])
        self.assertEqual(audit_model(TEXT, VARS, original)["status"], "supported_percentages_implied")
        self.assertFalse(repair_model(TEXT, VARS, original)["changed"])

    def test_unbounded_violation_has_exact_finite_witness(self):
        check = audit_model(TEXT, VARS, model())["checks"][0]
        x, y = map(F, check["witness"])
        self.assertGreater(x/4-3*y/4, 0)
        self.assertGreaterEqual(min(x, y), 0)

    def test_replace_only_reversed_constraint(self):
        original = model([row([-1, 3]), row([1, 1], b=20), row([1, -1], ">=", 0)])
        saved = deepcopy(original)
        result = repair_model(TEXT, VARS, original)
        self.assertEqual(original, saved)
        self.assertEqual(result["model"]["constraints"][1:], original["constraints"][1:])
        self.assertEqual(result["edits"][0]["operation"], "replace_reversed_homogeneous_row")
        self.assertEqual(result["after"]["status"], "supported_percentages_implied")
        self.assertTrue(result["heuristic"])

    def test_append_preserves_unrelated_offset_and_equalities(self):
        original = model([row([-1, 3], b=4), row([0, 1], "=", 1)])
        result = repair_model(TEXT, VARS, original)
        self.assertEqual(result["model"]["constraints"][:2], original["constraints"])
        self.assertEqual(result["edits"][0]["operation"], "append_supported_percentage")

    def test_capacity_and_infeasibility_are_not_false_passes(self):
        original = model([row([1, 1], b=100)]*32)
        result = repair_model(TEXT, VARS, original)
        self.assertFalse(result["changed"])
        self.assertEqual(result["blocked"][0]["reason"], "row_capacity")
        self.assertEqual(result["after"]["status"], "percentage_mismatch")
        bad = model([row([1, 0], b=-1)])
        self.assertEqual(audit_model(TEXT, VARS, bad)["status"], "inconclusive_infeasible_candidate")
        self.assertFalse(repair_model(TEXT, VARS, bad)["changed"])

    def test_variable_order_and_boundary_percentages(self):
        self.assertEqual(extract_percentage_constraints(TEXT, list(reversed(VARS)))["constraints"][0]["constraint"]["a"], ["-3/4", "1/4"])
        self.assertEqual(audit_model(TEXT.replace("25%", "0%"), VARS, model())["status"], "supported_percentages_implied")
        result = repair_model(TEXT.replace("25%", "100%"), VARS, model())
        self.assertEqual(result["model"]["constraints"][0]["a"], ["1", "0"])


if __name__ == "__main__":
    unittest.main()
