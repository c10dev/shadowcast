"""Failures, abstentions and positions must not earn credit as clean answers."""

import copy
import unittest

from shadowcast import evaluation


def row(gold=False, flagged=False, positions=(), **changes):
    out = {"item_id": "s-error" if gold else "s-clean", "gold": gold,
           "error_sentence": 2 if gold else None, "n_sentences": 4, "annotation_complete": True,
           "pred": {"has_error": flagged, "sentences": list(positions), "rule": None, "reason": ""}}
    out["pred"].update(changes)
    return out


class Evaluation(unittest.TestCase):
    def test_spec_example(self):
        rows = [row(), row(reason="ERROR: timeout"), row(True, True, [2]), row(True, True, [1])]
        original = copy.deepcopy(rows)
        m = evaluation.evaluate(rows)
        self.assertEqual(m["completion_rate"], 3/4)
        self.assertEqual(m["clean_completion_rate"], 1/2)
        self.assertEqual(m["localization"], 1/2)
        self.assertEqual(m["false_alarm_rate"], 0)
        self.assertEqual(m["denominators"]["false_alarm_rate"], 1)
        self.assertEqual(m["sentence_precision"], 1/2)
        self.assertEqual(rows, original)

    def test_failed_errors_stay_in_overall_localization_denominator(self):
        m = evaluation.evaluate([row(True, True, [2]), row(True, reason="ERROR: timeout")])
        self.assertEqual(m["localization"], .5)
        self.assertEqual(m["localization_completed"], 1)
        self.assertEqual(m["error_completion_rate"], .5)

    def test_all_failed_and_empty_have_no_false_alarm_estimate(self):
        for rows in ([], [row(reason="ERROR: timeout")]):
            m = evaluation.evaluate(rows)
            self.assertIsNone(m["false_alarm_rate"])
            self.assertIsNone(m["false_alarm_ci"])
            self.assertIsNone(m["localization"])
            self.assertIsNone(m["sentence_precision"])
        self.assertIsNone(evaluation.evaluate([])["completion_rate"])

    def test_abstention_is_not_completed(self):
        m = evaluation.evaluate([row(status="ok", verdict="undetermined", issues=["state limit reached"])])
        self.assertEqual(m["counts"]["undetermined"], 1)
        self.assertEqual(m["counts"]["invalid_output"], 0)
        self.assertEqual(m["completion_rate"], 0)
        self.assertIsNone(m["false_alarm_rate"])

    def test_bad_events_are_invalid_even_when_another_event_found_a_violation(self):
        m = evaluation.evaluate([row(True, True, [2], bad_events=["turn lacks target"])])
        self.assertEqual(m["counts"]["invalid_output"], 1)
        self.assertEqual(m["localization"], 0)

    def test_missing_positions_are_not_invented(self):
        m = evaluation.evaluate([row(False, True)])
        self.assertEqual(m["false_alarm_rate"], 1)
        self.assertEqual(m["counts"]["warnings_without_position"], 1)
        self.assertEqual(m["counts"]["warning_sentences"], 0)
        self.assertFalse(m["sentence_metrics_complete"])
        self.assertIsNone(m["sentence_precision"])

    def test_duplicate_positions_count_once(self):
        m = evaluation.evaluate([row(False, True, [1, 1, 2])])
        self.assertEqual(m["counts"]["clean_warning_sentences"], 2)
        self.assertEqual(m["false_alarms_per_100_clean_sentences"], 50)

    def test_unknown_annotation_coverage_disables_precision(self):
        r = row(True, True, [2])
        del r["annotation_complete"]
        self.assertIsNone(evaluation.evaluate([r])["sentence_precision"])

    def test_invalid_types_indices_and_contradictory_fields(self):
        for changes in ({"has_error": "false"}, {"sentences": [True]}, {"sentences": [-1]},
                        {"sentences": [4]}, {"sentences": [{}]}, {"sentences": None},
                        {"sentences": [1]}, {"status": "ok", "verdict": "error"},
                        {"status": "other"}):
            with self.subTest(changes=changes):
                m = evaluation.evaluate([row(**changes)])
                self.assertEqual(m["counts"]["invalid_output"], 1)
                self.assertIsNone(m["false_alarm_rate"])

    def test_legacy_global_rule_does_not_become_per_warning_evidence(self):
        pred = row(True, True, [1, 2], rule="hand_full", reason="global reason")["pred"]
        p = evaluation.normalize_prediction(pred, 4)
        self.assertEqual(p["rule"], "hand_full")
        self.assertTrue(all(w["rule"] is None and not w["evidence"] for w in p["warnings"]))
        self.assertFalse(p["provenance"]["raw_response_checked"])
