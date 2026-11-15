"""Offline analysis binds inputs, preserves sources and cannot call models."""

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from shadowcast import analysis, backends, prompts, runner, scenes
from shadowcast.__main__ import main


ROOT = Path(__file__).resolve().parents[1]


class OfflineAnalysis(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.data = self.folder / "scenes.json"
        self.scene = scenes.load(ROOT / "data/scenes-v2-pilot.json")[0]
        self.data.write_text(json.dumps([self.scene], ensure_ascii=False))
        with redirect_stdout(io.StringIO()):
            main(["run", "--backend", "gold", "--data", str(self.data), "--conditions", "A,C,D",
                  "--results", str(self.folder)])
        self.source = next(self.folder.glob("run-v2-*.json"))

    def test_rescore_preserves_inputs_and_original_metrics_without_network(self):
        before = self.source.read_bytes()
        output = self.folder / "rescore.json"
        with patch.object(backends, "make_backend", side_effect=AssertionError("network forbidden")), \
                patch.object(runner, "load_env", side_effect=AssertionError("credentials forbidden")), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(main(["rescore", str(self.source), "--output", str(output)]), 0)
        result = json.loads(output.read_text())
        original = json.loads(before)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(result["conditions"]["A"]["original_metrics"], original["conditions"]["A"]["metrics"])
        self.assertEqual(result["conditions"]["A"]["metrics"], original["conditions"]["A"]["metrics"])
        self.assertEqual(result["source"]["sha256"], analysis.fingerprint(self.source)["sha256"])
        self.assertEqual(analysis.rescore(self.source)["conditions"], result["conditions"])

    def test_never_overwrites_source_or_existing_output(self):
        before = self.source.read_bytes()
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(["rescore", str(self.source), "--output", str(self.source)]), 1)
        self.assertEqual(self.source.read_bytes(), before)

    def test_legacy_failure_and_annotation_assumption(self):
        report = json.loads(self.source.read_text())
        report.pop("metrics_version")
        report.pop("report_version")
        for result in report["conditions"].values():
            result["metrics"] = result.pop("legacy_metrics")
            for r in result["rows"]:
                r.pop("annotation_complete")
                for key in ("status", "verdict", "issues", "provenance", "warnings"):
                    r["pred"].pop(key, None)
        report["conditions"]["A"]["rows"][0]["pred"]["reason"] = "ERROR: timeout"
        self.source.write_text(json.dumps(report))
        result = analysis.rescore(self.source)
        m = result["conditions"]["A"]["metrics"]
        self.assertEqual(m["counts"]["call_error"], 1)
        self.assertIsNone(m["false_alarm_rate"])
        self.assertIsNone(m["sentence_precision"])
        self.assertIsNotNone(analysis.rescore(self.source, True)["conditions"]["A"]["metrics"]["sentence_precision"])

    def warned_report(self):
        report = json.loads(self.source.read_text())
        row = report["conditions"]["C"]["rows"][0]
        row["pred"].update(has_error=True, sentences=[1], rule="hand_full", reason="synthetic warning")
        self.source.write_text(json.dumps(report))
        return report, row

    def test_audit_attaches_verified_request_and_labels_current_replay(self):
        self.warned_report()
        before = {p: p.read_bytes() for p in self.folder.rglob("*.json")}
        with patch.object(backends, "make_backend", side_effect=AssertionError("network forbidden")):
            result = analysis.audit(self.source, [self.data], self.folder / "cache")
        case, = result["cases"]
        self.assertEqual(case["data_match"], "full_request_match")
        self.assertEqual(case["sentences"], [s["text"] for s in self.scene["sentences"]])
        self.assertFalse(case["replay_matches_saved"])
        self.assertEqual(case["review"]["status"], "unreviewed")
        self.assertEqual(case["review"]["primary_cause"], "unresolved")
        self.assertTrue(all(p.read_bytes() == content for p, content in before.items()))

    def test_semantically_invalid_event_is_not_hidden_by_replay(self):
        report, row = self.warned_report()
        cache = Path(row["pred"]["provenance"]["cache_path"])
        rec = json.loads(cache.read_text())
        rec["output"]["sentences"][0]["events"] = [prompts.flatten({"type": "turn", "character": "민준"})]
        cache.write_text(json.dumps(rec))
        row["pred"]["provenance"]["cache_sha256"] = analysis.fingerprint(cache)["sha256"]
        self.source.write_text(json.dumps(report))
        case, = analysis.audit(self.source, [self.data], self.folder / "cache")["cases"]
        self.assertEqual(case["replay_bad_events"][0]["rule"], "bad_event")
        self.assertFalse(case["replay_matches_saved"])
        self.assertIn("semantic event errors prevent a complete diagnostic replay", case["missing"])

    def test_missing_cache_remains_unresolved(self):
        self.warned_report()
        result = analysis.audit(self.source, [self.data])
        case, = result["cases"]
        self.assertEqual(case["data_match"], "unverified")
        self.assertTrue(case["missing"])
        self.assertNotIn("trace", case)

    def test_changed_text_cannot_bind_legacy_cache(self):
        report, _ = self.warned_report()
        report.pop("provenance")  # legacy run has no dataset fingerprint
        self.source.write_text(json.dumps(report))
        changed = copy.deepcopy(self.scene)
        changed["sentences"][0]["text"] += " 달라진 본문."
        self.data.write_text(json.dumps([changed], ensure_ascii=False))
        case, = analysis.audit(self.source, [self.data], self.folder / "cache")["cases"]
        self.assertEqual(case["data_match"], "unverified")
        self.assertNotIn("trace", case)

    def test_changed_cache_is_rejected(self):
        _, row = self.warned_report()
        cache = Path(row["pred"]["provenance"]["cache_path"])
        rec = json.loads(cache.read_text())
        rec["output"]["sentences"][0]["events"] = []
        cache.write_text(json.dumps(rec))
        case, = analysis.audit(self.source, [self.data], self.folder / "cache")["cases"]
        self.assertEqual(case["data_match"], "unverified")
        self.assertIn("cache content changed since the run", case["missing"])

    def test_duplicate_rows_are_rejected(self):
        report = json.loads(self.source.read_text())
        report["conditions"]["A"]["rows"].append(report["conditions"]["A"]["rows"][0])
        self.source.write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError, "duplicate row"):
            analysis.rescore(self.source)

    def test_analysis_output_is_not_silently_rescored_as_original(self):
        self.source.write_text(json.dumps(analysis.rescore(self.source)))
        with self.assertRaisesRegex(ValueError, "original run"):
            analysis.rescore(self.source)
