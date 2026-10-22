"""Independent analytic and frozen-cohort checks of rational LP certificates."""
from copy import deepcopy
from fractions import Fraction as F
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
import exact_lp as lp


def box(n, objective=None):
    return {"sense": "max", "objective": objective or [1]*n,
            "constraints": [{"a": [int(i == j) for j in range(n)], "op": "<=", "b": 1} for i in range(n)]}


class ExactLPTests(unittest.TestCase):
    def test_all_supported_dimensions_have_exact_primal_dual_optima(self):
        for n in range(1, 7):
            model = lp.compile_model(box(n))
            result = lp.analyze(model)
            self.assertEqual(result["value"], n)
            self.assertTrue(lp.check_certificate(model.rows, model.objective, result["certificate"]))

    def test_equal_region_different_optimal_face(self):
        left = box(3)
        right = box(3, [1, 0, 0])
        result = lp.compare_models(left, right)
        self.assertTrue(result["feasible_sets_equal"])
        self.assertFalse(result["optimal_faces_equal"])

    def test_scaled_and_redundant_constraints_are_equivalent(self):
        left = box(6)
        right = box(6, [3]*6)
        right["constraints"] += [{"a": [2]*6, "op": "<=", "b": 12}]
        self.assertTrue(lp.compare_models(left, right)["equivalent"])

    def test_lower_dimensional_fractional_polytope(self):
        model = box(3)
        model["constraints"] += [{"a": [1, 1, 0], "op": "=", "b": "1/3"}, {"a": [0, 0, 1], "op": "=", "b": "2/7"}]
        self.assertEqual(lp.analyze(lp.compile_model(model))["value"], F(13, 21))

    def test_infeasibility_requires_farkas_proof(self):
        model = box(2)
        model["constraints"] += [{"a": [1, 0], "op": ">=", "b": 2}]
        compiled = lp.compile_model(model)
        result = lp.analyze(compiled)
        self.assertEqual(result["status"], "infeasible")
        self.assertTrue(lp.check_certificate(compiled.rows, compiled.objective, result["certificate"]))

    def test_unbounded_ray_yields_finite_inclusion_counterexample(self):
        left = {"sense": "max", "objective": [1, 1], "constraints": []}
        result = lp.compare_models(left, box(2))
        self.assertEqual(result["left"]["status"], "unbounded")
        self.assertFalse(result["feasible_sets_equal"])
        self.assertFalse(result["optimal_faces_equal"])
        witness = list(map(F, result["feasible_inclusions"][0]["witness"]))
        self.assertTrue(all(x >= 0 for x in witness))
        self.assertTrue(any(x > 1 for x in witness))

    def test_empty_and_nonempty_regions_with_empty_optimal_faces(self):
        empty = {"sense": "max", "objective": [1], "constraints": [{"a": [0], "op": "<=", "b": -1}]}
        unbounded = {"sense": "max", "objective": [1], "constraints": []}
        result = lp.compare_models(empty, unbounded)
        self.assertFalse(result["feasible_sets_equal"])
        self.assertTrue(result["optimal_faces_equal"])

    def test_altered_certificate_is_rejected(self):
        model = lp.compile_model(box(2))
        certificate = deepcopy(lp.analyze(model)["certificate"])
        certificate["value"] += F(1, 10**12)
        self.assertFalse(lp.check_certificate(model.rows, model.objective, certificate))
        certificate = deepcopy(lp.analyze(model)["certificate"])
        certificate["point"] = (F(1)+F(1, 10**12), F(1))
        self.assertFalse(lp.check_certificate(model.rows, model.objective, certificate))

    def test_unknown_fields_and_dimension_mismatch_fail(self):
        with self.assertRaises(ValueError):
            lp.compile_model({**box(2), "integrality": [1, 1]})
        with self.assertRaises(ValueError):
            lp.compare_models(box(2), box(3))

    def test_frozen_heldout_per_case_flags_and_counts(self):
        from replay import SOURCE, read, load_candidate, ARMS
        if not (SOURCE / "heldout-scores.json").exists():
            self.skipTest("Local evidence is distributed separately")
        old = {r["id"]: r for r in read(SOURCE / "heldout-scores.json")}
        counts = dict.fromkeys(ARMS, 0)
        for case in read(SOURCE / "cases.private.json"):
            if case["split"] != "heldout":
                continue
            for arm in ARMS:
                pred = load_candidate(SOURCE, case, arm)
                if not pred["valid"]:
                    self.assertFalse(old[case["id"]]["arms"][arm]["success"])
                    continue
                result = lp.compare_models(case["reference"], pred["model"])
                expected = old[case["id"]]["arms"][arm]["comparison"]
                for key in ("feasible_sets_equal", "optimal_faces_equal"):
                    self.assertEqual(result[key], expected[key], (case["id"], arm, key))
                counts[arm] += result["feasible_sets_equal"] and result["optimal_faces_equal"]
        self.assertEqual(list(counts.values()), [42, 46, 44, 43])


if __name__ == "__main__":
    unittest.main()
