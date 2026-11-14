"""Read-only analysis of saved runs. Never instantiates a model backend."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from . import evaluation, prompts, rules, scenes
from .extraction import events_from_extraction, extraction_issues, unknown_start


def fingerprint(path):
    path = Path(path)
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def read_report(path):
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    if report.get("operation"):
        raise ValueError("use an original run report, not an analysis output")
    if report.get("metrics_version", 1) not in (1, evaluation.METRICS_VERSION):
        raise ValueError("unsupported metrics version")
    if not isinstance(report.get("conditions"), dict) or not report["conditions"]:
        raise ValueError("report has no conditions")
    for cond, result in report["conditions"].items():
        if cond not in ("A", "B", "C", "D"):
            raise ValueError(f"unknown condition {cond}")
        seen = set()
        for row in result["rows"]:
            key, n, gold = row["item_id"], row["n_sentences"], row["gold"]
            if key in seen or type(n) is not int or n < 1 or type(gold) is not bool:
                raise ValueError(f"invalid or duplicate row: {cond}/{key}")
            err = row["error_sentence"]
            if (gold and (type(err) is not int or not 0 <= err < n)) or (not gold and err is not None):
                raise ValueError(f"invalid gold label: {cond}/{key}")
            seen.add(key)
    return report


def analysis_header(report, path, operation):
    return {"operation": operation, "report_version": 3, "metrics_version": evaluation.METRICS_VERSION,
            "source": fingerprint(path), "created_at": datetime.now(timezone.utc).isoformat(),
            "backend": report.get("backend"), "model": report.get("model"),
            "trial": report.get("trial", 1), "effort": report.get("effort"),
            "source_provenance": report.get("provenance", "unknown"),
            "analysis_code": {p.name: fingerprint(p)["sha256"] for p in Path(__file__).parent.glob("*.py")}}


def rescore(path, complete_annotations=False):
    report = read_report(path)
    out = analysis_header(report, path, "rescore")
    out["annotation_assumption"] = "all unmarked sentences are clean" if complete_annotations else "from rows only"
    out["limitations"] = ["Saved fields cannot establish original response completeness.",
                          "Strict state scores require original events and a separate replay."]
    out["conditions"] = {}
    for cond, result in report["conditions"].items():
        rows = [{**r, "pred": evaluation.normalize_prediction(r["pred"], r["n_sentences"])}
                for r in result["rows"]]
        if complete_annotations:
            rows = [{**r, "annotation_complete": True} for r in rows]
        out["conditions"][cond] = {"metrics": evaluation.evaluate(rows),
                                   "original_metrics": result.get("metrics"),
                                   "original_metrics_version": report.get("metrics_version", 1),
                                   "legacy_metrics": result.get("legacy_metrics", result.get("metrics")),
                                   "rows": rows}
    return out


def matching_cache(report, row, item, cond, cache):
    """Verify the full stored request, not just the hashed cache filename.

    Old prompts that cannot be reconstructed remain unresolved. A full match
    binds text and input state; it does not certify historical gold annotations.
    """
    if cache is None:
        return None, "cache directory not supplied"
    tag = f"v2|{report['backend']}|{report['model']}|{report['effort']}|{cond}|{item['item_id']}"
    if report.get("trial", 1) > 1:
        tag += f"|trial{report['trial']}"
    key = tag + "|" + prompts.EXTRACT_SYSTEM + "|" + prompts.extract_prompt(item, cond == "C")
    path = Path(cache) / (hashlib.sha256(key.encode()).hexdigest()[:24] + ".json")
    if not path.exists():
        return None, "no cache matching the complete request for the supplied data/current prompt"
    rec = json.loads(path.read_text(encoding="utf-8"))
    if rec.get("key") != key:
        return None, "cache key content does not match request"
    expected = row["pred"].get("provenance", {}).get("cache_sha256")
    ref = fingerprint(path)
    if expected and expected != ref["sha256"]:
        return None, "cache content changed since the run"
    if rec.get("meta") != row["pred"].get("meta"):
        return None, "cache response metadata does not match saved prediction"
    return {**rec, "source": ref}, None


def event_trace(item, events):
    """Diagnostic replay with the current checker, including pre-event state."""
    scene = rules.Scene(item.get("initial_state"), item.get("items"), item.get("aliases"))
    trace, violations = [], []
    for i, sentence in enumerate(events):
        for j, event in enumerate(sentence):
            before = scene.snapshot()
            result = scene.apply(event)
            violation = {"sentence": i, "rule": result[0], "reason": result[1]} if result else None
            trace.append({"sentence": i, "event_index": j, "event": event,
                          "before": before, "after": scene.snapshot(), "violation": violation})
            if violation:
                violations.append(violation)
    return trace, violations


def audit(path, data, cache=None):
    report = read_report(path)
    out = analysis_header(report, path, "audit")
    out["data"] = [fingerprint(p) for p in data]
    items = {}
    for p in data:
        for scene in scenes.load(p):
            for item in scenes.expand(scene):
                if item["item_id"] in items:
                    raise ValueError(f"duplicate data item: {item['item_id']}")
                items[item["item_id"]] = item
    out["scope"] = "all recorded clean-item warnings in C/D, including invalid outputs for diagnosis"
    out["limitations"] = ["Trace uses the current checker, not an inferred historical checker.",
                          "Legacy gold annotations have no hash; matching labels do not certify annotation identity.",
                          "Generated cases are unreviewed, not automatically diagnosed causes."]
    cases = []
    for cond, result in report["conditions"].items():
        if cond not in ("C", "D"):
            continue
        for row in result["rows"]:
            if row["gold"] or row["pred"].get("has_error") is not True:
                continue
            case = {"item_id": row["item_id"], "condition": cond, "trial": report.get("trial", 1),
                    "prediction": row["pred"], "data_match": "unverified", "missing": [],
                    "review": {"status": "unreviewed", "primary_cause": "unresolved",
                               "secondary_causes": [], "reason": "requires evidence review",
                               "reviewer": None, "reviewed_at": None, "root_cause_ids": []}}
            cases.append(case)
            item = items.get(row["item_id"])
            if item is None:
                case["missing"].append("item not found in supplied data")
                continue
            if len(item["sentences"]) != row["n_sentences"] or item["error_sentence"] != row["error_sentence"]:
                case["missing"].append("data row metadata does not match")
                continue
            known_hashes = report.get("provenance", {}).get("data_sha256", {})
            if known_hashes and any(d["sha256"] not in known_hashes.values() for d in out["data"]):
                case["missing"].append("supplied dataset hash differs from the run")
                continue
            rec, problem = matching_cache(report, row, item, cond, cache)
            if problem:
                case["missing"].append(problem)
                continue
            case.update(data_match="full_request_match", cache=rec["source"],
                        scene_id=item["id"], sentences=item["sentences"], gold_events=item["events"])
            issues = extraction_issues(rec["output"], len(item["sentences"]))
            case["extraction_issues"] = issues
            case["raw_extraction"] = rec["output"]
            if issues:
                case["missing"].append("complete valid extraction unavailable for diagnostic replay")
                continue
            start = item if cond == "C" else unknown_start(item)
            events = events_from_extraction(rec["output"], start)
            trace, violations = event_trace(start, events)
            bad_events = [v for v in violations if v["rule"] == "bad_event"]
            case["replay_bad_events"] = bad_events
            if bad_events:
                case["missing"].append("semantic event errors prevent a complete diagnostic replay")
            violations = [v for v in violations if v["rule"] != "bad_event"]
            replay_positions = sorted({v["sentence"] for v in violations})
            case.update(extracted_events=events, trace=trace, replay_violations=violations,
                        replay_matches_saved=(not bad_events
                                              and replay_positions == sorted(set(row["pred"]["sentences"]))
                                              and (violations[0]["rule"] if violations else None) == row["pred"].get("rule")
                                              and "; ".join(v["reason"] for v in violations) == row["pred"].get("reason")))
    out["cases"] = cases
    out["summary"] = {"items": len(cases), "request_matched": sum(c["data_match"] == "full_request_match" for c in cases),
                      "unreviewed": len(cases)}
    return out


def run(args):
    output = Path(args.output)
    # Exclusive creation protects both original inputs and previous analyses.
    if output.exists():
        raise ValueError(f"output already exists: {output}")
    if args.cmd == "rescore":
        result = rescore(args.report, args.complete_annotations)
    else:
        result = audit(args.report, args.data, args.cache)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    if args.cmd == "rescore":
        for cond, value in result["conditions"].items():
            m = value["metrics"]
            print(f"{cond}: completed={m['counts']['completed']}/{m['counts']['attempted']} "
                  f"localization={m['localization']} false_alarm={m['false_alarm_rate']}")
    else:
        print(json.dumps(result["summary"], ensure_ascii=False))
    print(f"saved: {output}")
    return 0
