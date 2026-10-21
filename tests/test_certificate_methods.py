"""Exact independent one/two-dimensional checks of research comparisons."""
import copy
import json
import math
import sys
import unittest
from fractions import Fraction as Q
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
from certificate_methods import METHODS, _AuditSet, run_method


def interval_problem(threshold=Q(1, 10)):
    # Compatible theta is [1/5, 4/5]; worst regret is 4/5 - 3/5 = 1/5.
    return {
        "box": [(Q(0), Q(1))],
        "histories": [[((Q(1),), Q(4, 5))], [((Q(-1),), Q(-1, 5))]],
        "rivals": [(Q(0), (Q(0),)), (Q(-3, 5), (Q(1),))],
        "threshold": threshold,
    }


class ComparisonMethodTests(unittest.TestCase):
    def audit(self, problem, result, exact):
        json.dumps(result, allow_nan=False)
        if result["lowerExact"] is not None:
            self.assertLessEqual(Q(result["lowerExact"]), exact)
            self.assertLessEqual(Q.from_float(result["lowerBound"]), exact)
        if result["upperExact"] is not None:
            self.assertGreaterEqual(Q(result["upperExact"]), exact)
            self.assertGreaterEqual(Q.from_float(result["upperBound"]), exact)
        for witness in result["witnesses"]:
            theta = list(map(Q, witness))
            self.assertTrue(all(lo <= x <= hi for (lo, hi), x in zip(problem["box"], theta)))
            self.assertTrue(all(
                sum(a * x for a, x in zip(row, theta)) <= b
                for history in problem["histories"] for row, b in history))
        for proof in result["dualProofs"]:
            weighted = [Q(0)] * len(problem["box"])
            offset = Q(0)
            for index, multiplier in proof["multipliers"]:
                self.assertLess(index, proof["rowCount"])
                multiplier = Q(multiplier)
                self.assertGreaterEqual(multiplier, 0)
                row = result["rows"][index]
                offset += multiplier * Q(row["b"])
                weighted = [v + multiplier * Q(a) for v, a in zip(weighted, row["a"])]
            self.assertEqual(offset, Q(proof["offsetExact"]))
            self.assertEqual(weighted, list(map(Q, proof["weightedRowExact"])))
            residual = [Q(q) - a for q, a in zip(proof["sourceObjective"], weighted)]
            support = sum(max(q * lo, q * hi) for q, (lo, hi) in zip(residual, problem["box"]))
            self.assertEqual(offset + support, Q(proof["sourceUpperExact"]))
        for rival in result["rivals"]:
            if rival["upperExact"] is None:
                continue
            q = list(map(Q, rival["objectiveExact"]))
            constant = Q(rival["constantExact"])
            proof_ref = rival["upperProof"]
            if proof_ref["kind"] == "box":
                upper = constant + sum(max(v * lo, v * hi) for v, (lo, hi) in zip(q, problem["box"]))
            else:
                proof = result["dualProofs"][proof_ref["proofIndex"]]
                residual = [v - Q(a) for v, a in zip(q, proof["weightedRowExact"])]
                upper = constant + Q(proof["offsetExact"]) + sum(
                    max(v * lo, v * hi) for v, (lo, hi) in zip(residual, problem["box"]))
            self.assertEqual(upper, Q(rival["upperExact"]))

    def test_all_methods_find_real_risk_and_auditable_proofs(self):
        problem = interval_problem()
        for method in METHODS:
            with self.subTest(method=method):
                result = run_method(problem, method, 30, 10)
                self.assertEqual(result["status"], "risk_witness")
                self.audit(problem, result, Q(1, 5))

    def test_all_methods_prove_exact_boundary_safe(self):
        problem = interval_problem(Q(1, 5))
        for method in METHODS:
            with self.subTest(method=method):
                result = run_method(problem, method, 30, 10)
                self.assertEqual(result["status"], "safe")
                self.audit(problem, result, Q(1, 5))

    def test_every_lp_budget_retains_conservative_bounds(self):
        problem = interval_problem()
        for method in METHODS:
            for budget in range(5):
                with self.subTest(method=method, budget=budget):
                    result = run_method(problem, method, budget, 10)
                    self.assertLessEqual(result["resources"]["lpCalls"], budget)
                    self.assertNotEqual(result["status"], "safe")
                    self.audit(problem, result, Q(1, 5))

    def test_zero_budget_cannot_claim_nonempty_set(self):
        problem = interval_problem(Q(10))
        for method in METHODS:
            result = run_method(problem, method, 0, 10)
            self.assertEqual(result["status"], "unresolved")
            self.assertIsNone(result["lowerBound"])
            self.assertEqual(result["witnesses"], [])
            self.assertEqual(result["resources"]["lpCalls"], 0)

    def test_conflicting_histories_require_exact_empty_proof(self):
        problem = interval_problem()
        problem["histories"] = [[((Q(1),), Q(1, 5))], [((Q(-1),), Q(-4, 5))]]
        for method in METHODS:
            result = run_method(problem, method, 30, 10)
            self.assertEqual(result["status"], "incompatible")
            self.assertIsNone(result["lowerExact"])
            self.assertIsNone(result["upperExact"])
            self.assertTrue(any(
                all(Q(x) == 0 for x in proof["sourceObjective"]) and Q(proof["sourceUpperExact"]) < 0
                for proof in result["dualProofs"]))

    def test_infeasible_label_without_proof_is_unresolved(self):
        def proposal(engine, objective):
            return None, engine.box_support(objective), "unverified_infeasible"
        for method in METHODS:
            with patch.object(_AuditSet, "lp_proposal", proposal):
                result = run_method(interval_problem(), method, 2, 10)
            self.assertEqual(result["status"], "unresolved")
            self.assertIsNone(result["lowerExact"])
            self.assertLessEqual(result["resources"]["lpCalls"], 2)

    def test_joint_constraint_not_replaced_by_coordinate_box(self):
        problem = {
            "box": [(Q(0), Q(1))] * 2,
            "histories": [[((Q(1), Q(1)), Q(1))]],
            "rivals": [(Q(-1), (Q(1), Q(1)))],
            "threshold": Q(0),
        }
        for method in METHODS:
            result = run_method(problem, method, 30, 10)
            self.assertEqual(result["status"], "safe")
            self.audit(problem, result, Q(0))

    def test_global_witness_reuse_in_every_baseline(self):
        problem = interval_problem()
        problem["rivals"] = [(Q(-1), (Q(1),)), (Q(-3, 5), (Q(1),))]
        for method in METHODS:
            result = run_method(problem, method, 30, 10)
            self.assertEqual(result["status"], "risk_witness")
            self.assertTrue(result["policy"]["globalWitnessReuse"])
            self.assertTrue(all(r["lowerExact"] is not None for r in result["rivals"]))

    def test_dual_reuse_reduces_parallel_rival_certification_work(self):
        # Every rival has the same slope but a different constant. A dual
        # proof of theta<=1/3 simultaneously certifies all three at threshold 0.
        problem = {
            "box": [(Q(0), Q(1))],
            "histories": [[((Q(3),), Q(1))]],
            "rivals": [(Q(-1, 3), (Q(1),)), (Q(-1, 2), (Q(1),)), (Q(-3, 4), (Q(1),))],
            "threshold": Q(0),
        }
        candidate = run_method(problem, "dual_reuse", 30, 10)
        ablation = run_method(problem, "witness_priority", 30, 10)
        self.assertEqual(candidate["status"], "safe")
        self.assertEqual(ablation["status"], "safe")
        self.assertLess(candidate["resources"]["lpCalls"], ablation["resources"]["lpCalls"])
        self.assertGreater(candidate["resources"]["dualRivalEvaluations"], 0)
        self.assertEqual(ablation["resources"]["dualRivalEvaluations"], 0)
        self.audit(problem, candidate, Q(0))

    def test_adaptive_scheduler_reorders_after_bound_tightens(self):
        # The first rival starts at upper 2. A cut reduces it to 1.8 while
        # the second still has upper 1.9; only adaptive ordering switches.
        problem = {
            "box": [(Q(0), Q(1))] * 2,
            "histories": [[((Q(1), Q(0)), Q(4, 5)), ((Q(0), Q(1)), Q(4, 5))]],
            "rivals": [(Q(0), (Q(1), Q(1))), (Q(0), (Q(0), Q(19, 10)))],
            "threshold": Q(17, 10),
        }
        adaptive = run_method(problem, "witness_priority", 30, 10)
        static = run_method(problem, "lazy_priority", 30, 10)
        self.assertEqual([t["rivalIndex"] for t in adaptive["trace"][:3]], [0, 0, 1])
        self.assertEqual([t["rivalIndex"] for t in static["trace"][:3]], [0, 0, 0])
        for result in (adaptive, static):
            self.assertEqual(result["status"], "safe")
            self.audit(problem, result, Q(8, 5))

    def test_hidden_truth_does_not_change_method_result(self):
        first = interval_problem()
        second = copy.deepcopy(first)
        second["truth"] = {"price": 123456}
        second["heldOutTruth"] = {"price": -7}
        a = run_method(first, "dual_reuse", 30, 10)
        b = run_method(second, "dual_reuse", 30, 10)
        for key in ("status", "lowerExact", "upperExact", "witnesses", "rivals", "dualProofs", "trace"):
            self.assertEqual(a[key], b[key])

    def test_expired_setup_still_returns_initial_box_bounds(self):
        for method in METHODS:
            result = run_method(interval_problem(), method, 30, 1e-12)
            self.assertEqual(result["status"], "unresolved")
            self.assertEqual(result["resources"]["lpCalls"], 0)
            self.assertIsNone(result["lowerExact"])
            self.audit(interval_problem(), result, Q(1, 5))

    def test_input_validation_rejects_inexact_or_inconsistent_shapes(self):
        for change in (
            {"box": [(Q(1), Q(0))]},
            {"box": []},
            {"threshold": Q(-1)},
            {"rivals": [(Q(0), (Q(1), Q(2)))]},
            {"histories": [[((0.2,), Q(1))]]},
        ):
            problem = interval_problem()
            problem.update(change)
            with self.assertRaises(ValueError):
                run_method(problem, "dual_reuse", 5, 10)
        for budget, seconds in ((-1, 10), (True, 10), (1, 0), (1, math.inf)):
            with self.assertRaises(ValueError):
                run_method(interval_problem(), "dual_reuse", budget, seconds)


if __name__ == "__main__":
    unittest.main()
