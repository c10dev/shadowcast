"""Prompt and schema tests: the flat extraction schema can express every gold event."""

import re
import unittest
from pathlib import Path

from shadowcast import prompts, rules, scenes

ROOT = Path(__file__).parent.parent
FILES = [ROOT / "data" / "scenes-v2-pilot.json", ROOT / "data" / "scenes-v2-example.json",
         ROOT / "hand-check" / "data" / "scenes.json"]


def all_items():
    return [i for p in FILES for s in scenes.load(p) for i in scenes.expand(s)]


class FlatEvents(unittest.TestCase):
    def test_round_trip_keeps_the_verdict(self):
        for item in all_items():
            flat = [[prompts.normalize(prompts.flatten(e), item["initial_state"]) for e in ev] for ev in item["events"]]
            run = lambda events: rules.run_scene(item["initial_state"], events, item.get("items"), item.get("aliases"))
            self.assertEqual(run(flat), run(item["events"]), item["item_id"])

    def test_gold_events_fit_the_schema(self):
        props = prompts.EVENT_SCHEMA["properties"]
        self.assertEqual(set(prompts.EVENT_SCHEMA["required"]), set(props))
        for item in all_items():
            for ev in item["events"]:
                for e in ev:
                    flat = prompts.flatten(e)
                    self.assertEqual(set(flat), set(props), e)
                    for k, v in flat.items():
                        if "enum" in props[k]:
                            self.assertIn(v, props[k]["enum"], (item["item_id"], k, v))

    def test_names_without_at_become_people(self):
        flat = {**prompts.flatten({"type": "release", "character": "정우", "object": "은숙"})}
        self.assertEqual(prompts.normalize(flat, ["정우", "은숙"])["object"], "@은숙")
        self.assertEqual(prompts.normalize(flat, ["정우"])["object"], "은숙")  # not a person in this scene

    def test_empty_fields_are_dropped(self):
        flat = prompts.flatten({"type": "grab", "character": "지호", "object": "컵"})
        self.assertEqual(prompts.normalize(flat), {"type": "grab", "character": "지호", "object": "컵"})


class Prompts(unittest.TestCase):
    def item(self, item_id="x01-clean"):
        return next(i for i in all_items() if i["item_id"] == item_id)

    def test_state_text(self):
        text = prompts.format_state(self.item())
        self.assertIn("- 민준: 왼손=손잡이; 오른손=빈손; 유나에게 앞(마주 봄)을 보임; "
                      "착용(torso)=셔츠 → 백팩 (안쪽 → 바깥); 몸 앞=유나(사람); 몸 뒤=백팩", text)
        self.assertIn("- 통지서: 민준 바지 앞주머니에 있음", text)
        self.assertIn("- '가방'는 '백팩'와 같은 물건", text)

    def test_unknown_person_has_no_state(self):
        self.assertIn("- 지아: 몸 뒤=비었음", prompts.format_state(self.item("p06-clean")))

    def test_condition_a_has_no_state(self):
        item = self.item()
        self.assertNotIn("장면 시작 상태", prompts.judge_prompt(item, with_state=False))
        self.assertIn("장면 시작 상태", prompts.judge_prompt(item, with_state=True))

    def test_extract_prompt_lists_people_and_objects(self):
        text = prompts.extract_prompt(self.item())
        self.assertIn("인물: 민준, 유나", text)
        self.assertIn("물건 목록: 손잡이, 셔츠, 백팩, 통지서, 물병", text)

    def test_object_list_does_not_leak_gold_events(self):
        # 휴대폰 first appears in p07 error 2 events; the list must not name it.
        self.assertNotIn("휴대폰", prompts.extract_prompt(self.item("p07-error2")).split("문단")[0])

    def test_judge_rules_match_the_checker(self):
        documented = re.findall(r"^  (\w+)\s{2,}", rules.__doc__.split("Violation rules")[1], re.M)
        self.assertEqual(prompts.RULES, documented)
        self.assertEqual(prompts.JUDGE_SCHEMA["properties"]["rule"]["enum"], documented + ["none"])

    def test_event_types_match_the_checker(self):
        self.assertEqual(set(prompts.EVENT_TYPES), set(scenes.REQUIRED))


if __name__ == "__main__":
    unittest.main()
