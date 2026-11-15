"""Experiment runner for format v2.

  python -m shadowcast run --backend gold
  python -m shadowcast run --backend baseline
  python -m shadowcast run --backend gemini --limit 2
  python -m shadowcast run --backend anthropic --model claude-sonnet-5-5

Data: data/scenes-v2-pilot.json by default (--data to change, more than one is allowed).
Credentials: .env at the repo root, then hand-check/.env (both git-ignored).
Results: results/run-*.json. Responses are cached in results/cache/ by the full prompt.
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import backends, evaluation, prompts, rules, scenes
from .extraction import events_from_extraction, unknown_start, schema_issues, extraction_issues
# Compatibility imports for callers of the original runner helpers.
from .evaluation import wilson, flagged_sentences, distance_group, legacy_score as score

ROOT = Path(__file__).parent.parent
DEFAULT_DATA = [ROOT / "data" / "scenes-v2-pilot.json"]
RESULTS = ROOT / "results"
ENV_FILES = [ROOT / ".env", ROOT / "hand-check" / ".env"]
MODEL_BACKENDS = tuple(backends.BACKENDS)
CONDITIONS = ("A", "B", "C", "D")


def load_env(paths=ENV_FILES):
    """Read KEY=VALUE lines into os.environ. Variables already set win. Return the names set."""
    loaded = []
    for path in paths:
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            key, sep, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if not sep or not key:
                continue
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if key not in os.environ:
                os.environ[key] = value
                loaded.append(key)
    return loaded


def cached(cache, key, fn):
    path = cache / (hashlib.sha256(key.encode()).hexdigest()[:24] + ".json")
    if path.exists():
        record = json.loads(path.read_text(encoding="utf-8"))
        return {**record, "cache_hit": True, "cache_path": str(path),
                "cache_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    out, meta = fn()
    record = {"key": key, "output": out, "meta": meta}
    cache.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return {**record, "cache_hit": False, "cache_path": str(path),
            "cache_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


# ---------- state channels for extraction accuracy ----------

def channels(state):
    """Reduce one state to comparable values per channel."""
    out = {"hands": {}, "facing": {}, "worn": {}, "space": {}}
    for who, b in state["bodies"].items():
        out["hands"][who] = len(rules.Scene.free(b["hands"]))
        for other, facing in b["facing"].items():
            out["facing"][(who, other)] = facing
        for zone, layers in b["worn"].items():
            out["worn"][(who, zone)] = layers[-1] if layers else None
        for side in rules.SIDES:
            if b[side] is not None:
                out["space"][(who, side)] = tuple(sorted(b[side]))
    return out


def channel_accuracy(pred_states, gold_states):
    """Per channel: (matches, total) over the values that the gold state knows."""
    acc = {}
    for p, g in zip(pred_states, gold_states):
        pc, gc = channels(p), channels(g)
        for ch, values in gc.items():
            m, t = acc.get(ch, (0, 0))
            for key, value in values.items():
                t += 1
                m += pc[ch].get(key) == value
            acc[ch] = (m, t)
    return acc


# ---------- prediction ----------

def prediction_result(pred, n, rec, issues=()):
    pred = {**pred, "status": "invalid_output" if issues else "ok",
            "verdict": None if issues else ("error" if pred["has_error"] else "no_error"),
            "issues": list(issues), "meta": rec["meta"],
            "provenance": {"status_source": "validated_response", "raw_response_checked": True,
                           "cache_path": rec["cache_path"], "cache_sha256": rec["cache_sha256"],
                           "cache_hit": rec["cache_hit"]}}
    return evaluation.normalize_prediction(pred, n)


def judge(args, backend, item, with_state):
    if args.backend == "gold":
        err = item["error_sentence"]
        return {"has_error": err is not None, "sentences": [] if err is None else [err],
                "rule": item["rule"] or "none", "reason": "gold"}, {}
    if args.backend == "baseline":
        return {"has_error": False, "sentences": [], "rule": "none", "reason": "baseline"}, {}
    return backend.call(prompts.JUDGE_SYSTEM, prompts.judge_prompt(item, with_state), prompts.JUDGE_SCHEMA)


def extract(args, backend, item, with_state=True):
    if args.backend == "gold":
        return {"sentences": [{"index": i, "events": [prompts.flatten(e) for e in ev]}
                              for i, ev in enumerate(item["events"])]}, {}
    if args.backend == "baseline":
        return {"sentences": [{"index": i, "events": []} for i in range(len(item["sentences"]))]}, {}
    return backend.call(prompts.EXTRACT_SYSTEM, prompts.extract_prompt(item, with_state), prompts.EXTRACT_SCHEMA)


def predict(args, backend, item, cond, cache):
    # The cache key holds the full prompt, so editing a prompt or the data forces a new call.
    tag = f"v2|{args.backend}|{args.model}|{args.effort}|{cond}|{item['item_id']}"
    if getattr(args, "trial", 1) > 1:
        tag += f"|trial{args.trial}"  # a repeat run makes new calls; trial 1 keeps the old cache keys
    if cond in ("A", "B"):
        rec = cached(cache, tag + "|" + prompts.JUDGE_SYSTEM + "|" + prompts.judge_prompt(item, cond == "B"),
                     lambda: judge(args, backend, item, with_state=(cond == "B")))
        out = rec["output"]
        issues = schema_issues(out, prompts.JUDGE_SCHEMA)
        if issues:
            return prediction_result({"has_error": False, "sentences": [], "rule": None,
                                      "reason": "invalid judge response"}, len(item["sentences"]), rec, issues)
        rule = out.get("rule") if out.get("rule") in prompts.RULES else None
        return prediction_result({"has_error": out["has_error"], "sentences": out["sentences"],
                                  "rule": rule, "reason": out["reason"]}, len(item["sentences"]), rec)
    with_state = cond == "C"
    rec = cached(cache, tag + "|" + prompts.EXTRACT_SYSTEM + "|" + prompts.extract_prompt(item, with_state),
                 lambda: extract(args, backend, item, with_state))
    issues = extraction_issues(rec["output"], len(item["sentences"]))
    if issues:
        return prediction_result({"has_error": False, "sentences": [], "rule": None,
                                  "reason": "invalid extraction", "channels": {}, "bad_events": issues},
                                 len(item["sentences"]), rec, issues)
    if not with_state:
        item = unknown_start(item)  # judge and compare from the same unknown start
    events = events_from_extraction(rec["output"], item)
    states, violations = rules.run_scene(item.get("initial_state"), events, item.get("items"), item.get("aliases"))
    gold_states, _ = rules.run_scene(item.get("initial_state"), item["events"], item.get("items"), item.get("aliases"))
    # A malformed extracted event is an extraction failure, not a contradiction in the text.
    bad = [v for v in violations if v["rule"] == "bad_event"]
    violations = [v for v in violations if v["rule"] != "bad_event"]
    return prediction_result({"has_error": bool(violations),
            "sentences": sorted({v["sentence"] for v in violations}),
            "rule": violations[0]["rule"] if violations else None,
            "reason": "; ".join(v["reason"] for v in violations),
            "channels": {ch: list(mt) for ch, mt in channel_accuracy(states, gold_states).items()},
            "bad_events": [v["reason"] for v in bad],
            "warnings": [{**v, "evidence": []} for v in violations]}, len(item["sentences"]), rec,
            [v["reason"] for v in bad])


# ---------- scoring ----------


def run(args):
    paths = [Path(p) for p in (args.data or DEFAULT_DATA)]
    n_scenes, _, problems = scenes.validate_files(paths)
    if problems:
        print("Gold data is inconsistent. Run `python -m shadowcast validate` first.", file=sys.stderr)
        return 1
    scene_list = [s for p in paths for s in scenes.load(p)]
    if args.limit:
        scene_list = scene_list[: args.limit]
    items = [i for s in scene_list for i in scenes.expand(s)]
    if args.backend in MODEL_BACKENDS:
        load_env()
    backend = backends.make_backend(args.backend, args.model, args.effort)
    if backend is not None:
        args.model = backend.model
    results = Path(args.results) if args.results else RESULTS
    cache = results / "cache"
    report = {"backend": args.backend, "model": args.model, "effort": args.effort, "trial": args.trial,
              "report_version": 3, "metrics_version": evaluation.METRICS_VERSION,
              "legacy_metrics_version": 1,
              "data": [str(p) for p in paths], "time": datetime.now(timezone.utc).isoformat(),
              "provenance": {"data_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
                             "code_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                             for p in Path(__file__).parent.glob("*.py")},
                             "effort_sent": args.effort if args.backend == "anthropic" else None,
                             "retry_policy": "one attempt per item; backend SDK retries are not item trials"},
              "conditions": {}}
    conds = args.conditions.split(",")
    if any(c not in CONDITIONS for c in conds):
        print(f"Unknown condition in '{args.conditions}'. Use {', '.join(CONDITIONS)}.", file=sys.stderr)
        return 1
    for cond in conds:
        rows = []
        for it in items:
            try:
                pred = predict(args, backend, it, cond, cache)
            except Exception as e:  # preserve the failed attempt separately from the text verdict
                pred = {"has_error": False, "sentences": [], "rule": None, "reason": f"ERROR: {e}",
                        "channels": {}, "meta": {}, "status": "invalid_output" if isinstance(e, json.JSONDecodeError)
                        else "call_error", "verdict": None, "warnings": [], "issues": [str(e)],
                        "provenance": {"status_source": "runner_exception", "raw_response_checked": False}}
                print(f"[{cond}] {it['item_id']}: {e}", file=sys.stderr)
            rows.append({"item_id": it["item_id"], "gold": it["error_sentence"] is not None,
                         "scene_id": it["id"], "annotation_complete": True,
                         "error_sentence": it["error_sentence"], "rule": it["rule"], "cause": it["cause"],
                         "n_sentences": len(it["sentences"]),
                         "difficulty": it["difficulty"], "traps": it["traps"] or [], "pred": pred})
        report["conditions"][cond] = {"metrics": evaluation.evaluate(rows),
                                      "legacy_metrics": score(rows, cond), "rows": rows}

    results.mkdir(parents=True, exist_ok=True)
    trial = f"-trial{args.trial}" if args.trial > 1 else ""
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    name = f"run-v2-{stamp}-{args.backend}-{args.model or 'none'}{trial}.json".replace("/", "_")
    with (results / name).open("x", encoding="utf-8") as f:
        f.write(json.dumps(report, ensure_ascii=False, indent=1))
    print_report(report, len(items))
    print(f"saved: {results / name}")
    return 0


def print_report(report, n_items):
    def fmt(value):
        return "-" if value is None else f"{value:.3f}"

    print(f"backend={report['backend']} model={report['model']} items={n_items} metrics=v2")
    print("cond  completed  call/invalid/abstain  localization(all/completed)  false_alarm  sentence_precision")
    for cond, result in report["conditions"].items():
        m = result["metrics"]
        c = m["counts"]
        print(f"{cond:<5} {c['completed']}/{c['attempted']}  "
              f"{c['call_error']}/{c['invalid_output']}/{c['undetermined']}  "
              f"{fmt(m['localization'])}/{fmt(m['localization_completed'])}  "
              f"{fmt(m['false_alarm_rate'])}  {fmt(m['sentence_precision'])}")
        print(f"      completed clean/error: {c['completed_clean']}/{c['clean']}, "
              f"{c['completed_error']}/{c['error']}; false alarms per 100 clean sentences: "
              f"{fmt(m['false_alarms_per_100_clean_sentences'])}; "
              f"warnings without position: {c['warnings_without_position']}")
    print("Historical item metrics and coarse state scores are saved under legacy_metrics (v1).")
