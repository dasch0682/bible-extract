"""Pre-run price check: `python check_prices.py` (Termux and GitHub Actions).

Exit code 0 = prices match models.yml, 1 = stop (no model call may be made).
There is deliberately no option to skip or silence the check.
"""
import argparse
import os
import sys

from models import MODELS_PATH, fetch_published, format_report, run_check


def main(argv=None, fetch=fetch_published, path=MODELS_PATH) -> int:
    ap = argparse.ArgumentParser(description="Compare models.yml with OpenRouter's published prices.")
    ap.add_argument("--models", default=str(path), help="path to models.yml")
    args = ap.parse_args(argv)

    result = run_check(args.models, fetch=fetch)
    report = format_report(result)
    print(report)

    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(report + "\n")

    if not result.ok:
        print("Stopped: no model call was made. Edit models.yml (new price_ref or another model) to continue.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
