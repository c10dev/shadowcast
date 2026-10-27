"""Rule tests: each rule breaks on a bad event list and passes on a good one.

Run: python3 -m unittest discover -s tests
"""

import unittest

from shadowcast import rules


def rules_of(initial, sentences, items=None, aliases=None):
    """Violation rules as (sentence, rule) pairs."""
    _, violations = rules.run_scene(initial, sentences, items, aliases)
    return [(v["sentence"], v["rule"]) for v in violations]


def ev(event_type, who, **fields):
    return {"type": event_type, "character": who, **fields}


EMPTY = {"hands": {"left": None, "right": None}}


class HandRules(unittest.TestCase):
    def test_grab_with_full_hands(self):
        start = {"지호": {"hands": {"left": "국그릇", "right": "숟가락"}}}
        self.assertEqual(rules_of(start, [[ev("grab", "지호", object="컵")]]), [(0, "hand_full")])
        self.assertEqual(rules_of(start, [[ev("release", "지호", hand="right", object="숟가락"),
                                           ev("grab", "지호", object="컵")]]), [])

    def test_use_needs_free_hands(self):
        start = {"지호": {"hands": {"left": "컵", "right": None}}}
        self.assertEqual(rules_of(start, [[ev("use", "지호", hand="both", free_hands_needed=2, action="문을 엶")]]),
                         [(0, "hand_full")])
        self.assertEqual(rules_of(start, [[ev("use", "지호", free_hands_needed=1, action="문을 엶")]]), [])

    def test_two_arm_hold_takes_both_hands(self):
        start = {"지후": {"hands": {"left": "상자", "right": "상자"}}}
        self.assertEqual(rules_of(start, [[ev("grab", "지후", hand="right", object="볼펜")]]), [(0, "hand_full")])
        self.assertEqual(rules_of(start, [[ev("release", "지후", hand="both", object="상자"),
                                           ev("grab", "지후", hand="right", object="볼펜")]]), [])

    def test_release_what_is_not_held(self):
        start = {"지호": {"hands": {"left": "컵", "right": "열쇠"}}}
        self.assertEqual(rules_of(start, [[ev("release", "지호", object="우산")]]), [(0, "not_held")])

    def test_use_with_a_tool_that_is_put_down(self):
        start = {"지후": EMPTY}
        sentences = [[ev("grab", "지후", hand="right", object="볼펜")],
                     [ev("release", "지후", hand="right", object="볼펜", to="책상")],
                     [ev("use", "지후", hand="right", free_hands_needed=0, action="송장을 씀", **{"with": "볼펜"})]]
        self.assertEqual(rules_of(start, sentences), [(2, "tool_missing")])
        self.assertEqual(rules_of(start, sentences[:1] + sentences[2:]), [])

    def test_give_to_full_hands(self):
        start = {"채원": {"hands": {"left": None, "right": "바통"}}, "하늘": {"hands": {"left": "물병", "right": "모자"}}}
        self.assertEqual(rules_of(start, [[ev("give", "채원", to="하늘", object="바통")]]), [(0, "hand_full")])

    def test_a_failed_event_does_not_change_the_state(self):
        start = {"지호": {"hands": {"left": "컵", "right": "열쇠"}}}
        # The grab fails, so the release after it still finds the cup.
        self.assertEqual(rules_of(start, [[ev("grab", "지호", object="책")],
                                          [ev("release", "지호", object="컵")]]), [(0, "hand_full")])


class V1Gaps(unittest.TestCase):
    """False alarms of condition C in hand-check v1. The events are the model extractions."""

    def test_handoff_frees_the_giver(self):
        # s27-clean: the text says only that 하늘 took the baton.
        start = {"채원": {"hands": {"left": None, "right": "바통"}}, "하늘": {"hands": {"left": "물병", "right": None}}}
        sentences = [[], [],
                     [ev("release", "하늘", hand="left", object="물병"), ev("grab", "하늘", hand="left", object="바통")],
                     [ev("use", "채원", hand="both", free_hands_needed=2, action="두 손으로 무릎을 짚음")]]
        self.assertEqual(rules_of(start, sentences), [])

    def test_person_outside_the_initial_state_is_unknown(self):
        # s39-clean: the clerk is not in the initial state and holds out a form.
        start = {"지후": {"hands": {"left": "소포 상자", "right": "소포 상자"}}}
        sentences = [[], [ev("release", "창구 직원", object="송장")],
                     [ev("release", "지후", hand="both", object="소포 상자"), ev("grab", "지후", hand="right", object="볼펜")]]
        self.assertEqual(rules_of(start, sentences), [])

    def test_alias_matches_another_name(self):
        # s28-clean: an egg is grabbed, its shell is thrown away.
        start = {"다은": EMPTY}
        sentences = [[ev("grab", "다은", hand="left", object="프라이팬")],
                     [ev("grab", "다은", hand="right", object="달걀")],
                     [ev("release", "다은", object="껍데기"), ev("grab", "다은", object="소금 통")]]
        # Without the alias the shell is not found, so the egg stays and the salt has no hand.
        self.assertEqual(rules_of(start, sentences), [(2, "not_held"), (2, "hand_full")])
        self.assertEqual(rules_of(start, sentences, aliases={"껍데기": "달걀"}), [])


class FacingRules(unittest.TestCase):
    START = {"민준": {"facing": {"유나": "front"}}, "유나": {"facing": {"민준": "front"}}}

    def test_text_says_another_facing(self):
        self.assertEqual(rules_of(self.START, [[ev("state", "유나", facing={"민준": "back"})]]),
                         [(0, "facing_mismatch")])

    def test_turn_changes_the_facing(self):
        self.assertEqual(rules_of(self.START, [[ev("turn", "유나", away_from="민준")],
                                               [ev("state", "유나", facing={"민준": "back"})]]), [])

    def test_unknown_facing_takes_the_text(self):
        self.assertEqual(rules_of({}, [[ev("state", "유나", facing={"민준": "back"})],
                                       [ev("state", "유나", facing={"민준": "front"})]]), [(1, "facing_mismatch")])

    def test_face_of_a_back_is_hidden(self):
        start = {"서윤": {"facing": {"도현": "back"}}}
        self.assertEqual(rules_of(start, [[ev("see", "도현", target="서윤", part="face")]]), [(0, "hidden_side")])
        self.assertEqual(rules_of(start, [[ev("turn", "서윤", toward="도현")],
                                          [ev("see", "도현", target="서윤", part="face")]]), [])


class WornRules(unittest.TestCase):
    START = {"민준": {"hands": {"left": None, "right": None}, "worn": {"torso": ["셔츠", "백팩"]},
                     "front": [], "back": ["백팩"]}}

    def test_inner_layer_under_an_outer_layer(self):
        self.assertEqual(rules_of(self.START, [[ev("take_off", "민준", item="셔츠")]]), [(0, "layer_order")])
        self.assertEqual(rules_of(self.START, [[ev("take_off", "민준", item="백팩")],
                                               [ev("take_off", "민준", item="셔츠")]]), [])

    def test_take_off_what_is_not_worn(self):
        self.assertEqual(rules_of(self.START, [[ev("take_off", "민준", item="재킷", zone="torso")]]),
                         [(0, "not_worn")])
        # A zone that the scene never named is unknown, so a scarf can come off.
        self.assertEqual(rules_of(self.START, [[ev("take_off", "민준", item="목도리", zone="neck")]]), [])
        self.assertEqual(rules_of(self.START, [[ev("take_off", "민준", item="재킷")]]), [])

    def test_wear_again_in_the_same_zone_does_nothing(self):
        start = {"소희": {"hands": {"left": None, "right": None}, "worn": {"left_hand": ["반지", "장갑"]}}}
        self.assertEqual(rules_of(start, [[ev("take_off", "소희", item="반지")],
                                          [ev("wear", "소희", item="반지", zone="left_hand")]]), [(0, "layer_order")])

    def test_take_off_needs_hands(self):
        start = {"민준": {"hands": {"left": "손잡이", "right": "@유나"}, "worn": {"torso": ["재킷"]}}}
        self.assertEqual(rules_of(start, [[ev("take_off", "민준", item="재킷", free_hands_needed=1)]]),
                         [(0, "hand_full")])

    def test_taken_off_item_stays_in_a_free_hand(self):
        start = {"준호": {"hands": {"left": None, "right": None}, "worn": {"torso": ["바람막이"]}}}
        take_off = ev("take_off", "준호", item="바람막이", free_hands_needed=1)
        states, _ = rules.run_scene(start, [[take_off]])
        self.assertEqual(states[0]["bodies"]["준호"]["hands"], {"left": None, "right": "바람막이"})
        self.assertEqual(rules_of(start, [[take_off],
                                          [ev("release", "준호", object="바람막이", to="배낭 옆 주머니")]]), [])
        # A grab of the item that is already in the hand does not take a second hand.
        self.assertEqual(rules_of(start, [[take_off],
                                          [ev("grab", "준호", object="바람막이"),
                                           ev("grab", "준호", object="컵")]]), [])
        self.assertEqual(rules_of(start, [[take_off, ev("grab", "준호", object="컵"),
                                           ev("grab", "준호", object="볼펜")]]), [(0, "hand_full")])

    def test_taken_off_item_with_no_free_hand_is_unknown(self):
        start = {"준호": {"hands": {"left": "손잡이", "right": "컵"}, "worn": {"torso": ["바람막이"]}}}
        states, violations = rules.run_scene(start, [[ev("take_off", "준호", item="바람막이")]])
        self.assertEqual(violations, [])
        self.assertEqual(states[0]["bodies"]["준호"]["hands"], {"left": "손잡이", "right": "컵"})
        self.assertNotIn("바람막이", states[0]["items"])

    def test_taken_off_item_goes_to_its_place(self):
        start = {"준호": {"hands": {"left": None, "right": None}, "worn": {"torso": ["바람막이"]}}}
        take_off = ev("take_off", "준호", item="바람막이", to="의자")
        states, _ = rules.run_scene(start, [[take_off]])
        self.assertEqual(states[0]["bodies"]["준호"]["hands"], {"left": None, "right": None})
        self.assertEqual(states[0]["items"]["바람막이"], "의자")
        self.assertEqual(rules_of(start, [[take_off], [ev("grab", "준호", object="바람막이", **{"from": "의자"})]]), [])
        self.assertEqual(rules_of(start, [[take_off], [ev("grab", "준호", object="바람막이", **{"from": "가방"})]]),
                         [(1, "item_location")])

    def test_move_a_worn_backpack_to_the_front(self):
        sentences = [[ev("wear", "민준", item="백팩", zone="torso", side="front")],
                     [ev("state", "민준", front="백팩")]]
        self.assertEqual(rules_of(self.START, sentences), [])


class SpaceRules(unittest.TestCase):
    START = {"민준": {"worn": {"torso": ["셔츠", "백팩"]}, "front": ["@유나"], "back": ["백팩"]},
             "유나": {"front": ["@민준"]}}

    def test_front_space_is_full(self):
        wear_front = ev("wear", "민준", item="백팩", zone="torso", side="front")
        self.assertEqual(rules_of(self.START, [[wear_front]]), [(0, "space_full")])
        self.assertEqual(rules_of(self.START, [[ev("move", "유나", away_from="민준")], [wear_front]]), [])

    def test_hug_needs_an_empty_front(self):
        start = {"민준": {"hands": {"left": None, "right": None}, "front": ["백팩"]}}
        self.assertEqual(rules_of(start, [[ev("touch", "민준", target="유나", kind="hug")]]), [(0, "space_full")])


    def test_put_down_box_leaves_the_front(self):
        start = {"수빈": {"hands": {"left": "상자", "right": "상자"}, "front": ["상자"]}}
        press = ev("touch", "수빈", target="남자", kind="press")
        self.assertEqual(rules_of(start, [[press]]), [(0, "space_full")])
        self.assertEqual(rules_of(start, [[ev("release", "수빈", hand="both", object="상자", to="바닥")], [press]]), [])


class ContactRules(unittest.TestCase):
    def test_hug_needs_both_hands(self):
        start = {"민준": {"hands": {"left": "찻잔", "right": None}}}
        self.assertEqual(rules_of(start, [[ev("touch", "민준", target="유나", kind="hug")]]), [(0, "hand_full")])

    def test_hold_hands_uses_one_hand_each(self):
        start = {"민준": {"hands": {"left": None, "right": None}}, "유나": {"hands": {"left": None, "right": None}}}
        sentences = [[ev("touch", "민준", target="유나", kind="hold_hands", hand="left", target_hand="right")],
                     [ev("grab", "민준", hand="right", object="우산"), ev("grab", "민준", object="가방")]]
        self.assertEqual(rules_of(start, sentences), [(1, "hand_full")])

    def test_hug_sets_facing(self):
        start = {"민준": {"hands": {"left": None, "right": None}}}
        self.assertEqual(rules_of(start, [[ev("touch", "민준", target="유나", kind="hug")],
                                          [ev("state", "유나", facing={"민준": "back"})]]), [(1, "facing_mismatch")])

    def test_back_hug_sets_facing(self):
        start = {"민준": {"hands": {"left": None, "right": None}}}
        self.assertEqual(rules_of(start, [[ev("touch", "민준", target="유나", kind="back_hug")],
                                          [ev("see", "민준", target="유나", part="face")]]), [(1, "hidden_side")])

    def test_move_away_while_holding(self):
        start = {"민준": {"hands": {"left": None, "right": None}}}
        grip = ev("touch", "민준", target="유나", kind="grip", hand="right")
        self.assertEqual(rules_of(start, [[grip], [ev("move", "유나", away_from="민준")]]), [(1, "contact_kept")])
        self.assertEqual(rules_of(start, [[grip], [ev("untouch", "민준", target="유나")],
                                          [ev("move", "유나", away_from="민준")]]), [])

    def test_let_go_with_the_hand_only(self):
        start = {"정우": {"hands": {"left": "손잡이", "right": None}, "front": [], "worn": {"torso": ["백팩"]}}}
        sentences = [[ev("touch", "정우", target="은숙", kind="lean"),
                      ev("touch", "정우", target="은숙", kind="grip", hand="right")],
                     [ev("release", "정우", hand="right", object="@은숙")],
                     [ev("use", "정우", hand="right", free_hands_needed=1, action="끈을 잡음"),
                      ev("wear", "정우", item="백팩", zone="torso", side="front")]]
        # The hand is free again, but 은숙 still leans on the front.
        self.assertEqual(rules_of(start, sentences), [(2, "space_full")])
        self.assertEqual(rules_of(start, sentences[:1] + [[ev("release", "정우", object="@민수")]]), [(1, "not_held")])

    def test_turn_away_while_hugged(self):
        start = {"민준": {"hands": {"left": None, "right": None}}}
        self.assertEqual(rules_of(start, [[ev("touch", "민준", target="유나", kind="hug")],
                                          [ev("turn", "민준", away_from="유나")]]), [(1, "contact_kept")])

    def test_turn_ends_contact_without_hands(self):
        start = {"민준": {"front": ["@유나"], "facing": {"유나": "front"}},
                 "유나": {"front": ["@민준"], "facing": {"민준": "front"}}}
        self.assertEqual(rules_of(start, [[ev("turn", "유나", away_from="민준")],
                                          [ev("state", "유나", facing={"민준": "back"})]]), [])


class ItemRules(unittest.TestCase):
    def test_take_from_the_wrong_place(self):
        start = {"지호": EMPTY}
        items = {"가방": "의자 위"}
        self.assertEqual(rules_of(start, [[ev("grab", "지호", object="가방", **{"from": "바닥"})]], items),
                         [(0, "item_location")])
        self.assertEqual(rules_of(start, [[ev("grab", "지호", object="가방", **{"from": "의자"})]], items), [])

    def test_put_then_take_from_the_new_place(self):
        start = {"지호": EMPTY}
        sentences = [[ev("grab", "지호", object="열쇠")],
                     [ev("release", "지호", object="열쇠", to="코트 주머니")],
                     [ev("grab", "지호", object="열쇠", **{"from": "가방"})]]
        self.assertEqual(rules_of(start, sentences), [(2, "item_location")])

    def test_place_names_match_on_a_shared_word(self):
        self.assertTrue(rules.same_place("민준 바지 앞주머니", "바지 주머니"))
        self.assertTrue(rules.same_place("가방 안주머니", "가방"))
        self.assertFalse(rules.same_place("코트 주머니", "바지 주머니"))  # "주머니" alone does not match
        self.assertFalse(rules.same_place("신발장 위 접시", "가방 안주머니"))

    def test_unknown_place_does_not_break(self):
        self.assertEqual(rules_of({"지호": EMPTY}, [[ev("grab", "지호", object="열쇠", **{"from": "가방"})]]), [])

    def test_text_says_a_hand_holds_what_it_does_not(self):
        start = {"지호": {"hands": {"left": None, "right": "컵"}}}
        self.assertEqual(rules_of(start, [[ev("release", "지호", object="컵", to="탁자")],
                                          [ev("state", "지호", holds="컵")]]), [(1, "state_mismatch")])

    def test_unknown_hand_takes_the_text(self):
        self.assertEqual(rules_of({}, [[ev("state", "지호", holds="컵")],
                                       [ev("grab", "지호", object="책")], [ev("grab", "지호", object="펜")]]),
                         [(2, "hand_full")])


class FreeHands(unittest.TestCase):
    def test_counts(self):
        states, _ = rules.run_scene({"지호": {"hands": {"left": "컵", "right": None}}},
                                    [[ev("grab", "지호", object="책")]])
        self.assertEqual(rules.free_hand_counts(states), [{"지호": 0}])


if __name__ == "__main__":
    unittest.main()
