"""Prompts and output schemas for format v2.

Conditions (the same as hand-check):
  A  paragraph only -> the model judges
  B  paragraph + initial state -> the model judges
  C  paragraph + initial state -> the model extracts events -> rules.py judges

The extraction schema is flat: every event has every field, and "" means "not used".
Strict structured output works best when all fields are required. normalize() turns
a flat event back into the event form that rules.py reads. flatten() is the reverse,
used for the gold backend and for tests.
"""

from . import rules

RULES = ["hand_full", "not_held", "tool_missing", "facing_mismatch", "hidden_side", "layer_order",
         "not_worn", "space_full", "contact_kept", "item_location", "state_mismatch"]
EVENT_TYPES = ["grab", "release", "give", "use", "turn", "wear", "take_off", "touch", "untouch", "move", "state", "see"]
ZONES = ["torso", "legs", "feet", "head", "neck", "hands"]
HAND_VALUES = ["left", "right", "both", "any", ""]

JUDGE_SYSTEM = """너는 소설 원고의 물리 연속성 검사기다. 한 장면 안에서 인물의 몸 상태가 앞뒤 문장과 맞는지만 검사한다.
- 손: 왼손과 오른손 둘뿐이다. 찬 손으로 다른 물건을 집거나 손이 필요한 행동을 할 수 없다. 두 팔로 안은 것은 두 손을 차지한다. 사람을 붙잡은 손도 찬 손이다. 든 물건 자체를 쓰는 행동, 어깨 · 발 · 몸으로 하는 행동은 빈손이 필요 없다.
- 향한 쪽: 돌아서는 행동 없이 향한 쪽이 바뀌지 않는다. 등을 보인 사람의 얼굴이나 앞모습은 보이지 않는다. 화면이나 거울에 비친 모습은 보인다.
- 착용 겹침: 바깥에 걸친 것을 벗지 않고 안쪽 것을 벗을 수 없다. 멘 가방의 끈은 그 아래 옷 위에 있다.
- 몸 앞뒤 공간: 몸 앞이나 뒤에 사람이나 물건이 붙어 있으면 그 자리에 다른 것을 둘 수 없다.
- 접촉: 붙잡거나 안거나 업은 채로는 멀어지거나 돌아설 수 없다. 먼저 놓아야 한다.
- 물건 자리: 물건은 한 번에 한 곳에만 있다. 내려놓거나 건넨 물건은 다시 집기 전까지 쓸 수 없고, 넣은 곳이 아닌 곳에서 꺼낼 수 없다.
- 문장이 묘사하는 상태(쥐고 있다, 입고 있다, 마주 보고 있다)는 앞 문장에서 정해진 상태와 맞아야 한다.
- 문장이 밝히지 않은 것은 가능한 쪽으로 읽는다. 장면에 처음 나오는 인물과 물건의 상태는 모른다.
이 밖의 오류(시간, 성격, 개연성, 문체)는 무시한다."""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "has_error": {"type": "boolean"},
        "sentences": {"type": "array", "items": {"type": "integer"}},
        "rule": {"type": "string", "enum": RULES + ["none"]},
        "reason": {"type": "string"},
    },
    "required": ["has_error", "sentences", "rule", "reason"],
    "additionalProperties": False,
}

EXTRACT_SYSTEM = f"""너는 소설 문장에서 인물의 몸 · 손 · 옷 · 물건 상태가 바뀌거나 드러나는 사건을 뽑는 추출기다.
판정은 하지 않는다. 문장에 쓰인 대로만 사건을 적는다. 쓰지 않는 칸은 빈 문자열로, free_hands_needed 는 0 으로 둔다.
모든 문장(index 0부터)에 항목을 하나씩 만든다. 사건이 없으면 events 를 빈 목록으로 둔다.

사건 종류(type)와 쓰는 칸:
- grab: 물건을 손에 쥔다. hand, object, from(꺼낸 곳)
- release: 물건을 놓거나 내려놓는다. hand, object, to(둔 곳). 사람을 붙잡은 손만 놓으면 object 에 "@이름"
- give: 물건을 다른 사람에게 건넨다. object, to(받는 사람), to_hand
- use: 손이 필요한 행동. hand, free_hands_needed(그 행동에 필요한 빈손 수 0~2), action, with(쥐고 써야 하는 도구)
  든 물건 자체를 쓰는 행동, 어깨 · 발 · 몸으로 하는 행동은 free_hands_needed 가 0 이다.
- turn: 몸을 돌린다. toward(그 사람 쪽으로) 또는 away_from(그 사람에게 등을 보이게) 또는 side_to
- wear: 입거나 멘다. item, zone({" · ".join(ZONES)}), side(몸 앞에 멨으면 front, 등에 멨으면 back)
- take_off: 벗거나 내린다. item, zone, free_hands_needed, to
- touch: 접촉을 시작한다. target, kind, hand, target_hand
  kind: grip(손목 · 어깨를 잡음), hold_hands(손을 맞잡음), hug(마주 안음), back_hug(뒤에서 안음),
  carry_back(업음, target 이 업힌 사람), lean(target 이 character 의 몸 앞에 등을 기댐), press(앞몸끼리 맞닿음)
- untouch: 두 사람 사이의 접촉을 끝낸다. target
- move: 몸을 옮긴다. away_from(그 사람에게서 멀어짐) 또는 to(간 곳)
- state: 문장이 지금 상태를 묘사한다. holds(쥔 물건), wears(입은 것), front · back(몸 앞 · 뒤에 붙은 것, 사람은 "@이름"),
  facing_who 와 facing(그 사람에게 front=앞, back=등, side=옆을 보임)
- see: 다른 사람의 얼굴이나 앞모습을 직접 본다. target, part(face 또는 front). 화면 · 거울로 본 것은 적지 않는다.
hand: 문장이 손을 밝히면 left · right · both, 밝히지 않으면 any.
물건 이름은 아래 목록에 있으면 그 이름을 그대로 쓴다. 사람은 이름으로 쓴다."""

FLAT_FIELDS = ["character", "hand", "object", "from", "to", "target", "kind", "target_hand", "to_hand",
               "item", "zone", "side", "toward", "away_from", "side_to", "action", "with", "part",
               "holds", "wears", "front", "back", "facing_who", "facing"]

ENUMS = {
    "type": EVENT_TYPES,
    "hand": HAND_VALUES,
    "target_hand": HAND_VALUES,
    "to_hand": HAND_VALUES,
    "kind": list(rules.TOUCH_KINDS) + [""],
    "zone": ZONES + [""],
    "side": ["front", "back", ""],
    "part": ["face", "front", ""],
    "facing": ["front", "back", "side", ""],
}

EVENT_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": EVENT_TYPES},
        **{f: ({"type": "string", "enum": ENUMS[f]} if f in ENUMS else {"type": "string"}) for f in FLAT_FIELDS},
        "free_hands_needed": {"type": "integer"},
    },
    "required": ["type", *FLAT_FIELDS, "free_hands_needed"],
    "additionalProperties": False,
}

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "events": {"type": "array", "items": EVENT_SCHEMA},
                },
                "required": ["index", "events"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["sentences"],
    "additionalProperties": False,
}


# ---------- state text ----------

FACING_WORDS = {"front": "앞(마주 봄)", "back": "등", "side": "옆"}


def _thing(value):
    return f"{value[1:]}(사람)" if rules.is_person(value) else value


def format_state(item):
    """The initial state as text lines. Fields that the data does not give are left out."""
    lines = []
    for who, body in (item.get("initial_state") or {}).items():
        parts = []
        hands = body.get("hands") or {}
        for h, label in (("left", "왼손"), ("right", "오른손")):
            if h in hands:
                parts.append(f"{label}={_thing(hands[h]) if hands[h] else '빈손'}")
        for other, facing in (body.get("facing") or {}).items():
            parts.append(f"{other}에게 {FACING_WORDS[facing]}을 보임")
        for zone, layers in (body.get("worn") or {}).items():
            parts.append(f"착용({zone})=" + (" → ".join(layers) + " (안쪽 → 바깥)" if layers else "없음"))
        for side, label in (("front", "몸 앞"), ("back", "몸 뒤")):
            if body.get(side) is not None:
                parts.append(f"{label}=" + (", ".join(_thing(x) for x in body[side]) or "비었음"))
        lines.append(f"- {who}: " + ("; ".join(parts) if parts else "알려진 상태 없음"))
    for obj, place in (item.get("items") or {}).items():
        lines.append(f"- {obj}: {place}에 있음")
    for alias, name in (item.get("aliases") or {}).items():
        lines.append(f"- '{alias}'는 '{name}'와 같은 물건")
    return "\n".join(lines) or "- 알려진 상태 없음"


def format_sentences(sentences):
    return "\n".join(f"[{i}] {s}" for i, s in enumerate(sentences))


def object_names(item):
    """Object names that the initial state, places, and aliases give. Gold events are not used."""
    names = []
    for body in (item.get("initial_state") or {}).values():
        names += [v for v in (body.get("hands") or {}).values() if v and not rules.is_person(v)]
        names += [x for layers in (body.get("worn") or {}).values() for x in layers]
        names += [x for side in ("front", "back") for x in (body.get(side) or []) if not rules.is_person(x)]
    names += list(item.get("items") or {})
    names += list((item.get("aliases") or {}).values())
    return list(dict.fromkeys(names))


def judge_prompt(item, with_state):
    parts = []
    if with_state:
        parts.append("장면 시작 상태:\n" + format_state(item))
    parts.append("문단(문장 번호 포함):\n" + format_sentences(item["sentences"]))
    parts.append("몸 상태 모순이 있으면 has_error=true, 모순이 처음 드러나는 문장 번호를 sentences 에, "
                 "가장 가까운 규칙을 rule 에 적어라. 모순이 없으면 has_error=false, rule=none.\n"
                 "규칙: hand_full(빈손 모자람), not_held(쥐지 않은 것을 놓음), tool_missing(도구를 쥐지 않음), "
                 "facing_mismatch(향한 쪽이 다름), hidden_side(등 보인 사람의 얼굴을 봄), layer_order(겹침 순서), "
                 "not_worn(입지 않은 것을 벗음), space_full(몸 앞뒤가 이미 참), contact_kept(잡은 채 멀어짐), "
                 "item_location(없는 곳에서 꺼냄), state_mismatch(묘사한 쥔 것 · 입은 것이 다름)")
    return "\n\n".join(parts)


def extract_prompt(item):
    people = list((item.get("initial_state") or {}).keys())
    objects = object_names(item)
    return "\n\n".join([
        "장면 시작 상태:\n" + format_state(item),
        "인물: " + (", ".join(people) or "없음"),
        "물건 목록: " + (", ".join(objects) or "없음"),
        "문단(문장 번호 포함):\n" + format_sentences(item["sentences"]),
        "각 문장의 사건을 뽑아라.",
    ])


# ---------- flat events ----------

def normalize(flat, people=()):
    """Turn a flat extracted event into the form that rules.py reads."""
    people = set(people)
    out = {"type": flat.get("type")}
    for f in FLAT_FIELDS:
        v = flat.get(f)
        if v not in ("", None) and f not in ("facing_who", "facing"):
            out[f] = v
    need = flat.get("free_hands_needed")
    if isinstance(need, int) and need > 0:
        out["free_hands_needed"] = need
    if flat.get("type") == "state" and flat.get("facing_who") and flat.get("facing"):
        out["facing"] = {flat["facing_who"]: flat["facing"]}
    # People named without "@" where a person is meant.
    for f in ("object", "front", "back"):
        v = out.get(f)
        if isinstance(v, str) and v in people:
            out[f] = "@" + v
    return out


def flatten(event):
    """Turn an event into the flat schema form (the reverse of normalize)."""
    flat = {"type": event["type"], **{f: "" for f in FLAT_FIELDS}, "free_hands_needed": 0}
    for k, v in event.items():
        if k == "facing" and isinstance(v, dict):
            (who, facing), = v.items()
            flat["facing_who"], flat["facing"] = who, facing
        elif k == "free_hands_needed":
            flat[k] = int(v or 0)
        elif k in flat and k != "type":
            flat[k] = v
    return flat
