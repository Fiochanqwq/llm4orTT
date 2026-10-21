"""Adversarial tests of the independent two-dimensional comparison audit."""
import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
from verify_comparison import prepare_case, verify_one, verify_prepared


def context(identifier="history", decision=1, base=-1, features=(1, 1)):
    return {
        "id": identifier,
        "model": {
            "sense": "minimize",
            "variables": [{"name": "x", "type": "binary", "lower": 0, "upper": 1}],
            "objective": {"x": base},
            "constraints": [],
        },
        "features": {
            "p0": {"kind": "linear", "terms": {"x": features[0]}},
            "p1": {"kind": "linear", "terms": {"x": features[1]}},
        },
        "decision": {"x": decision},
    }


def data():
    # The observed x=1 implies p0+p1<=1 in [0,1]^2.
    return {
        "schema": "contextual-inverse.v1",
        "hypotheses": [{"id": "p0", "lower": 0, "upper": 1},
                       {"id": "p1", "lower": 0, "upper": 1}],
        "samples": [context()],
        "deployment": context("deployment", base=-0.5),
        "certification": {"noise": {"kind": "absolute", "budget": 0}, "threshold": 0.25},
    }


def result(status="risk_witness", low=0.5, high=0.5):
    return {
        "chosenDecision": {"x": 1}, "status": status,
        "lowerBound": low, "upperBound": high, "threshold": 0.25,
        "witnesses": [{"p0": "1", "p1": "0"}],
    }


class IndependentComparisonAuditTests(unittest.TestCase):
    def test_joint_polygon_exact_regret_and_truth(self):
        audited = verify_one(data(), result(), {"p0": 0.2, "p1": 0.3})
        self.assertEqual(audited["vertexCount"], 3)
        self.assertEqual(audited["exactWorstRegretRational"], "1/2")
        self.assertEqual(audited["exactTrueRegretRational"], "0")
        self.assertTrue(audited["truthContained"])
        self.assertEqual(audited["historyActionCounts"], [2])

    def test_inward_upper_bound_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "upper bound"):
            verify_one(data(), result(high=0.49, low=0))

    def test_invented_lower_bound_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "supporting"):
            verify_one(data(), result(low=0.6, high=0.8))

    def test_out_of_box_witness_is_rejected(self):
        saved = result()
        saved["witnesses"] = [{"p0": "2", "p1": "-1"}]
        with self.assertRaisesRegex(ValueError, "full historical budget"):
            verify_one(data(), saved)

    def test_joint_budget_violating_witness_is_rejected(self):
        saved = result()
        saved["witnesses"] = [{"p0": "1", "p1": "1"}]
        with self.assertRaisesRegex(ValueError, "full historical budget"):
            verify_one(data(), saved)

    def test_missing_witness_cannot_support_lower_bound(self):
        saved = result("unresolved", low=0, high=1)
        saved["witnesses"] = []
        with self.assertRaisesRegex(ValueError, "supporting"):
            verify_one(data(), saved)

    def test_no_evidence_can_remain_unresolved(self):
        saved = result("unresolved", low=None, high=1)
        saved["witnesses"] = []
        audited = verify_one(data(), saved)
        self.assertEqual(audited["verifiedWitnesses"], 0)
        self.assertEqual(audited["exactWorstRegretRational"], "1/2")

    def test_safe_requires_nonempty_set_evidence(self):
        saved = result("safe", low=None, high=0.5)
        saved.update(threshold=0.5, witnesses=[])
        with self.assertRaisesRegex(ValueError, "nonempty-set evidence"):
            verify_one(data(), saved)

    def test_false_safe_release_rejected(self):
        with self.assertRaisesRegex(ValueError, "False safe"):
            verify_one(data(), result("safe"))

    def test_threshold_equality_is_safe_and_not_risky(self):
        saved = result("safe")
        saved["thresholdRational"] = "1/2"
        self.assertTrue(verify_one(data(), saved)["verified"])
        saved["status"] = "risk_witness"
        with self.assertRaisesRegex(ValueError, "above the declared threshold"):
            verify_one(data(), saved)

    def test_exact_threshold_overrides_rounded_float(self):
        saved = result()
        saved["threshold"] = 0.500001
        saved["thresholdRational"] = "499999999999999999999/1000000000000000000000"
        self.assertTrue(verify_one(data(), saved)["verified"])

    def test_false_empty_set_claim_rejected(self):
        saved = result("incompatible", low=None, high=None)
        saved["witnesses"] = []
        with self.assertRaisesRegex(ValueError, "False empty-set"):
            verify_one(data(), saved)

    def test_true_empty_set_and_nonvacuous_safety(self):
        instance = data()
        instance["samples"] = [context("low", base=-0.2, features=(1, 0)),
                               context("high", decision=0, base=-0.8, features=(1, 0))]
        saved = result("incompatible", low=None, high=None)
        saved["witnesses"] = []
        audited = verify_one(instance, saved, {"p0": 0.5, "p1": 0.5})
        self.assertTrue(audited["feasibleSetEmpty"])
        self.assertFalse(audited["truthContained"])
        self.assertIsNone(audited["exactWorstRegretRational"])
        saved["status"] = "safe"
        with self.assertRaisesRegex(ValueError, "Empty set"):
            verify_one(instance, saved)

    def test_degenerate_segment_and_singleton(self):
        instance = data()
        instance["samples"].append(context("opposite", decision=0))
        saved = result("safe")
        saved["thresholdRational"] = "1/2"
        self.assertEqual(verify_one(instance, saved)["vertexCount"], 2)
        instance["hypotheses"][0]["upper"] = 0
        saved["witnesses"] = [{"p0": "0", "p1": "1"}]
        self.assertEqual(verify_one(instance, saved)["vertexCount"], 1)

    def test_integer_actions_original_constraints_and_soft_features(self):
        instance = data()
        sample = context(base=-1, features=(0, 0))
        sample["model"]["variables"][0].update(type="integer", lower=0, upper=3)
        sample["model"]["constraints"] = [{"terms": {"x": 1}, "sense": "<=", "rhs": 2}]
        sample["features"]["p0"] = {"kind": "soft", "terms": {"x": 1}, "sense": "<=", "rhs": 1}
        sample["features"]["p1"] = {"kind": "soft", "terms": {"x": 1}, "sense": ">=", "rhs": 1}
        sample["decision"] = {"x": 2}
        instance["samples"] = [sample]
        instance["deployment"] = copy.deepcopy(sample)
        saved = result("safe", low=0, high=0)
        saved.update(chosenDecision={"x": 2}, witnesses=[{"p0": "1", "p1": "1"}])
        audited = verify_one(instance, saved)
        self.assertEqual(audited["deploymentActionCount"], 3)
        self.assertEqual(audited["exactWorstRegretRational"], "0")

    def test_infeasible_original_decision_rejected(self):
        saved = result()
        saved["chosenDecision"] = {"x": 2}
        with self.assertRaisesRegex(ValueError, "original model"):
            verify_one(data(), saved)

    def test_boolean_decision_rejected(self):
        saved = result()
        saved["chosenDecision"] = {"x": True}
        with self.assertRaisesRegex(ValueError, "numeric"):
            verify_one(data(), saved)

    def test_deployment_placeholder_is_never_used_as_history(self):
        instance = data()
        first = verify_one(instance, result())
        instance["deployment"]["decision"] = {"x": 1234}
        self.assertEqual(first, verify_one(instance, result()))

    def test_per_history_budgets_and_truth_outside_are_reported(self):
        instance = data()
        instance["certification"]["noise"] = {"kind": "absolute", "budgets": {"history": 0}}
        audited = verify_one(instance, result(), {"p0": 0.8, "p1": 0.8})
        self.assertFalse(audited["truthContained"])
        self.assertEqual(audited["exactTrueRegretRational"], "11/10")

    def test_reuse_does_not_mutate_or_allow_changed_candidate(self):
        prepared = prepare_case(data(), {"x": 1})
        first = verify_prepared(prepared, result())
        self.assertEqual(first, verify_prepared(prepared, result()))
        saved = result()
        saved["chosenDecision"] = {"x": 0}
        with self.assertRaisesRegex(ValueError, "frozen"):
            verify_prepared(prepared, saved)


if __name__ == "__main__":
    unittest.main()
