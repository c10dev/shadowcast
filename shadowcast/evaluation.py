"""Pure scoring of saved predictions. No model calls or rule replay."""

import math

METRICS_VERSION = 2
FAR = 15


def normalize_prediction(pred, n_sentences):
    """Read legacy or versioned predictions without modifying the input.

    Legacy records cannot prove that the original response was complete. Keep
    that limitation, and never manufacture per-warning rules or evidence.
    """
    if not isinstance(pred, dict):
        pred = {"issues": ["prediction is not an object"]}
    out = {**pred}
    issues = list(pred.get("issues", []))
    source = "explicit_status" if "status" in pred else "legacy_fields"
    status = pred.get("status", "ok")
    verdict = pred.get("verdict")
    if "status" not in pred:
        if isinstance(pred.get("reason"), str) and pred["reason"].startswith("ERROR:"):
            status = "call_error"
            issues.append("legacy runner ERROR record")
        elif pred.get("bad_events"):
            status = "invalid_output"
            issues.append("legacy extracted events contain bad_event")
        else:
            verdict = "error" if pred.get("has_error") is True else "no_error"
    if status not in ("ok", "call_error", "invalid_output"):
        issues.append("unknown status")
        status = "invalid_output"
    if status == "ok":
        prior_issues = len(issues)
        if type(pred.get("has_error")) is not bool:
            issues.append("has_error must be a boolean")
        positions = pred.get("sentences")
        if not isinstance(positions, list) or any(
                type(i) is not int or not 0 <= i < n_sentences for i in positions):
            issues.append("sentences must contain in-range integer indices")
        if verdict not in ("error", "no_error", "undetermined"):
            issues.append("unknown or missing verdict")
        elif pred.get("has_error") != (verdict == "error"):
            issues.append("verdict disagrees with has_error")
        if verdict in ("no_error", "undetermined") and positions:
            issues.append("non-error verdict has warning positions")
        if pred.get("bad_events"):
            issues.append("extracted events contain bad_event")
        if len(issues) > prior_issues:
            status = "invalid_output"
    if status != "ok":
        verdict = None
    out.update(status=status, verdict=verdict, issues=issues)
    out.setdefault("warnings", [{"sentence": i, "rule": None, "reason": None, "evidence": []}
                                for i in sorted(set(pred.get("sentences", [])))]
                   if status == "ok" and verdict == "error" else [])
    out.setdefault("provenance", {"status_source": source, "raw_response_checked": False})
    return out


def ratio(k, n):
    return k / n if n else None


def evaluate(rows):
    """Version 2 metrics: failures and abstentions never count as true negatives."""
    normalized = [{**r, "pred": normalize_prediction(r["pred"], r["n_sentences"])} for r in rows]
    completed = [r for r in normalized if r["pred"]["status"] == "ok"
                 and r["pred"]["verdict"] in ("error", "no_error")]
    clean = [r for r in completed if not r["gold"]]
    errors = [r for r in completed if r["gold"]]
    n_error = sum(r["gold"] for r in rows)
    n_clean = len(rows) - n_error
    warned = [r for r in completed if r["pred"]["verdict"] == "error"]
    located = sum(r["error_sentence"] in r["pred"]["sentences"] for r in warned if r["gold"])
    false_alarms = sum(not r["gold"] for r in warned)
    warning_sentences = sum(len(set(r["pred"]["sentences"])) for r in warned)
    clean_flags = sum(len(set(r["pred"]["sentences"])) for r in warned if not r["gold"])
    clean_sentences = sum(r["n_sentences"] for r in clean)
    missing_positions = sum(not r["pred"]["sentences"] for r in warned)
    annotations_complete = all(r.get("annotation_complete") is True for r in completed)
    counts = {
        "attempted": len(rows), "clean": n_clean, "error": n_error,
        "completed": len(completed), "completed_clean": len(clean), "completed_error": len(errors),
        "call_error": sum(r["pred"]["status"] == "call_error" for r in normalized),
        "invalid_output": sum(r["pred"]["status"] == "invalid_output" for r in normalized),
        "undetermined": sum(r["pred"]["verdict"] == "undetermined" for r in normalized),
        "located_errors": located, "false_alarm_items": false_alarms,
        "warning_sentences": warning_sentences, "clean_warning_sentences": clean_flags,
        "completed_clean_sentences": clean_sentences, "warnings_without_position": missing_positions,
    }
    rates = {
        "completion_rate": (len(completed), len(rows)),
        "clean_completion_rate": (len(clean), n_clean),
        "error_completion_rate": (len(errors), n_error),
        "localization": (located, n_error),
        "localization_completed": (located, len(errors)),
        "false_alarm_rate": (false_alarms, len(clean)),
        "sentence_precision": (located, warning_sentences),
    }
    out = {"version": METRICS_VERSION, "counts": counts,
           **{key: ratio(k, n) for key, (k, n) in rates.items()},
           "denominators": {key: n for key, (_, n) in rates.items()},
           "false_alarms_per_100_clean_sentences": 100 * clean_flags / clean_sentences if clean_sentences else None,
           "sentence_metrics_complete": not missing_positions,
           "annotations_complete": annotations_complete,
           "localization_ci": wilson(located, n_error) if n_error else None,
           "false_alarm_ci": wilson(false_alarms, len(clean)) if clean else None}
    if not annotations_complete or missing_positions:
        out["sentence_precision"] = None
    return out


def wilson(k, n, z=1.96):
    """Wilson 95% interval for k successes in n trials, as [low, high]."""
    if not n:
        return [0.0, 1.0]
    p = k / n
    center = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [max(0.0, center - half), min(1.0, center + half)]


def flagged_sentences(pred):
    """Warnings that an author sees: one per flagged sentence, at least one when the item is flagged."""
    return max(1, len(set(pred["sentences"]))) if pred["has_error"] else 0


def distance_group(row):
    if row.get("cause") is None:
        return "-"
    return "far" if row["error_sentence"] - row["cause"] > FAR else "near"


def legacy_score(rows, cond):
    tp = sum(r["gold"] and r["pred"]["has_error"] for r in rows)
    fp = sum((not r["gold"]) and r["pred"]["has_error"] for r in rows)
    fn = sum(r["gold"] and not r["pred"]["has_error"] for r in rows)
    tn = sum((not r["gold"]) and not r["pred"]["has_error"] for r in rows)
    n_err, n_clean = tp + fn, fp + tn
    located = [r for r in rows if r["gold"] and r["pred"]["has_error"] and r["error_sentence"] in r["pred"]["sentences"]]
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / n_err if n_err else 0.0
    out = {
        "n": len(rows),
        "accuracy": (tp + tn) / len(rows) if rows else 0.0,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "false_alarm_rate": fp / n_clean if n_clean else 0.0,
        "localization": len(located) / n_err if n_err else 0.0,
        # Of the errors found at the right sentence, how many name the right rule.
        "rule_accuracy": sum(r["pred"]["rule"] == r["rule"] for r in located) / len(located) if located else 0.0,
        "always_no_error_accuracy": n_clean / len(rows) if rows else 0.0,
        "recall_ci": wilson(tp, n_err),
        "false_alarm_ci": wilson(fp, n_clean),
    }
    clean_sentences = sum(r["n_sentences"] for r in rows if not r["gold"])
    clean_flags = sum(flagged_sentences(r["pred"]) for r in rows if not r["gold"])
    out["clean_sentences"] = clean_sentences
    out["false_alarms_per_100_clean_sentences"] = 100 * clean_flags / clean_sentences if clean_sentences else 0.0
    if cond in ("C", "D"):
        totals = {}
        for r in rows:
            if r["gold"]:
                continue  # extraction accuracy uses clean items only
            for ch, (m, t) in r["pred"]["channels"].items():
                tm, tt = totals.get(ch, (0, 0))
                totals[ch] = (tm + m, tt + t)
        out["extraction"] = {ch: (m / t if t else None) for ch, (m, t) in sorted(totals.items())}
    for field, key_of in (("difficulty", lambda r: r["difficulty"] or "-"), ("rule", lambda r: r["rule"] or "-"),
                          ("distance", distance_group)):
        groups = {}
        for r in rows:
            if r["gold"]:
                groups.setdefault(key_of(r), []).append(r)
        out[f"by_{field}"] = {
            key: {"n_error": len(g),
                  "recall": sum(r["pred"]["has_error"] for r in g) / len(g),
                  "recall_ci": wilson(sum(r["pred"]["has_error"] for r in g), len(g)),
                  "localization": sum(r["pred"]["has_error"] and r["error_sentence"] in r["pred"]["sentences"]
                                      for r in g) / len(g)}
            for key, g in sorted(groups.items())
        }
    traps = [r for r in rows if not r["gold"] and r["traps"]]
    out["trap_false_alarm_rate"] = sum(r["pred"]["has_error"] for r in traps) / len(traps) if traps else 0.0
    return out
