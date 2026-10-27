"""Scene data (format v2): load, convert from v1, expand into items, validate.

A scene is one JSON object. A file holds a list of scenes.
  id, title          names
  source             where the text comes from ("original", "hand-check v1", ...)
  difficulty         "explicit" or "implicit"
  patterns           error kinds in the scene, free text labels
  traps              actions in the clean text that look like errors but are not
  characters         {name: {"height_cm": int}} (optional, for a later height rule)
  aliases            {other name: object name}, for example {"껍데기": "달걀"}
  initial_state      {name: body}. See rules.py for the body fields.
  items              {object: place} at the start
  sentences          [{"text", "events": [...]}]
  errors             [{"sentence", "text", "events", "rule", "note"}]
                     Each error makes one error item: the clean text with one sentence replaced.

A v1 scene (hand-check/data/scenes.json) has "error" (one object) instead of "errors".
load() converts it to v2.
"""

import json
from pathlib import Path

from . import rules

REQUIRED = {
    "grab": ("object",),
    "release": (),
    "give": ("to", "object"),
    "use": (),
    "turn": (),
    "wear": ("item",),
    "take_off": ("item",),
    "touch": ("target", "kind"),
    "untouch": ("target",),
    "move": (),
    "state": (),
    "see": ("target",),
}

# All v1 patterns break the same rule: a hand is not free.
V1_PATTERN_RULE = {p: "hand_full" for p in ("grab_full", "use_full", "both_conflict", "handoff", "forgotten_object")}

SCENE_FIELDS = ("initial_state", "items", "aliases", "characters")


def is_v1(scene):
    return isinstance(scene.get("error"), dict)


def from_v1(scene):
    """Convert a v1 scene (hands only, one error) to v2."""
    out = {k: scene[k] for k in ("id", "title", "difficulty") if k in scene}
    out["source"] = "hand-check v1"
    out["patterns"] = [scene["pattern"]] if scene.get("pattern") else []
    out["traps"] = scene.get("traps", [])
    out["initial_state"] = {who: {"hands": {"left": h.get("left"), "right": h.get("right")}}
                            for who, h in scene["initial_state"].items()}
    out["sentences"] = scene["sentences"]
    error = dict(scene["error"])
    if scene.get("pattern") in V1_PATTERN_RULE:
        error["rule"] = V1_PATTERN_RULE[scene["pattern"]]
    out["errors"] = [error]
    return out


def load(path):
    """Read a scene file. v1 scenes come back as v2."""
    scenes = json.loads(Path(path).read_text(encoding="utf-8"))
    return [from_v1(s) if is_v1(s) else s for s in scenes]


def expand(scene):
    """Make the clean item and one error item per error."""
    texts = [s["text"] for s in scene["sentences"]]
    events = [s.get("events", []) for s in scene["sentences"]]
    base = {k: scene.get(k) for k in ("id", "title", "difficulty", "patterns", "traps", *SCENE_FIELDS)}
    items = [{**base, "item_id": f"{scene['id']}-clean", "variant": "clean",
              "sentences": texts, "events": events, "error_sentence": None, "rule": None}]
    errors = scene.get("errors", [])
    for j, err in enumerate(errors, 1):
        i = err["sentence"]
        suffix = "error" if len(errors) == 1 else f"error{j}"
        items.append({**base, "item_id": f"{scene['id']}-{suffix}", "variant": "error",
                      "sentences": texts[:i] + [err["text"]] + texts[i + 1:],
                      "events": events[:i] + [err.get("events", [])] + events[i + 1:],
                      "error_sentence": i, "rule": err.get("rule"), "note": err.get("note", "")})
    return items


def run_item(item):
    return rules.run_scene(item.get("initial_state"), item["events"], item.get("items"), item.get("aliases"))


def check_events(scene):
    """Shape problems: unknown event types and missing fields."""
    problems = []
    rows = [(f"sentence {i}", s.get("events", [])) for i, s in enumerate(scene.get("sentences", []))]
    rows += [(f"error {j}", e.get("events", [])) for j, e in enumerate(scene.get("errors", []))]
    for where, events in rows:
        for ev in events:
            kind = ev.get("type")
            if kind not in REQUIRED:
                problems.append(f"{scene['id']} {where}: unknown event type '{kind}'")
                continue
            missing = [f for f in ("character", *REQUIRED[kind]) if not ev.get(f)]
            if missing:
                problems.append(f"{scene['id']} {where}: {kind} event lacks {missing}")
    for j, err in enumerate(scene.get("errors", [])):
        if not 0 <= err.get("sentence", -1) < len(scene.get("sentences", [])):
            problems.append(f"{scene['id']} error {j}: sentence {err.get('sentence')} is out of range")
    return problems


def validate_scene(scene):
    """Check that the gold events agree with the gold labels.

    The clean item has no violation. Each error item has violations only
    at its error sentence. When the error gives a rule, the first violation breaks it.
    Later events in the same sentence can fail after it (a failed grab, then a give).
    """
    problems = check_events(scene)
    if problems:
        return problems
    for item in expand(scene):
        _, violations = run_item(item)
        where = sorted({v["sentence"] for v in violations})
        if item["variant"] == "clean":
            if violations:
                problems.append(f"{item['item_id']}: clean item has violations {violations}")
            continue
        if where != [item["error_sentence"]]:
            problems.append(f"{item['item_id']}: expected violation only at {item['error_sentence']}, got {violations}")
        elif item["rule"] and violations[0]["rule"] != item["rule"]:
            problems.append(f"{item['item_id']}: expected rule {item['rule']}, got {violations}")
    return problems


def validate_files(paths):
    """Return (scene count, item count, problems)."""
    scenes = [s for p in paths for s in load(p)]
    problems = []
    ids = [s["id"] for s in scenes]
    problems += [f"duplicate scene id '{i}'" for i in sorted({i for i in ids if ids.count(i) > 1})]
    for scene in scenes:
        problems += validate_scene(scene)
    return len(scenes), sum(len(expand(s)) for s in scenes), problems
