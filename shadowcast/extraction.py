"""Shared response validation and event conversion; no model calls."""

from . import prompts, scenes


def people_of(item):
    return list((item.get("initial_state") or {}).keys())


def events_from_extraction(extraction, item):
    n = len(item["sentences"])
    events = [[] for _ in range(n)]
    for s in extraction.get("sentences", []):
        i = s.get("index")
        if isinstance(i, int) and 0 <= i < n:
            events[i] = [prompts.normalize(e, people_of(item)) for e in s.get("events", [])]
    return events



def schema_issues(value, schema, path="response"):
    """Validate the small JSON Schema subset used by our model responses."""
    kind = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool}
    if kind in types and type(value) is not types[kind]:
        return [f"{path}: expected {kind}"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{path}: value outside enum"]
    issues = []
    if kind == "object":
        issues += [f"{path}: missing {k}" for k in schema.get("required", []) if k not in value]
        for k, child in schema.get("properties", {}).items():
            if k in value:
                issues += schema_issues(value[k], child, f"{path}.{k}")
    elif kind == "array":
        for i, child in enumerate(value):
            issues += schema_issues(child, schema["items"], f"{path}[{i}]")
    return issues


def extraction_issues(output, n):
    issues = schema_issues(output, prompts.EXTRACT_SCHEMA)
    if issues:
        return issues
    indices = [s["index"] for s in output["sentences"]]
    if sorted(indices) != list(range(n)):
        issues.append("extraction must include each sentence index exactly once")
    for s in output["sentences"]:
        for ev in s["events"]:
            missing = [k for k in ("character", *scenes.REQUIRED[ev["type"]]) if not ev[k]]
            if missing:
                issues.append(f"sentence {s['index']}: {ev['type']} lacks {missing}")
            if not 0 <= ev["free_hands_needed"] <= 2:
                issues.append(f"sentence {s['index']}: free_hands_needed outside 0..2")
    return issues



def unknown_start(item):
    """The item as condition D sees it: the characters are known, their bodies and the object places are not."""
    return {**item, "initial_state": {who: {} for who in prompts.character_names(item)},
            "items": None, "aliases": None}
