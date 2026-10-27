"""Command line.

  python -m shadowcast validate data/scenes-v2-example.json hand-check/data/scenes.json
"""

import argparse
import sys

from . import scenes


def main():
    p = argparse.ArgumentParser(prog="python -m shadowcast")
    sub = p.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="check that gold events agree with gold labels")
    v.add_argument("paths", nargs="+")
    args = p.parse_args()
    if args.cmd == "validate":
        n_scenes, n_items, problems = scenes.validate_files(args.paths)
        for line in problems:
            print("FAIL", line)
        print(f"{n_scenes} scenes, {n_items} items, {len(problems)} problems")
        return 1 if problems else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
