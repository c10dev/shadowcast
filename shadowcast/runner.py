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
import math
import os
import sys
import time
from pathlib import Path

from . import backends, prompts, rules, scenes

ROOT = Path(__file__).parent.parent
DEFAULT_DATA = [ROOT / "data" / "scenes-v2-pilot.json"]
RESULTS = ROOT / "results"
ENV_FILES = [ROOT / ".env", ROOT / "hand-check" / ".env"]
MODEL_BACKENDS = tuple(backends.BACKENDS)
CONDITIONS = ("A", "B", "C", "D")
FAR = 15  # an error is "far" when its cause is more than this many sentences back


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
        return json.loads(path.read_text(encoding="utf-8"))
    out, meta = fn()
    record = {"key": key, "output": out, "meta": meta}
    cache.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return record


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

def judge(args, backend, item, with_state):
    if args.backend == "gold":
        err = item["error_sentence"]
        return {"has_error": err is not None, "sentences": [] if err is None else [err],
                "rule": item["rule"] or "none", "reason": "gold"}, {}
    if args.backend == "baseline":
        return {"has_error": False, "sentences": [], "rule": "none", "reason": "baseline"}, {}
    return backend.call(prompts.JUDGE_SYSTEM, prompts.judge_prompt(item, with_state), prompts.JUDGE_SCHEMA)


def unknown_start(item):
    """The item as condition D sees it: the characters are known, their bodies and the object places are not."""
    return {**item, "initial_state": {who: {} for who in prompts.character_names(item)},
            "items": None, "aliases": None}


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
        rule = out.get("rule") if out.get("rule") in prompts.RULES else None
        return {"has_error": bool(out.get("has_error")),
                "sentences": [i for i in out.get("sentences", []) if isinstance(i, int)],
                "rule": rule, "reason": out.get("reason", ""), "meta": rec["meta"]}
    with_state = cond == "C"
    rec = cached(cache, tag + "|" + prompts.EXTRACT_SYSTEM + "|" + prompts.extract_prompt(item, with_state),
                 lambda: extract(args, backend, item, with_state))
    if not with_state:
        item = unknown_start(item)  # judge and compare from the same unknown start
    events = events_from_extraction(rec["output"], item)
    states, violations = rules.run_scene(item.get("initial_state"), events, item.get("items"), item.get("aliases"))
    gold_states, _ = rules.run_scene(item.get("initial_state"), item["events"], item.get("items"), item.get("aliases"))
    # A malformed extracted event is an extraction failure, not a contradiction in the text.
    bad = [v for v in violations if v["rule"] == "bad_event"]
    violations = [v for v in violations if v["rule"] != "bad_event"]
    return {"has_error": bool(violations),
            "sentences": sorted({v["sentence"] for v in violations}),
            "rule": violations[0]["rule"] if violations else None,
            "reason": "; ".join(v["reason"] for v in violations),
            "channels": {ch: list(mt) for ch, mt in channel_accuracy(states, gold_states).items()},
            "bad_events": [v["reason"] for v in bad],
            "meta": rec["meta"]}


# ---------- scoring ----------

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


def score(rows, cond):
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
              "data": [str(p) for p in paths], "time": time.strftime("%Y-%m-%d %H:%M:%S"), "conditions": {}}
    conds = args.conditions.split(",")
    if any(c not in CONDITIONS for c in conds):
        print(f"Unknown condition in '{args.conditions}'. Use {', '.join(CONDITIONS)}.", file=sys.stderr)
        return 1
    for cond in conds:
        rows = []
        for it in items:
            try:
                pred = predict(args, backend, it, cond, cache)
            except Exception as e:  # keep going; failed items count as "no error"
                pred = {"has_error": False, "sentences": [], "rule": None, "reason": f"ERROR: {e}",
                        "channels": {}, "meta": {}}
                print(f"[{cond}] {it['item_id']}: {e}", file=sys.stderr)
            rows.append({"item_id": it["item_id"], "gold": it["error_sentence"] is not None,
                         "error_sentence": it["error_sentence"], "rule": it["rule"], "cause": it["cause"],
                         "n_sentences": len(it["sentences"]),
                         "difficulty": it["difficulty"], "traps": it["traps"] or [], "pred": pred})
        report["conditions"][cond] = {"metrics": score(rows, cond), "rows": rows}

    results.mkdir(parents=True, exist_ok=True)
    trial = f"-trial{args.trial}" if args.trial > 1 else ""
    name = f"run-v2-{time.strftime('%Y%m%d-%H%M%S')}-{args.backend}-{args.model or 'none'}{trial}.json".replace("/", "_")
    (results / name).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print_report(report, len(items))
    print(f"saved: {results / name}")
    return 0


def print_report(report, n_items):
    keys = ["accuracy", "precision", "recall", "false_alarm_rate", "localization", "rule_accuracy",
            "always_no_error_accuracy"]
    print(f"backend={report['backend']} model={report['model']} items={n_items}")
    print("cond  " + "  ".join(f"{k[:12]:>12}" for k in keys))
    for cond, res in report["conditions"].items():
        m = res["metrics"]
        print(f"{cond:<5} " + "  ".join(f"{m[k]:>12.2f}" for k in keys))
    for cond, res in report["conditions"].items():
        if "extraction" in res["metrics"]:
            print(f"extraction ({cond}): " + "  ".join(
                f"{ch} {v:.2f}" if v is not None else f"{ch} -" for ch, v in res["metrics"]["extraction"].items()))
    print("95% Wilson intervals and false alarms per 100 clean sentences")
    for cond, res in report["conditions"].items():
        m = res["metrics"]
        print(f"{cond:<5} recall {m['recall']:.2f} [{m['recall_ci'][0]:.2f}, {m['recall_ci'][1]:.2f}]"
              f"  false alarm {m['false_alarm_rate']:.2f} [{m['false_alarm_ci'][0]:.2f}, {m['false_alarm_ci'][1]:.2f}]"
              f"  per 100 clean sentences {m['false_alarms_per_100_clean_sentences']:.2f} (of {m['clean_sentences']})")
    print("\nerror items by group (recall / localization)")
    first = next(iter(report["conditions"].values()))["metrics"]
    for field in ("difficulty", "distance", "rule"):
        for key in first[f"by_{field}"]:
            cells = []
            for cond, res in report["conditions"].items():
                g = res["metrics"][f"by_{field}"][key]
                cells.append(f"{cond} {g['recall']:.2f}/{g['localization']:.2f}")
            print(f"  {field}={key} (n={first[f'by_{field}'][key]['n_error']}): " + "  ".join(cells))
    print("trap false alarm rate: " + "  ".join(
        f"{cond} {res['metrics']['trap_false_alarm_rate']:.2f}" for cond, res in report["conditions"].items()))
