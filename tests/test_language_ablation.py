import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))
from language_ablation import without_logs, assert_paired_requests, confusion


class AblationTests(unittest.TestCase):
    def test_only_logs_removed_and_original_unchanged(self):
        task = {"description": "plain", "logs": ["clue"], "observations": [{"monitor": "m0"}]}
        request = {"model": "fixed", "messages": [{"role": "system", "content": "unchanged"},
                   {"role": "user", "content": "prefix\n" + json.dumps(task)}]}
        original = copy.deepcopy(request)
        changed = without_logs(request)
        self.assertEqual(request, original)
        payload = json.loads(changed["messages"][1]["content"].split("\n", 1)[1])
        self.assertEqual(payload, {k: v for k, v in task.items() if k != "logs"})
        assert_paired_requests(request, changed)
        changed["model"] = "other"
        with self.assertRaises(ValueError):
            assert_paired_requests(request, changed)

    def test_abstentions_are_not_true_negatives(self):
        rows = [{"scores": {"L1": {"dangerous": d, "arms": {"A2": {"status": s}}}}}
                for d, s in [(True, "risk"), (True, "safe"), (False, "risk"),
                             (False, "safe"), (True, "unresolved"), (False, "incompatible")]]
        got = confusion(rows)
        self.assertEqual([got[k] for k in ("TP", "FN", "FP", "TN")], [1, 1, 1, 1])
        self.assertEqual(got["sensitivity"]["rate"], 1 / 3)
        self.assertEqual(got["specificity"]["rate"], 1 / 3)
        self.assertEqual(got["explicitOnlySensitivity"]["rate"], .5)

    def test_missing_and_zero_denominator_explicit(self):
        got = confusion([{"scores": {}}])
        self.assertEqual(got["missing"], 1)
        self.assertIsNone(got["sensitivity"]["rate"])
        self.assertIsNone(got["specificity"]["rate"])


if __name__ == "__main__":
    unittest.main()
