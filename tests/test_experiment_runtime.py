"""Evidence integrity and protocol-contract regression tests."""
import copy
import json
import math
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
from experiment_runtime import exclusive_run, freeze_sources, load_record, read, save, seal_record
from publication_pipeline import archive_regression_case, execute_record, schedules
from comparison_cases import make_case, prepare_problem, problem_from_case
from run_comparison import normalize_result


class RuntimeTests(unittest.TestCase):
    def temporary(self):
        directory = ROOT / "work" / "tmp"
        directory.mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(dir=directory)

    def test_atomic_serialization_failure_preserves_old_record(self):
        with self.temporary() as temp:
            path = Path(temp) / "result.json"
            save(path, {"value": 7})
            with self.assertRaises(ValueError):
                save(path, {"value": math.nan})
            self.assertEqual(read(path), {"value": 7})

    def test_sealed_records_reject_overwrite_and_tampering(self):
        with self.temporary() as temp:
            path = Path(temp) / "result.json"
            seal_record(path, {"value": 7})
            with self.assertRaises(FileExistsError):
                seal_record(path, {"value": 8})
            save(path, {"value": 8})
            with self.assertRaises(ValueError):
                load_record(path)

    def test_failed_outcome_is_not_retried(self):
        with self.temporary() as temp:
            path = Path(temp) / "run.json"
            def failure():
                raise RuntimeError("Deliberate test failure")
            first = execute_record(path, {"caseId": "case"}, failure)
            second = execute_record(path, {"caseId": "case"}, lambda: self.fail("Must not retry"))
            self.assertEqual(first, second)
            self.assertEqual(second["executionStatus"], "failed")

    def test_interrupted_attempt_is_retained(self):
        with self.temporary() as temp:
            path = Path(temp) / "run.json"
            seal_record(Path(str(path) + ".attempt"), {"startedUTC": "test"})
            row = execute_record(path, {}, lambda: self.fail("Must not rerun"))
            self.assertTrue(row["interrupted"])
            self.assertEqual(row["executionStatus"], "failed")

    def test_lock_rejects_concurrent_writer_and_releases(self):
        with self.temporary() as temp:
            with exclusive_run(temp):
                with self.assertRaises(OSError):
                    with exclusive_run(temp):
                        self.fail("Second writer entered")
            with exclusive_run(temp):
                pass

    def test_protocol_counts_duplicates_and_determinism(self):
        protocol = read(ROOT / "research/publication_protocol.json")
        self.assertEqual(schedules(protocol), schedules(protocol))
        bad = copy.deepcopy(protocol)
        bad["methods"].append(bad["methods"][0])
        with self.assertRaises(ValueError):
            schedules(bad)
        bad = copy.deepcopy(protocol)
        bad["planned_comparison_runs"] += 1
        with self.assertRaises(ValueError):
            schedules(bad)

    def test_resume_rejects_source_protocol_snapshot_drift(self):
        with self.temporary() as temp:
            root = Path(temp)
            protocol = root / "protocol.json"
            source = root / "source.py"
            save(protocol, {"version": 1})
            source.write_text("value = 1\n", encoding="utf-8")
            out = root / "batch"
            freeze_sources(root, out, protocol, {"version": 1}, ["source.py"], {"schedule": [1]})
            freeze_sources(root, out, protocol, {"version": 1}, ["source.py"], {"schedule": [1]}, resume=True)
            with self.assertRaises(FileExistsError):
                freeze_sources(root, out, protocol, {"version": 1}, ["source.py"], {"schedule": [1]})
            source.write_text("value = 2\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                freeze_sources(root, out, protocol, {"version": 1}, ["source.py"], {"schedule": [1]}, resume=True)
            source.write_text("value = 1\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                freeze_sources(root, out, protocol, {"version": 2}, ["source.py"], {"schedule": [1]}, resume=True)
            (out / "frozen-source/source.py").write_text("changed\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                freeze_sources(root, out, protocol, {"version": 1}, ["source.py"], {"schedule": [1]}, resume=True)

    def test_rehydration_preserves_decision_and_respects_contract(self):
        case, tables = make_case("menu8", 99101, 0, 0, "unit_test")
        original = prepare_problem(case, tables)
        self.assertEqual(original, problem_from_case(case, tables))
        case["input"]["certification"]["threshold"] = 0.5
        case["input"]["hypotheses"][0]["upper"] = 3
        rebuilt = problem_from_case(case, tables)
        self.assertEqual(rebuilt["threshold"], Fraction(1, 2))
        self.assertEqual(rebuilt["box"][0], (0, 3))
        normalized = normalize_result({"witnesses": []}, case)
        self.assertEqual(normalized["thresholdRational"], "1/2")

    def test_archived_regression_passes_independent_identity_and_math_audit(self):
        from run_followup import profile
        from verify_followup import verify_profile, regression_audit
        from experiment_runtime import sha
        with self.temporary() as temp:
            root = Path(temp)
            case, tables = make_case("menu8", 99102, 1, 0, "regression_test")
            case["id"] = "original-case-id"
            prepare_problem(case, tables)
            source = root / (case["id"] + ".json")
            save(source, case)
            archived = archive_regression_case(root / "batch", source)
            result, _ = profile(case, 1, read(ROOT / "research/publication_protocol.json"))
            record = {"executionStatus": "complete", "caseId": case["id"], "cap": 1,
                      "caseSha256": sha(archived), "result": result}
            audit = verify_profile(case, record, archived)
            self.assertIn("rangeSafe", audit)
            save(root / "batch/regression/prior-false-safe.json", {
                "sourcePath": str(root / "unavailable-original-host" / source.name),
                "sourceSha256": sha(archived), "case": case, "cap": 1,
                "countsAsNewIndependentEvidence": False, "result": result,
            })
            self.assertTrue(regression_audit(root / "batch")["allPassed"])


if __name__ == "__main__":
    unittest.main()
