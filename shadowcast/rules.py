"""Rule checker for scene state (format v2).

A scene starts from an initial state. Each sentence has a list of events.
The checker applies the events in order and reports rule violations.
It does not read text. A model or a person writes the events.

State
  bodies: {name: body}
    hands   {"left": v, "right": v}. v is None (empty), an object name,
            "@name" (the hand holds that person), or "?" (unknown).
    facing  {other: "front" | "back" | "side"}. A missing key is unknown.
            "front": the front of this body points at the other person.
            "back": the back of this body points at the other person.
    worn    {zone: [item, ...]}, inner layer first. A missing zone is unknown.
    front   list of things in the space in front of the body ("@name" or an item).
    back    the same for the space behind the body.
            None means unknown. [] means empty.
  items: {object: place} for objects that are not in a hand or worn.
         A missing object has an unknown place.

Events. All events have "type" and "character".
  grab      hand, object, from?           take an object into a hand
  release   hand, object, to?             let an object go
  give      to, object, hand?, to_hand?   pass an object to another person
  use       hand, free_hands_needed, action?, with?   act with the hands
  turn      toward | away_from | side_to  change facing to one person
  wear      item, zone, side?             put on an item (side: "front" | "back")
  take_off  item, zone?, free_hands_needed?, to?   take off a worn item
  touch     target, kind, hand?           start contact (kinds: TOUCH_KINDS)
  untouch   target                        end all contact with the target
  move      away_from? | to?              move the body
  state     facing?, holds?, wears?, front?   the text describes the state
  see       target, part?                 the character sees the target's face or front
  hand: "left" | "right" | "both" | "any". A missing hand is "any".

Violation rules (the "rule" field of a violation)
  hand_full        an action needs a free hand and none is free
  not_held         release or give an object that the hands do not hold
  tool_missing     use an object ("with") that the hands do not hold
  facing_mismatch  the text describes a facing that the state does not have
  hidden_side      see the face or front of a person who shows the back
  layer_order      take off an inner layer under an outer layer
  not_worn         take off an item that is not on a known zone
  space_full       put an item or a person into a front or back space that is full
  contact_kept     move away from or turn from a person who is still held
  item_location    take an object from a place where it is not
  state_mismatch   the text describes a held or worn object that the state does not have

When an event breaks a rule, the state does not change.
"""

from copy import deepcopy

HANDS = ("left", "right")
UNKNOWN = "?"
SIDES = ("front", "back")
FACINGS = ("front", "back", "side")

# kind: (hands of the actor, hands of the target, actor side, target side,
#        facing of the actor to the target, facing of the target to the actor)
TOUCH_KINDS = {
    "grip": (1, 0, None, None, None, None),          # hold the target's hand, wrist, or shoulder
    "hold_hands": (1, 1, None, None, None, None),    # both hold hands
    "hug": (2, 0, "front", "front", "front", "front"),
    "back_hug": (2, 0, "front", "back", "front", "back"),
    "carry_back": (2, 0, "back", "front", "back", "front"),  # the target rides on the actor's back
    "lean": (0, 0, "front", "back", "front", "back"),        # the target leans its back on the actor
    "press": (0, 0, "front", "front", "front", "front"),     # fronts touch without arms
}


# ---------- names ----------

def _key(name):
    return (name or "").replace(" ", "")


def _same(a, b):
    """Object or place names match when one contains the other, spaces ignored."""
    a, b = _key(a), _key(b)
    return bool(a) and bool(b) and (a in b or b in a)


def person(name):
    return "@" + name


def is_person(value):
    return isinstance(value, str) and value.startswith("@")


class Scene:
    """The state of one scene and the rules that change it."""

    def __init__(self, initial_state=None, items=None, aliases=None):
        self.aliases = {_key(k): v for k, v in (aliases or {}).items()}
        self.bodies = {}
        for who, body in deepcopy(initial_state or {}).items():
            self.bodies[who] = self._new_body(body)
        self.items = {self.name(k): v for k, v in (items or {}).items()}

    # ----- state helpers -----

    @staticmethod
    def _new_body(body=None):
        body = body or {}
        hands = body.get("hands") or {}
        return {
            "hands": {h: hands.get(h, UNKNOWN) for h in HANDS},
            "facing": dict(body.get("facing") or {}),
            "worn": {z: list(v) for z, v in (body.get("worn") or {}).items()},
            "front": list(body["front"]) if body.get("front") is not None else None,
            "back": list(body["back"]) if body.get("back") is not None else None,
        }

    def body(self, who):
        if who not in self.bodies:
            self.bodies[who] = self._new_body()  # a person outside the initial state: all unknown
        return self.bodies[who]

    def name(self, obj):
        """Map an alias to its object name."""
        return self.aliases.get(_key(obj), obj) if obj else obj

    def snapshot(self):
        return {"bodies": deepcopy(self.bodies), "items": dict(self.items)}

    @staticmethod
    def free(hands):
        """Free hands. An unknown hand counts as free."""
        return [h for h in HANDS if hands[h] is None or hands[h] == UNKNOWN]

    def holders(self, obj):
        """(person, hand) pairs that hold the object."""
        return [(who, h) for who, b in self.bodies.items() for h in HANDS
                if b["hands"][h] not in (None, UNKNOWN) and not is_person(b["hands"][h])
                and _same(b["hands"][h], obj)]

    def worn_by(self, who, item):
        """The zone where the person wears the item, or None."""
        for zone, layers in self.body(who)["worn"].items():
            if any(_same(x, item) for x in layers):
                return zone
        return None

    def _take_hands(self, who, hand, need, value):
        """Fill `need` hands with value. Return an error text or None."""
        hands = self.body(who)["hands"]
        if need <= 0:
            return None
        if hand in HANDS and need == 1:
            if hands[hand] not in (None, UNKNOWN):
                return f"{who}: {hand} hand holds '{hands[hand]}'"
            hands[hand] = value
            return None
        free = self.free(hands)
        if hand == "both":
            need = 2
        if len(free) < need:
            return f"{who}: needs {need} free hand(s), holds {hands}"
        # Prefer the right hand when both are free.
        order = sorted(free, key=lambda h: h != "right")
        for h in order[:need]:
            hands[h] = value
        return None

    def _side_take(self, who, side, value):
        """Put value into a front or back space. Return an error text or None."""
        b = self.body(who)
        space = b[side]
        if space is None:
            b[side] = space = []
        others = [x for x in space if x != value]
        if others:
            return f"{who}: {side} space holds {others}"
        if value not in space:
            space.append(value)
        return None

    def _contacts(self, a, b):
        """Hands-based contact between a and b (either way)."""
        ha = self.body(a)["hands"].values()
        hb = self.body(b)["hands"].values()
        return person(b) in ha or person(a) in hb

    def _clear_pair(self, a, b):
        """Remove all contact between a and b."""
        for x, y in ((a, b), (b, a)):
            body = self.body(x)
            for h in HANDS:
                if body["hands"][h] == person(y):
                    body["hands"][h] = None
            for side in SIDES:
                if body[side] is not None and person(y) in body[side]:
                    body[side].remove(person(y))

    # ----- events -----

    def apply(self, event):
        """Apply one event. Return (rule, reason) for a violation, or None."""
        kind = event.get("type")
        handler = getattr(self, f"_ev_{kind}", None)
        if handler is None:
            return "bad_event", f"unknown event type '{kind}'"
        who = event.get("character")
        if not who:
            return "bad_event", f"{kind} event has no character"
        saved = self.snapshot()
        result = handler(who, event)
        if result:
            self.bodies, self.items = saved["bodies"], saved["items"]
        return result

    def _ev_grab(self, who, e):
        obj = self.name(e.get("object"))
        hand = e.get("hand") or "any"
        if e.get("from") and obj in self.items and not _same(self.items[obj], e["from"]):
            return "item_location", f"'{obj}' is at '{self.items[obj]}', not '{e['from']}'"
        # A grab of an object in another person's hand is a handoff: the other hand lets go.
        for giver, h in self.holders(obj):
            if giver != who:
                self.body(giver)["hands"][h] = None
        err = self._take_hands(who, hand, 2 if hand == "both" else 1, obj)
        if err:
            return "hand_full", f"cannot grab '{obj}': {err}"
        self.items.pop(obj, None)
        return None

    def _clear_sides(self, who, obj):
        body = self.body(who)
        for side in SIDES:
            if body[side] is not None:
                body[side] = [x for x in body[side] if is_person(x) or not _same(x, obj)]

    def _release(self, who, hand, obj):
        """Free the hand that holds obj. Return an error text or None."""
        hands = self.body(who)["hands"]
        if hand in HANDS:
            if hands[hand] is None:
                return f"{who}: {hand} hand is already empty"
            held = hands[hand]
            for h in HANDS:  # a two-handed object frees both hands
                if hands[h] == held:
                    hands[h] = None
            return None
        if hand == "both":
            if all(hands[h] is None for h in HANDS):
                return f"{who}: both hands are already empty"
            hands["left"] = hands["right"] = None
            return None
        matches = [h for h in HANDS if hands[h] not in (None, UNKNOWN) and not is_person(hands[h])
                   and _same(hands[h], obj)]
        if not matches:
            held = [h for h in HANDS if hands[h] not in (None, UNKNOWN) and not is_person(hands[h])]
            if len(held) == 1 or (len(held) == 2 and hands["left"] == hands["right"]):
                matches = held
            elif UNKNOWN in hands.values():
                matches = [h for h in HANDS if hands[h] == UNKNOWN][:1]  # it was in the unknown hand
        if not matches:
            return f"{who}: does not hold '{obj}', holds {hands}"
        for h in matches:
            hands[h] = None
        return None

    def _ev_release(self, who, e):
        obj = self.name(e.get("object"))
        err = self._release(who, e.get("hand") or "any", obj)
        if err:
            return "not_held", err
        if obj:
            self._clear_sides(who, obj)  # a carried box leaves the front space
            if e.get("to"):
                self.items[obj] = e["to"]
            else:
                self.items.pop(obj, None)
        return None

    def _ev_give(self, who, e):
        obj = self.name(e.get("object"))
        to = e.get("to")
        if not to:
            return "bad_event", "give event has no 'to'"
        err = self._release(who, e.get("hand") or "any", obj)
        if err:
            return "not_held", err
        self._clear_sides(who, obj)
        err = self._take_hands(to, e.get("to_hand") or "any", 1, obj)
        if err:
            return "hand_full", f"cannot receive '{obj}': {err}"
        return None

    def _ev_use(self, who, e):
        hands = self.body(who)["hands"]
        tool = self.name(e.get("with"))
        if tool and not any(hands[h] not in (None, UNKNOWN) and _same(hands[h], tool) for h in HANDS) \
                and UNKNOWN not in hands.values():
            return "tool_missing", f"{who} does not hold '{tool}' for '{e.get('action', '')}', holds {hands}"
        need = int(e.get("free_hands_needed") or 0)
        hand = e.get("hand") or "any"
        if need <= 0:
            return None
        if hand in HANDS and need == 1:
            if hands[hand] not in (None, UNKNOWN):
                return "hand_full", f"{who}: {hand} hand holds '{hands[hand]}', cannot do '{e.get('action', '')}'"
            return None
        if hand == "both":
            need = 2
        if len(self.free(hands)) < need:
            return "hand_full", f"{who}: needs {need} free hand(s) for '{e.get('action', '')}', holds {hands}"
        return None

    def _ev_turn(self, who, e):
        for field, facing in (("toward", "front"), ("away_from", "back"), ("side_to", "side")):
            other = e.get(field)
            if other:
                break
        else:
            return "bad_event", "turn event has no toward, away_from, or side_to"
        body = self.body(who)
        held = [h for h in HANDS if body["hands"][h] == person(other)]
        # Front or back contact with the other person ends when the body turns.
        for side in SIDES:
            if body[side] is not None and person(other) in body[side] and facing != side:
                if held:
                    return "contact_kept", f"{who} turns from {other} while holding {other}"
                self._clear_pair(who, other)
        body["facing"][other] = facing
        return None

    def _ev_wear(self, who, e):
        item = self.name(e.get("item"))
        zone = e.get("zone") or "torso"
        side = e.get("side")
        body = self.body(who)
        old = self.worn_by(who, item)
        if old == zone and (side not in SIDES or item in (body[side] or [])):
            return None  # already worn there
        if old is not None:  # moving a worn item (a backpack from the back to the front)
            err = self._take_off(who, item, old)
            if err:
                return err
        if side in SIDES:
            err = self._side_take(who, side, item)
            if err:
                return "space_full", f"cannot wear '{item}' on the {side}: {err}"
        for h in HANDS:  # wearing an item from the hand frees the hand
            if body["hands"][h] not in (None, UNKNOWN) and _same(body["hands"][h], item):
                body["hands"][h] = None
        body["worn"].setdefault(zone, []).append(item)
        self.items.pop(item, None)
        return None

    def _take_off(self, who, item, zone):
        body = self.body(who)
        layers = body["worn"][zone]
        i = next(i for i, x in enumerate(layers) if _same(x, item))
        outer = layers[i + 1:]
        if outer:
            return "layer_order", f"{who}: '{layers[i]}' is under {outer}"
        layers.pop(i)
        for side in SIDES:
            if body[side] is not None:
                body[side] = [x for x in body[side] if not _same(x, item)]
        return None

    def _ev_take_off(self, who, e):
        item = self.name(e.get("item"))
        zone = self.worn_by(who, item)
        if zone is None:
            # Only a known zone can say "not worn". Clothes the text never named are unknown.
            asked = e.get("zone")
            if asked and asked in self.body(who)["worn"]:
                return "not_worn", f"{who} does not wear '{item}' on {asked}, wears {self.body(who)['worn'][asked]}"
            return None
        need = int(e.get("free_hands_needed") or 0)
        if need and len(self.free(self.body(who)["hands"])) < need:
            return "hand_full", f"{who}: needs {need} free hand(s) to take off '{item}', holds {self.body(who)['hands']}"
        err = self._take_off(who, item, zone)
        if err:
            return err
        if e.get("to"):
            self.items[item] = e["to"]
        return None

    def _ev_touch(self, who, e):
        target = e.get("target")
        kind = e.get("kind")
        if not target or kind not in TOUCH_KINDS:
            return "bad_event", f"touch event needs a target and a kind in {sorted(TOUCH_KINDS)}"
        a_hands, t_hands, a_side, t_side, a_face, t_face = TOUCH_KINDS[kind]
        err = self._take_hands(who, e.get("hand") or "any", a_hands, person(target))
        if err:
            return "hand_full", f"cannot {kind} {target}: {err}"
        err = self._take_hands(target, e.get("target_hand") or "any", t_hands, person(who))
        if err:
            return "hand_full", f"{target} cannot {kind} with {who}: {err}"
        for x, side, value in ((who, a_side, target), (target, t_side, who)):
            if side:
                err = self._side_take(x, side, person(value))
                if err:
                    return "space_full", f"cannot {kind}: {err}"
        if a_face:
            self.body(who)["facing"][target] = a_face
        if t_face:
            self.body(target)["facing"][who] = t_face
        return None

    def _ev_untouch(self, who, e):
        target = e.get("target")
        if not target:
            return "bad_event", "untouch event has no target"
        self._clear_pair(who, target)
        return None

    def _ev_move(self, who, e):
        other = e.get("away_from")
        if other:
            if self._contacts(who, other):
                return "contact_kept", f"{who} moves away from {other} while one holds the other"
            self._clear_pair(who, other)  # body contact without hands ends
            self.body(who)["facing"].pop(other, None)
            self.body(other)["facing"].pop(who, None)
            return None
        # A move to a place makes the facing unknown. Contact goes with the body.
        self.body(who)["facing"] = {}
        for b in self.bodies.values():
            b["facing"].pop(who, None)
        return None

    def _ev_state(self, who, e):
        body = self.body(who)
        for other, facing in (e.get("facing") or {}).items():
            known = body["facing"].get(other)
            if known and known != facing:
                return "facing_mismatch", f"{who} faces {other} with the {known}, text says {facing}"
            body["facing"][other] = facing
        obj = self.name(e.get("holds"))
        if obj:
            hands = body["hands"]
            if not any(hands[h] not in (None, UNKNOWN) and _same(hands[h], obj) for h in HANDS):
                if UNKNOWN not in hands.values():
                    return "state_mismatch", f"text says {who} holds '{obj}', hands hold {hands}"
                h = next(h for h in HANDS if hands[h] == UNKNOWN)
                hands[h] = obj
        item = self.name(e.get("wears"))
        if item and self.worn_by(who, item) is None and body["worn"]:
            return "state_mismatch", f"text says {who} wears '{item}', worn {body['worn']}"
        for side in SIDES:
            value = e.get(side)
            if value:
                space = body[side]
                if space is not None and value not in space and not any(_same(x, value) for x in space):
                    return "state_mismatch", f"text says {value} is in {who}'s {side} space, it holds {space}"
                if space is None:
                    body[side] = [value]
        return None

    def _ev_see(self, who, e):
        target = e.get("target")
        if not target:
            return "bad_event", "see event has no target"
        if self.body(target)["facing"].get(who) == "back":
            return "hidden_side", f"{who} sees the {e.get('part') or 'face'} of {target}, who shows the back"
        return None


def run_scene(initial_state, sentence_events, items=None, aliases=None):
    """Simulate a scene.

    Return (states_after_each_sentence, violations).
    violations: list of {"sentence": i, "rule": str, "reason": str}.
    """
    scene = Scene(initial_state, items, aliases)
    states, violations = [], []
    for i, events in enumerate(sentence_events):
        for event in events or []:
            result = scene.apply(event)
            if result:
                rule, reason = result
                violations.append({"sentence": i, "rule": rule, "reason": reason})
        states.append(scene.snapshot())
    return states, violations


def free_hand_counts(states):
    """Free-hand counts per person per sentence. An unknown hand counts as free.

    This comparison ignores object names and left or right,
    so naming differences in extraction do not count as errors.
    """
    return [{who: len(Scene.free(b["hands"])) for who, b in s["bodies"].items()} for s in states]
