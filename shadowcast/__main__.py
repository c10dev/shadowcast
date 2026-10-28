"""Command line.

  python -m shadowcast validate data/scenes-v2-pilot.json data/scenes-v2-example.json hand-check/data/scenes.json
  python -m shadowcast run --backend gold
  python -m shadowcast run --backend gemini --limit 2
"""

import argparse
import sys

from . import runner, scenes


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
    args = p.parse_args(argv)
    if args.cmd == "validate":
        n_scenes, n_items, problems = scenes.validate_files(args.paths)
        for line in problems:
            print("FAIL", line)
        print(f"{n_scenes} scenes, {n_items} items, {len(problems)} problems")
        return 1 if problems else 0
    return runner.run(args)


if __name__ == "__main__":
    sys.exit(main())
