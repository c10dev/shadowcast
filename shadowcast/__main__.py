"""Command line.

  python -m shadowcast validate data/scenes-v2-pilot.json data/scenes-v2-example.json hand-check/data/scenes.json
  python -m shadowcast run --backend gold
  python -m shadowcast run --backend gemini --limit 2
"""

import argparse
import sys

from . import analysis, runner, scenes


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m shadowcast")
    sub = p.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="check that gold events agree with gold labels")
    v.add_argument("paths", nargs="+")
    r = sub.add_parser("run", help="run conditions A, B, C, D on scene data")
    r.add_argument("--backend", choices=["gold", "baseline", *runner.MODEL_BACKENDS], required=True)
    r.add_argument("--model", default=None)
    r.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    r.add_argument("--conditions", default="A,B,C", help="A, B, C, D, comma-separated")
    r.add_argument("--trial", type=int, default=1, help="repeat number; 2 or more makes new calls for a repeat run")
    r.add_argument("--data", nargs="+", default=None, help="scene files (default: data/scenes-v2-pilot.json)")
    r.add_argument("--limit", type=int, default=0, help="use only the first N scenes")
    r.add_argument("--results", default=None, help="results folder (default: results/)")
    rescore = sub.add_parser("rescore", help="score a saved run offline; never calls a model")
    rescore.add_argument("report", help="original run JSON")
    rescore.add_argument("--output", required=True, help="new analysis JSON; must not already exist")
    rescore.add_argument("--complete-annotations", action="store_true",
                         help="explicitly assert all unmarked sentences are clean for sentence precision")
    audit = sub.add_parser("audit", help="prepare unreviewed C/D false-alarm cases offline")
    audit.add_argument("report", help="original run JSON")
    audit.add_argument("--data", nargs="+", required=True, help="scene files corresponding to the run")
    audit.add_argument("--cache", help="existing response cache directory (read only)")
    audit.add_argument("--output", required=True, help="new audit JSON; must not already exist")
    args = p.parse_args(argv)
    if args.cmd in ("rescore", "audit"):
        try:
            return analysis.run(args)
        except (OSError, ValueError, KeyError, TypeError) as e:
            print(f"Cannot {args.cmd}: {e}", file=sys.stderr)
            return 1
    if args.cmd == "validate":
        n_scenes, n_items, problems = scenes.validate_files(args.paths)
        for line in problems:
            print("FAIL", line)
        print(f"{n_scenes} scenes, {n_items} items, {len(problems)} problems")
        return 1 if problems else 0
    return runner.run(args)


if __name__ == "__main__":
    sys.exit(main())
