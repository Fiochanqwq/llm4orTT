import socket
import itertools
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
from language_io_guard import zero_call_guard
from language_oracle_reanalysis import oracle_selection
from language_primary_statistics import analyze, comparison
from language_density import inventory, materialize_density, near_boundary_seeds
from language_decisions import decide
from language_evaluator import score
from language_stage import request_for, verify_prompt


def rows(l0_bad, l1_bad, l1_available=0, l3_available=0):
    result = []
    for i in range(60):
        scores = {}
        for structure, bad, available in (("L0", l0_bad, 0), ("L1", l1_bad, l1_available), ("L3", 0, l3_available)):
            scores[structure] = {
                "dangerous": i < bad,
                "arms": {"A0": {"dangerousReleased": int(i < bad), "availableCorrect": int(i >= bad), "status": "safe"},
                         "A2": {"dangerousReleased": 0, "availableCorrect": int(i < available), "status": "unresolved"}},
            }
        result.append({"id": str(i), "domain": ["dispatch", "staffing", "workshop"][i // 20], "scores": scores})
    return result


class OracleTests(unittest.TestCase):
    def test_primary_twenty_discordances_and_reversal(self):
        forward = comparison([1] * 26 + [0] * 34, [1] * 6 + [0] * 54, "L0", "L1")
        reverse = comparison([1] * 6 + [0] * 54, [1] * 26 + [0] * 34, "L0", "L1")
        self.assertEqual(forward["L0only"], 20)
        self.assertEqual(forward["L1only"], 0)
        self.assertEqual(forward["pExactTwoSided"], 2 ** -19)
        self.assertEqual(reverse["pExactTwoSided"], forward["pExactTwoSided"])
        self.assertEqual(reverse["differenceSecondMinusFirst"], -forward["differenceSecondMinusFirst"])

    def test_density_is_required_even_when_primary_significant(self):
        result = analyze(rows(26, 6))
        self.assertFalse(result["success"]["A"])
        self.assertFalse(result["success"]["B"])
        self.assertTrue(result["primary"]["solePrimaryTest"])

    def test_exact_user_criteria_without_extra_utility_gate(self):
        self.assertTrue(analyze(rows(50, 30))["success"]["A"])
        # B is the specified observed gap rule, even when both rates are zero.
        self.assertTrue(analyze(rows(30, 30, 0, 0))["success"]["B"])
        self.assertTrue(analyze(rows(30, 30, 10, 16))["success"]["B"])
        self.assertFalse(analyze(rows(30, 30, 10, 17))["success"]["B"])

    def test_oracle_contains_only_nonzero_factor(self):
        value = {"thetaTenths": {"a": 5, "b": 0, "c": 0},
                 "activeFactor": "a", "distractors": ["b", "c"]}
        self.assertEqual(oracle_selection(value), ["a"])
        value["thetaTenths"]["b"] = 1
        with self.assertRaises(ValueError):
            oracle_selection(value)

    def test_zero_call_guard_blocks_connection_before_network(self):
        with socket.socket() as sock:
            with zero_call_guard():
                with self.assertRaisesRegex(PermissionError, "Zero-call"):
                    sock.connect(("127.0.0.1", 9))

    def test_density_inventory_and_bounds_are_prespecified(self):
        specs = inventory()
        self.assertEqual(len(specs), 60)
        self.assertEqual(len({(s["domain"], s["seed"]) for s in specs}), 60)
        near = 0
        for spec in specs:
            blueprint, public, truth = materialize_density(**spec)
            self.assertTrue(verify_prompt(public, request_for(public)))
            self.assertTrue(all(0 <= v <= 20 for v in truth["thetaTenths"].values()))
            self.assertTrue(all(__import__("fractions").Fraction(v) <= 1 for v in truth["realizedHistoryRegrets"]))
            near += truth["generator"]["nearBoundary"]
        self.assertEqual(near, 36)

    def test_near_boundary_density_does_not_depend_on_selected_proposal(self):
        seed = min(near_boundary_seeds("dispatch"))
        _, public, truth = materialize_density("dispatch", seed)
        ids = sorted(truth["thetaTenths"])
        for n in range(4):
            for selected in itertools.combinations(ids, n):
                with zero_call_guard():
                    decision = decide(public, list(selected))
                self.assertTrue(score(public, truth, decision)["dangerous"])


if __name__ == "__main__":
    unittest.main()
