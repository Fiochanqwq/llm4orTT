import copy
import json
import math
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from fractions import Fraction as Q
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
from language_instances import generate, inventory, check_no_leak, FORBIDDEN
from language_stage import request_for, verify_prompt
from language_evaluator import materialize, score
from language_decisions import vertices, endpoint, parse_proposal, decide
from language_statistics import proportion, paired, summarize
from language_call_records import count_language_calls


class LeakTests(unittest.TestCase):
    def setUp(self):
        self.blueprint = generate("dispatch", 81001)
        self.public, self.truth = materialize(self.blueprint)

    def check(self, value):
        return check_no_leak(value, self.public["catalog"], self.truth["thetaTenths"])

    def test_all_62_tasks_pass_both_text_and_full_prompt_checks(self):
        pilots, formal = inventory()
        self.assertEqual(len(formal), 60)
        self.assertEqual(len({(v["domain"], v["seed"]) for v in formal}), 60)
        for spec in pilots + formal:
            blueprint = generate(**spec)
            public, truth = materialize(blueprint)
            self.assertEqual(len(public["logs"]), 4)
            self.assertTrue(check_no_leak(public, public["catalog"], truth["thetaTenths"])["passed"])
            self.assertTrue(verify_prompt(public, request_for(public)))
            self.assertEqual(blueprint, generate(**spec))
            self.assertEqual((public, truth), materialize(generate(**spec)))

    def test_each_id_label_truth_key_and_banned_word_fails_with_name(self):
        terms = [h[k] for h in self.public["catalog"] for k in ("id", "label")]
        terms += list(self.truth["thetaTenths"]) + FORBIDDEN
        for field in ("description", "logs"):
            for term in terms:
                public = copy.deepcopy(self.public)
                if field == "description":
                    public[field] += " " + term
                else:
                    public[field][0] += " " + term
                with self.assertRaisesRegex(ValueError, __import__("re").escape(term)):
                    self.check(public)

    def test_structure_token_alone_is_rejected(self):
        public = copy.deepcopy(self.public)
        public["logs"][0] += " WORKLOAD "
        with self.assertRaisesRegex(ValueError, "workload"):
            self.check(public)

    def test_unicode_and_case_do_not_bypass(self):
        public = copy.deepcopy(self.public)
        public["description"] += " ＴＲＵＴＨ "
        with self.assertRaisesRegex(ValueError, "truth"):
            self.check(public)

    def test_private_evaluator_keys_never_in_request(self):
        request = json.dumps(request_for(self.public))
        for key in ("activeFactor", "thetaTenths", "histories", "deployment", "truth.json", "trueRegret"):
            self.assertNotIn(key, request)

    def test_real_cli_imports_under_embedded_python(self):
        result = subprocess.run([sys.executable, "-B", "-X", "utf8",
                                 str(ROOT / "research" / "language_stage.py"), "--help"],
                                cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_prompt_runtime_blocks_truth_file_open(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "research" / "scratch") as temp:
            directory = Path(temp) / "language" / "truth"
            directory.mkdir(parents=True)
            truth_file = directory / "test.json"
            truth_file.write_text('{"secret": 123}', encoding="utf-8")
            self.assertTrue(verify_prompt(self.public, request_for(self.public)))
            with patch("language_stage.encoded", side_effect=lambda value: truth_file.read_text("utf-8")):
                with self.assertRaisesRegex(PermissionError, "Prompt construction cannot open.*truth"):
                    request_for(self.public)
            self.assertEqual(json.loads(truth_file.read_text("utf-8"))["secret"], 123)


class ExactAuditTests(unittest.TestCase):
    def test_cube_vertices_and_empty_zero_dimensional_set(self):
        rows = []
        for j in range(3):
            unit = tuple(int(j == k) for k in range(3))
            rows.extend([(unit, 20), (tuple(-v for v in unit), 0)])
        self.assertEqual(len(vertices(rows, 3)), 8)
        self.assertEqual(vertices([((), -1)], 0), [])
        self.assertEqual(vertices([((), 0)], 0), [((), 1)])

    def test_fractional_lower_dimensional_polytope(self):
        # x+y=1, x>=1/3, y>=0, bounded square
        rows = [((1, 1), 1), ((-1, -1), -1), ((-3, 0), -1),
                ((0, -1), 0), ((1, 0), 2), ((0, 1), 2)]
        values = {tuple(Q(n, d) for n in nums) for nums, d in vertices(rows, 2)}
        self.assertEqual(values, {(Q(1, 3), Q(2, 3)), (Q(1), Q(0))})

    def test_correct_structure_upper_certificate_contains_truth(self):
        # Independent direct evaluation must never exceed the exact upper bound.
        for domain in ("dispatch", "staffing", "workshop"):
            for seed in (79001, 79002, 79003):
                public, truth = materialize(generate(domain, seed))
                selected = sorted(truth["thetaTenths"])
                for action in public["deployment"]["actions"]:
                    result = endpoint(public, selected, action["id"], 1)
                    self.assertIn(result["status"], ("safe", "risk"))
                    fake = {"selected": selected, "chosenDecision": action["id"],
                            **{a: {"status": "safe", "released": True} for a in ("A0", "A1", "A2")}}
                    observed = score(public, truth, fake)
                    self.assertLessEqual(Q(observed["trueRegret"]), Q(result["worstRegret"]))

    def test_no_repair_for_unknown_or_duplicate_monitors(self):
        public, _ = materialize(generate("dispatch", 79001))
        with self.assertRaisesRegex(ValueError, "Unknown"):
            parse_proposal({"hypotheses": [{"monitor": "m9"}]}, public["catalog"])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            parse_proposal({"hypotheses": [{"monitor": "m0"}, {"monitor": "m0"}]}, public["catalog"])
        self.assertEqual(parse_proposal({"hypotheses": []}, public["catalog"]), [])

    def test_pure_fit_then_audit_executes_without_truth(self):
        public, _ = materialize(generate("workshop", 79001))
        selected = sorted(h["id"] for h in public["catalog"])
        result = decide(public, selected)
        self.assertEqual(result["fit"]["status"], "optimal")
        self.assertTrue(result["A0"]["released"])
        if result["A2"]["upper"]["status"] == "risk":
            self.assertFalse(result["A2"]["released"])


class StatisticsTests(unittest.TestCase):
    def test_wilson_endpoints_and_symmetry(self):
        self.assertAlmostEqual(proportion(0)["wilson95"][1], 0.060171852142089886)
        self.assertAlmostEqual(proportion(60)["wilson95"][0], 1 - proportion(0)["wilson95"][1])
        self.assertAlmostEqual(sum(proportion(30)["wilson95"]), 1)

    def test_exact_paired_test_is_symmetric(self):
        a, b = [1] * 6 + [0] * 54, [0] * 60
        self.assertEqual(paired(a, b)["pExactTwoSided"], 0.03125)
        self.assertEqual(paired(b, a)["pExactTwoSided"], 0.03125)
        self.assertEqual(paired(b, b)["pExactTwoSided"], 1)
        self.assertEqual(paired(a, b)["A0only"], 6)

    def test_all_failed_still_has_denominator_60(self):
        summary = summarize([{"id": str(i), "status": "failed", "scores": {}} for i in range(60)])
        self.assertEqual(summary["primary"]["A0"]["dangerousReleased"]["denominator"], 60)
        self.assertEqual(summary["primary"]["A2"]["availableCorrect"]["count"], 0)
        self.assertEqual(summary["direction"], "未观察到差异")
        self.assertEqual(summary["selectedInterpretation"], "alwaysAbstain")

    def test_absent_language_stage_means_zero_calls(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "research" / "scratch") as temp:
            self.assertEqual(count_language_calls(temp)["newModelCalls"], 0)


if __name__ == "__main__":
    unittest.main()
