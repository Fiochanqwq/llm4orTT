"""No-network tests of information isolation and scoring, using temporary data."""
from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))
import decision_contract_study as study


BOX = {"sense": "min", "objective": ["1", "1"], "constraints": [
    {"a": ["1", "0"], "op": "<=", "b": "2"},
    {"a": ["0", "1"], "op": "<=", "b": "3"}]}


def case(identifier="731"):
    return {"id": identifier, "text": "Make apples and pears under the stated budgets.",
            "variables": ["apples", "pears"], "split": "heldout",
            "reference": deepcopy(BOX), "private_secret": "PRIVATE_REFERENCE_SENTINEL",
            "source_objective_direction": "PRIVATE_DIRECTION_SENTINEL"}


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        # Use an explicitly writable project directory; the Windows sandbox's
        # redirected system temporary directory need not allow child writes.
        self.temp_root = Path(__file__).resolve().parents[1] / "实验/决策契约研究_2026-10-21_01/_protocol_test_tmp"
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=self.temp_root)
        self.out = Path(self.temp.name)
        self.out_patch = patch.object(study, "OUT", self.out)
        self.out_patch.start()

    def tearDown(self):
        self.out_patch.stop()
        self.assertTrue(self.out.resolve().is_relative_to(self.temp_root.resolve()))
        self.temp.cleanup()

    def write_result(self, identifier, arm, payload, status="complete", raw=False):
        dest = self.out / "network" / (identifier + "_" + arm + ".result.json")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps({"status": status, "text": payload if raw else json.dumps(payload)}), "utf-8")

    def test_public_prompt_has_explicit_whitelist(self):
        c = case()
        public = study.public_prompt(c)
        self.assertEqual(set(public), {"public_problem", "variable_catalog", "task_scope"})
        self.assertEqual(public["variable_catalog"], {"x0": "apples", "x1": "pears"})
        before = deepcopy(public)
        c["reference"] = {"secret": "CHANGED_PRIVATE_REFERENCE"}
        self.assertEqual(study.public_prompt(c), before)
        self.assertNotIn("SENTINEL", json.dumps(study.request("test", public)))

    def test_initial_queues_do_not_depend_on_reference(self):
        c = case()
        with patch.object(study, "cases", return_value=[c]), contextlib.redirect_stdout(io.StringIO()):
            study.initial_queue("heldout")
        queue = study.read(self.out / "heldout-initial-queue.json")
        self.assertEqual(len(queue), 2)
        for request in queue:
            payload = json.loads(request["messages"][1]["content"])
            self.assertEqual(set(payload), {"public_problem", "variable_catalog", "task_scope", "instruction"})
            self.assertNotIn("SENTINEL", json.dumps(request))

    def test_repair_arms_share_all_inputs_except_witness_payload(self):
        c = case()
        other = deepcopy(BOX)
        other["constraints"].append({"a": ["1", "1"], "op": "<=", "b": "4"})
        self.write_result(c["id"], "A", BOX)
        self.write_result(c["id"], "B", other)
        with patch.object(study, "cases", return_value=[c]), contextlib.redirect_stdout(io.StringIO()):
            study.repair_queue("heldout")
        queue = study.read(self.out / "heldout-repair-queue.json")
        by_arm = {r["id"].rsplit("_", 1)[1]: r for r in queue}
        a = json.loads(by_arm["abstract"]["messages"][1]["content"])
        w = json.loads(by_arm["witness"]["messages"][1]["content"])
        self.assertEqual(by_arm["abstract"]["maxTokens"], by_arm["witness"]["maxTokens"])
        self.assertEqual(by_arm["abstract"]["messages"][0], by_arm["witness"]["messages"][0])
        self.assertTrue(w.pop("exact_concrete_witnesses"))
        w.pop("witness_note")
        self.assertEqual(a, w)
        self.assertFalse(a["exact_relation_diagnostics"]["feasible_sets_equal"])
        self.assertNotIn("SENTINEL", json.dumps(queue))

    def test_agreement_and_invalid_candidates_have_no_fabricated_witness(self):
        same = case("732")
        broken = case("733")
        for arm in ("A", "B"):
            self.write_result(same["id"], arm, BOX)
        self.write_result(broken["id"], "A", "not JSON", raw=True)
        self.write_result(broken["id"], "B", BOX)
        with patch.object(study, "cases", return_value=[same, broken]), contextlib.redirect_stdout(io.StringIO()):
            study.repair_queue("heldout")
        for row in study.read(self.out / "heldout-diagnostics.json"):
            self.assertEqual(row["witnesses"], [])
        bad = study.read(self.out / "heldout-diagnostics.json")[1]
        self.assertEqual(bad["verdict"]["status"], "candidate_parse_failure")

    def test_invalid_and_incomplete_outputs_are_rejected(self):
        invalid = [{}, [], None, {**BOX, "sense": "maximize"}, {**BOX, "objective": [1, float("nan")]},
                   {**BOX, "objective": [1]}, {**BOX, "objective": [True, 1]},
                   {**BOX, "constraints": [{"a": [1, 0], "op": "<", "b": 1}]},
                   {**BOX, "constraints": [{"a": [1, 0], "op": "<=", "b": "1/0"}]}]
        for value in invalid:
            with self.subTest(value=value):
                self.write_result("731", "A", value)
                self.assertFalse(study.candidate(case(), "A")["valid"])
        self.write_result("731", "A", BOX, status="length")
        self.assertFalse(study.candidate(case(), "A")["valid"])
        self.assertFalse(study.candidate(case(), "missing")["valid"])

    def test_unsupported_semantics_not_silently_discarded(self):
        for field, value in (("integrality", [1, 1]), ("objective_offset", 7), ("variables", {"x0": "integer"})):
            with self.subTest(field=field):
                self.write_result("731", "A", {**BOX, field: value})
                self.assertFalse(study.candidate(case(), "A")["valid"])
        badrow = deepcopy(BOX)
        badrow["constraints"][0]["strict"] = True
        self.write_result("731", "A", badrow)
        self.assertFalse(study.candidate(case(), "A")["valid"])

    def test_known_scoring_contract_separates_value_region_face_and_order(self):
        cases = [case(str(740 + i)) for i in range(4)]
        # Equal value/optimal point but a smaller feasible region must fail.
        smaller = deepcopy(BOX)
        smaller["constraints"].append({"a": [1, 1], "op": "<=", "b": 4})
        # Same feasible region/value but a larger optimal face must fail.
        face = {**BOX, "objective": [1, 0]}
        # Same feasible region/optimal point, different full objective order:
        # current-instance primary passes, separate order flag must fail.
        order = {**BOX, "objective": [2, 1]}
        predictions = [smaller, face, order, {}]
        for c, prediction in zip(cases, predictions):
            for arm in ("A", "B", "abstract", "witness"):
                self.write_result(c["id"], arm, prediction if arm != "witness" else BOX)
        with patch.object(study, "cases", return_value=cases), contextlib.redirect_stdout(io.StringIO()):
            study.evaluate("heldout")
        rows = study.read(self.out / "heldout-scores.json")
        self.assertEqual([r["arms"]["abstract"]["success"] for r in rows], [False, False, True, False])
        self.assertFalse(rows[2]["arms"]["abstract"]["comparison"]["objective_order_equal"])
        self.assertEqual([r["arms"]["witness"]["success"] for r in rows], [True] * 4)
        summary = study.read(self.out / "heldout-summary.json")
        self.assertEqual(summary["n"], 4)
        self.assertEqual(summary["primary"]["gains"], 3)
        self.assertEqual(summary["primary"]["losses"], 0)
        self.assertEqual(summary["primary"]["pExact"], .25)
        self.assertFalse(summary["positiveGate"])

    def test_exact_paired_test_known_answers(self):
        r = study.mcnemar([False] * 6, [True] * 6)
        self.assertEqual(r["pExact"], .03125)
        self.assertEqual(r["difference"], 1)
        self.assertEqual(r["pairedBootstrap95"], [1, 1])
        r = study.mcnemar([False, True], [True, False])
        self.assertEqual(r["pExact"], 1)
        self.assertEqual(r["difference"], 0)


if __name__ == "__main__":
    unittest.main()
