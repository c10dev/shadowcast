"""Hand-occupancy experiment runner.

  python run.py validate
  python run.py run --backend gold
  python run.py run --backend baseline
  python run.py run --backend anthropic --model claude-opus-5-5
  python run.py run --backend gemini --model gemini-4-argon
  python run.py run --backend ollama --model <local-model>

Conditions:
  A  paragraph only -> model judges
  B  paragraph + initial state -> model judges
  C  paragraph + initial state -> model extracts events -> rules.py judges

Credentials: put these in hand-check/.env (git-ignored).
  ANTHROPIC_API_KEY=...                          for --backend anthropic
  GOOGLE_APPLICATION_CREDENTIALS=/path/key.json  for --backend gemini (Vertex AI)
  or GEMINI_API_KEY=...                          for --backend gemini (API key)
"""

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import llm
import rules

ROOT = Path(__file__).parent
DATA = ROOT / "data" / "scenes.json"
RESULTS = ROOT / "results"
CACHE = RESULTS / "cache"
ENV_FILE = ROOT / ".env"


def load_env(path=ENV_FILE):
    """Read KEY=VALUE lines from a .env file into os.environ.

    Variables already set in the shell win over the file.
    Return the names that were set from the file.
    """
    if not path.exists():
        return []
    loaded = []
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
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()  # inline comment
        if key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded


def load_items(path=DATA):
    """Expand each scene into a clean item and an error item."""
    items = []
    for scene in json.loads(path.read_text(encoding="utf-8")):
        texts = [s["text"] for s in scene["sentences"]]
        events = [s["events"] for s in scene["sentences"]]
        base = {k: scene[k] for k in ("id", "title", "difficulty", "initial_state")}
        base["pattern"] = scene.get("pattern", "")
        base["traps"] = scene.get("traps", [])
        items.append({**base, "item_id": f"{scene['id']}-clean", "variant": "clean",
                      "sentences": texts, "events": events, "error_sentence": None})
        err = scene["error"]
        i = err["sentence"]
        items.append({**base, "item_id": f"{scene['id']}-error", "variant": "error",
                      "sentences": texts[:i] + [err["text"]] + texts[i + 1:],
                      "events": events[:i] + [err["events"]] + events[i + 1:],
                      "error_sentence": i, "note": err.get("note", "")})
    return items


def validate(items):
    """Check that gold events agree with gold labels."""
    problems = []
    for it in items:
        if len(it["sentences"]) != len(it["events"]):
            problems.append(f"{it['item_id']}: sentence and event counts differ")
            continue
        _, violations = rules.run_scene(it["initial_state"], it["events"])
        where = sorted({v["sentence"] for v in violations})
        if it["variant"] == "clean" and violations:
            problems.append(f"{it['item_id']}: clean item has violations {violations}")
        if it["variant"] == "error" and where != [it["error_sentence"]]:
            problems.append(f"{it['item_id']}: expected violation only at {it['error_sentence']}, got {violations}")
    return problems


def cached(key, fn):
    path = CACHE / (hashlib.sha256(key.encode()).hexdigest()[:24] + ".json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    out, meta = fn()
    record = {"key": key, "output": out, "meta": meta}
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return record


def events_from_extraction(extraction, n):
    events = [[] for _ in range(n)]
    for s in extraction.get("sentences", []):
        i = s.get("index")
        if isinstance(i, int) and 0 <= i < n:
            events[i] = s.get("events", [])
    return events


def predict(args, backend, item, cond):
    # The cache key holds the full prompt, so editing a prompt forces a new call.
    tag = f"{args.backend}|{args.model}|{args.effort}|{cond}|{item['item_id']}"
    if cond in ("A", "B"):
        rec = cached(tag + "|" + llm.JUDGE_SYSTEM + "|" + llm.judge_prompt(item, cond == "B"),
                     lambda: llm.judge(args.backend, backend, item, with_state=(cond == "B")))
        out = rec["output"]
        return {"has_error": bool(out.get("has_error")),
                "sentences": [i for i in out.get("sentences", []) if isinstance(i, int)],
                "reason": out.get("reason", ""), "meta": rec["meta"]}
    rec = cached(tag + "|" + llm.EXTRACT_SYSTEM + "|" + llm.extract_prompt(item),
                 lambda: llm.extract(args.backend, backend, item))
    events = events_from_extraction(rec["output"], len(item["sentences"]))
    states, violations = rules.run_scene(item["initial_state"], events)
    gold_states, _ = rules.run_scene(item["initial_state"], item["events"])
    return {"has_error": bool(violations),
            "sentences": sorted({v["sentence"] for v in violations}),
            "reason": "; ".join(v["reason"] for v in violations),
            "free_hands": rules.free_hand_counts(states),
            "gold_free_hands": rules.free_hand_counts(gold_states),
            "meta": rec["meta"]}


def score(rows, cond):
    tp = sum(r["gold"] and r["pred"]["has_error"] for r in rows)
    fp = sum((not r["gold"]) and r["pred"]["has_error"] for r in rows)
    fn = sum(r["gold"] and not r["pred"]["has_error"] for r in rows)
    tn = sum((not r["gold"]) and not r["pred"]["has_error"] for r in rows)
    n_err, n_clean = tp + fn, fp + tn
    located = sum(r["gold"] and r["pred"]["has_error"] and r["error_sentence"] in r["pred"]["sentences"]
                  for r in rows)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / n_err if n_err else 0.0
    out = {
        "n": len(rows),
        "accuracy": (tp + tn) / len(rows) if rows else 0.0,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "false_alarm_rate": fp / n_clean if n_clean else 0.0,
        "localization": located / n_err if n_err else 0.0,
        "always_no_error_accuracy": n_clean / len(rows) if rows else 0.0,
    }
    if cond == "C":
        match = total = 0
        for r in rows:
            if r["gold"]:
                continue  # extraction accuracy uses clean items only
            for pred_s, gold_s in zip(r["pred"]["free_hands"], r["pred"]["gold_free_hands"]):
                for who, count in gold_s.items():
                    total += 1
                    match += pred_s.get(who) == count
        out["extraction_free_hand_accuracy"] = match / total if total else 0.0

    # Breakdown on error items: which kinds of errors the model misses.
    for field in ("difficulty", "pattern"):
        groups = {}
        for r in rows:
            if r["gold"]:
                groups.setdefault(r[field], []).append(r)
        out[f"by_{field}"] = {
            key: {"n_error": len(g),
                  "recall": sum(r["pred"]["has_error"] for r in g) / len(g),
                  "localization": sum(r["pred"]["has_error"] and r["error_sentence"] in r["pred"]["sentences"]
                                      for r in g) / len(g)}
            for key, g in sorted(groups.items())
        }
    # Clean items with distractors (feet, shoulder, held tool): false alarms here are expected first.
    traps = [r for r in rows if not r["gold"] and r["traps"]]
    out["trap_false_alarm_rate"] = sum(r["pred"]["has_error"] for r in traps) / len(traps) if traps else 0.0
    return out


def cmd_run(args):
    items = load_items()
    problems = validate(items)
    if problems:
        print("Gold data is inconsistent. Run `python run.py validate` first.", file=sys.stderr)
        return 1
    if args.limit:
        items = items[: args.limit * 2]
    backend = llm.make_backend(args.backend, args.model, args.effort)
    report = {"backend": args.backend, "model": args.model, "effort": args.effort,
              "time": time.strftime("%Y-%m-%d %H:%M:%S"), "conditions": {}}
    for cond in args.conditions.split(","):
        rows = []
        for it in items:
            try:
                pred = predict(args, backend, it, cond)
            except Exception as e:  # keep going; failed items count as "no error"
                pred = {"has_error": False, "sentences": [], "reason": f"ERROR: {e}",
                        "free_hands": [], "gold_free_hands": [], "meta": {}}
                print(f"[{cond}] {it['item_id']}: {e}", file=sys.stderr)
            rows.append({"item_id": it["item_id"], "gold": it["error_sentence"] is not None,
                         "error_sentence": it["error_sentence"], "difficulty": it["difficulty"],
                         "pattern": it["pattern"], "traps": it["traps"], "pred": pred})
        report["conditions"][cond] = {"metrics": score(rows, cond), "rows": rows}

    RESULTS.mkdir(exist_ok=True)
    name = f"run-{time.strftime('%Y%m%d-%H%M%S')}-{args.backend}-{args.model or 'none'}.json".replace("/", "_")
    (RESULTS / name).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    keys = ["accuracy", "precision", "recall", "false_alarm_rate", "localization",
            "always_no_error_accuracy", "extraction_free_hand_accuracy"]
    print(f"backend={args.backend} model={args.model} items={len(items)}")
    print("cond  " + "  ".join(f"{k[:12]:>12}" for k in keys))
    for cond, res in report["conditions"].items():
        m = res["metrics"]
        print(f"{cond:<5} " + "  ".join(f"{m[k]:>12.2f}" if k in m else f"{'-':>12}" for k in keys))
    print("\nerror items by group (recall / localization)")
    for field in ("difficulty", "pattern"):
        groups = next(iter(report["conditions"].values()))["metrics"][f"by_{field}"]
        for key in groups:
            cells = []
            for cond, res in report["conditions"].items():
                g = res["metrics"][f"by_{field}"][key]
                cells.append(f"{cond} {g['recall']:.2f}/{g['localization']:.2f}")
            print(f"  {field}={key} (n={groups[key]['n_error']}): " + "  ".join(cells))
    print("trap false alarm rate: " + "  ".join(
        f"{cond} {res['metrics']['trap_false_alarm_rate']:.2f}" for cond, res in report["conditions"].items()))
    print(f"saved: results/{name}")
    return 0


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate")
    r = sub.add_parser("run")
    r.add_argument("--backend", choices=["gold", "baseline", "anthropic", "gemini", "ollama"], required=True)
    r.add_argument("--model", default=None)
    r.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    r.add_argument("--conditions", default="A,B,C")
    r.add_argument("--limit", type=int, default=0, help="use only the first N scenes")
    args = p.parse_args()
    load_env()

    if args.cmd == "validate":
        items = load_items()
        problems = validate(items)
        for line in problems:
            print("FAIL", line)
        print(f"{len(items)} items, {len(problems)} problems")
        return 1 if problems else 0
    if args.backend in ("anthropic", "gemini", "ollama") and not args.model:
        if args.backend == "anthropic":
            args.model = "claude-opus-5-5"
        elif args.backend == "gemini":
            args.model = llm.GeminiBackend.DEFAULT_MODEL
        else:
            p.error("--model is required for ollama")
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
