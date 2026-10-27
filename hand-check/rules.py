"""Rule checker for hand occupancy.

A scene starts from an initial state. Each sentence has a list of events.
The checker applies the events in order and reports rule violations.

State: {character: {"left": obj | None, "right": obj | None}}
Event: {"character", "type": "grab" | "release" | "use",
        "hand": "left" | "right" | "both" | "any",
        "object": str | None, "free_hands_needed": int (use only)}
"""

from copy import deepcopy

HANDS = ("left", "right")


def empty_hands():
    return {"left": None, "right": None}


def free_hands(hands):
    return [h for h in HANDS if hands[h] is None]


def _same_object(a, b):
    if not a or not b:
        return False
    a, b = a.replace(" ", ""), b.replace(" ", "")
    return a in b or b in a


def apply_event(state, event):
    """Apply one event to state in place. Return a violation reason or None.

    When an event breaks a rule, the state does not change.
    """
    who = event.get("character")
    if not who:
        return "event has no character"
    hands = state.setdefault(who, empty_hands())
    kind = event.get("type")
    hand = event.get("hand") or "any"
    obj = event.get("object")

    if kind == "grab":
        if hand in HANDS:
            if hands[hand] is not None:
                return f"{who}: {hand} hand already holds '{hands[hand]}', cannot grab '{obj}'"
            hands[hand] = obj
        elif hand == "both":
            if free_hands(hands) != list(HANDS):
                return f"{who}: needs both hands free to grab '{obj}', holds {hands}"
            hands["left"] = hands["right"] = obj
        else:
            free = free_hands(hands)
            if not free:
                return f"{who}: no free hand to grab '{obj}', holds {hands}"
            # Prefer the right hand when both are free.
            hands["right" if "right" in free else free[0]] = obj
        return None

    if kind == "release":
        if hand in HANDS:
            if hands[hand] is None:
                return f"{who}: {hand} hand is already empty"
            held = hands[hand]
            # A two-handed object frees both hands.
            for h in HANDS:
                if hands[h] == held:
                    hands[h] = None
            return None
        if hand == "both":
            if all(hands[h] is None for h in HANDS):
                return f"{who}: both hands are already empty"
            hands["left"] = hands["right"] = None
            return None
        matches = [h for h in HANDS if _same_object(hands[h], obj)]
        if not matches:
            held = [h for h in HANDS if hands[h] is not None]
            if len(held) == 1 or (len(held) == 2 and hands["left"] == hands["right"]):
                matches = held
        if not matches:
            return f"{who}: does not hold '{obj}', holds {hands}"
        for h in matches:
            hands[h] = None
        return None

    if kind == "use":
        need = int(event.get("free_hands_needed") or 0)
        if need <= 0:
            return None
        if hand in HANDS:
            if hands[hand] is not None:
                return f"{who}: {hand} hand holds '{hands[hand]}', cannot do '{event.get('action', '')}'"
            return None
        free = free_hands(hands)
        if hand == "both":
            need = 2
        if len(free) < need:
            return f"{who}: needs {need} free hand(s) for '{event.get('action', '')}', holds {hands}"
        return None

    return f"unknown event type '{kind}'"


def run_scene(initial_state, sentence_events):
    """Simulate a scene.

    Return (states_after_each_sentence, violations).
    violations: list of {"sentence": i, "reason": str}.
    """
    state = {who: {**empty_hands(), **hands} for who, hands in deepcopy(initial_state).items()}
    states, violations = [], []
    for i, events in enumerate(sentence_events):
        for event in events or []:
            reason = apply_event(state, event)
            if reason:
                violations.append({"sentence": i, "reason": reason})
        states.append(deepcopy(state))
    return states, violations


def free_hand_counts(states):
    """Reduce states to free-hand counts per character per sentence.

    This comparison ignores object names and left/right choice,
    so naming differences in extraction do not count as errors.
    """
    return [{who: len(free_hands(h)) for who, h in s.items()} for s in states]
