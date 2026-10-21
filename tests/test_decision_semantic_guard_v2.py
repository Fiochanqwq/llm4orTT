"""Handwritten adaptive-development examples; no dataset files are read."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))
import decision_semantic_guard as v1
import decision_semantic_guard_v2 as v2


def model(rows=()):
    return {"sense": "min", "objective": [1, 1], "constraints": deepcopy(list(rows))}


def row(a, b=0, op="<="):
    return {"a": a, "op": op, "b": b}


class AdaptiveGuardTests(unittest.TestCase):
    def test_known_adaptive_crepe_example(self):
        text = "At least 25% of the crepes made should be chocolate."
        names = ["peanut butter crepes", "chocolate crepe"]
        r = v2.extract_percentage_constraints(text, names)
        self.assertEqual(r["constraints"][0]["constraint"], row(["1/4", "-3/4"], "0"))
        evidence = r["constraints"][0]["evidence"]
        for span in evidence["variable_spans"]:
            self.assertEqual(text[span["start"]:span["end"]], span["text"])
        self.assertEqual(r["provenance"], v2.PROVENANCE)
        self.assertEqual(v1.extract_percentage_constraints(text, names)["status"], "abstain")

    def test_by_car_forms(self):
        for verb in ("must", "should"):
            for form in ("by car", "made by car", "car"):
                text = f"At least 60% of the trips {verb} be {form}."
                self.assertEqual(v2.extract_percentage_constraints(text, ["bus", "car"])["constraints"][0]["constraint"]["a"], ["3/5", "-2/5"])

    def test_white_list_nouns_and_at_most(self):
        for noun in v2.COUNT_NOUNS:
            text = f"At most 10% of the {noun} made should be chocolate."
            r = v2.extract_percentage_constraints(text, ["chocolate products", "vanilla products"])
            self.assertEqual(r["constraints"][0]["constraint"]["a"], ["9/10", "-1/10"])

    def test_ambiguous_shared_names_and_pronouns_abstain(self):
        names = ["red buns", "blue buns"]
        for target in ("buns", "them", "those", "red and blue", "red or blue"):
            text = f"At least 20% of the buns must be {target}."
            self.assertEqual(v2.extract_percentage_constraints(text, names)["status"], "abstain")

    def test_condition_negation_and_weighted_totals_abstain(self):
        base = "At least 20% of the items must be chocolate."
        names = ["chocolate", "vanilla"]
        for text in ("If supplies allow, " + base, "It is not required that " + base,
                     "When supplies allow, " + base, "Provided demand increases, " + base,
                     base.replace("items", "revenue"), base.replace("items", "weight"),
                     base.replace("chocolate.", "chocolate by weight."),
                     base.replace("chocolate.", "chocolate except on weekends.")):
            self.assertEqual(v2.extract_percentage_constraints(text, names)["status"], "abstain")

    def test_repair_reuses_v1_scope_and_preserves_unrelated_rows(self):
        text = "At least 60% of the trips must be by car."
        original = model([row([-3, 2]), row([2, 1], 100), row([1, -1], 2)])
        snapshot = deepcopy(original)
        r = v2.repair_model(text, ["bus", "car"], original)
        self.assertEqual(original, snapshot)
        self.assertEqual(r["model"]["constraints"][1:], original["constraints"][1:])
        self.assertEqual(r["after"]["status"], "supported_percentages_implied")
        self.assertEqual(r["edits"][0]["operation"], "replace_reversed_homogeneous_row")

    def test_capacity_infeasible_and_strict_comparison_unchanged(self):
        text = "At least 60% of the trips must be by car."
        r = v2.repair_model(text, ["bus", "car"], model([row([1, 1], 100)]*32))
        self.assertFalse(r["changed"])
        self.assertTrue(r["blocked"])
        r = v2.repair_model(text, ["bus", "car"], model([row([1, 0], -1)]))
        self.assertEqual(r["after"]["status"], "inconclusive_infeasible_candidate")
        self.assertFalse(r["changed"])
        self.assertFalse(v2.repair_model("Cars must exceed buses.", ["bus", "car"], model())["changed"])

    def test_existing_v1_percentage_behavior_is_preserved(self):
        text = "At least 25% of the bowls made must be chicken curry."
        names = ["goat", "chicken"]
        original = model([row([-1, 3])])
        self.assertEqual(v1.repair_model(text, names, original)["model"], v2.repair_model(text, names, original)["model"])


if __name__ == "__main__":
    unittest.main()
