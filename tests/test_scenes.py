"""Scene format tests: v1 conversion, the example file, and validation messages."""

import unittest
from pathlib import Path

from shadowcast import scenes

ROOT = Path(__file__).parent.parent
V1 = ROOT / "hand-check" / "data" / "scenes.json"
EXAMPLE = ROOT / "data" / "scenes-v2-example.json"
PILOT = ROOT / "data" / "scenes-v2-pilot.json"


class V1Data(unittest.TestCase):
    def test_all_v1_scenes_pass_with_the_v2_rules(self):
        n_scenes, n_items, problems = scenes.validate_files([V1])
        self.assertEqual((n_scenes, n_items, problems), (40, 80, []))

    def test_conversion_keeps_ids_and_rule(self):
        s = scenes.load(V1)[0]
        self.assertEqual(s["source"], "hand-check v1")
        self.assertEqual(len(s["errors"]), 1)
        self.assertEqual(s["errors"][0]["rule"], "hand_full")
        ids = [i["item_id"] for i in scenes.expand(s)]
        self.assertEqual(ids, [f"{s['id']}-clean", f"{s['id']}-error"])


class ExampleData(unittest.TestCase):
    def test_example_passes(self):
        self.assertEqual(scenes.validate_files([EXAMPLE]), (1, 5, []))

    def test_each_error_breaks_its_rule(self):
        scene = scenes.load(EXAMPLE)[0]
        got = {}
        for item in scenes.expand(scene)[1:]:
            _, violations = scenes.run_item(item)
            got[item["item_id"]] = sorted({v["rule"] for v in violations})
        self.assertEqual(got, {"x01-error1": ["facing_mismatch"], "x01-error2": ["layer_order"],
                               "x01-error3": ["space_full"], "x01-error4": ["hand_full"]})


class PilotData(unittest.TestCase):
    def test_pilot_passes(self):
        self.assertEqual(scenes.validate_files([PILOT]), (10, 32, []))

    def test_pilot_covers_each_rule(self):
        # not_held is a slip of event lists more than of prose, so no pilot scene targets it.
        labels = {e["rule"] for p in (PILOT, EXAMPLE) for s in scenes.load(p) for e in s["errors"]}
        self.assertEqual(labels, {"hand_full", "tool_missing", "facing_mismatch", "hidden_side", "layer_order",
                                  "not_worn", "space_full", "contact_kept", "item_location", "state_mismatch"})


class Validation(unittest.TestCase):
    def scene(self, **change):
        base = {"id": "t1", "initial_state": {"지호": {"hands": {"left": "컵", "right": None}}},
                "sentences": [{"text": "a", "events": []}, {"text": "b", "events": []}],
                "errors": [{"sentence": 1, "text": "b2",
                            "events": [{"type": "use", "character": "지호", "hand": "both",
                                        "free_hands_needed": 2, "action": "x"}],
                            "rule": "hand_full"}]}
        return {**base, **change}

    def test_good_scene(self):
        self.assertEqual(scenes.validate_scene(self.scene()), [])

    def test_clean_item_with_a_violation(self):
        s = self.scene(sentences=[{"text": "a", "events": [{"type": "grab", "character": "지호", "object": "책"},
                                                          {"type": "grab", "character": "지호", "object": "펜"}]},
                                  {"text": "b", "events": []}])
        self.assertTrue(any("clean item has violations" in p for p in scenes.validate_scene(s)))

    def test_later_failure_in_the_error_sentence_is_allowed(self):
        s = self.scene()
        s["errors"][0]["events"].append({"type": "release", "character": "지호", "hand": "right", "object": "책"})
        _, violations = scenes.run_item(scenes.expand(s)[1])
        self.assertEqual([v["rule"] for v in violations], ["hand_full", "not_held"])
        self.assertEqual(scenes.validate_scene(s), [])

    def test_wrong_rule_label(self):
        s = self.scene()
        s["errors"][0]["rule"] = "layer_order"
        self.assertTrue(any("expected rule layer_order" in p for p in scenes.validate_scene(s)))

    def test_unknown_event_type_and_missing_field(self):
        s = self.scene(sentences=[{"text": "a", "events": [{"type": "jump", "character": "지호"},
                                                          {"type": "grab", "character": "지호"}]},
                                  {"text": "b", "events": []}])
        problems = scenes.validate_scene(s)
        self.assertTrue(any("unknown event type 'jump'" in p for p in problems))
        self.assertTrue(any("grab event lacks ['object']" in p for p in problems))

    def test_error_sentence_out_of_range(self):
        s = self.scene()
        s["errors"][0]["sentence"] = 5
        self.assertTrue(any("out of range" in p for p in scenes.validate_scene(s)))


if __name__ == "__main__":
    unittest.main()
