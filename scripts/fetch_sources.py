#!/usr/bin/env python3
"""Fetch the external datasets and check their licenses.

  python scripts/fetch_sources.py --check              licenses of the cloned datasets
  python scripts/fetch_sources.py --fetch [id ...]     clone missing datasets at the pinned commit
  python scripts/fetch_sources.py --update-lock        record the cloned commits in data/sources.lock.json

Datasets live in tmp/ (ignored by git). Their license file must contain the
strings listed in data/sources.yml; when one is missing the check fails, so a
license change is noticed before the data is used.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "data" / "sources.yml"
LOCK = ROOT / "data" / "sources.lock.json"


def load_registry(path=REGISTRY) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))["sources"]


def fetchable(registry: dict) -> dict:
    return {k: v for k, v in registry.items() if v.get("fetch")}


def check_license(src: dict, root: Path = ROOT) -> list:
    """Problems found in the dataset's license file (empty list = fine)."""
    base = root / src["dir"]
    lic = base / src["license_file"]
    if not lic.is_file():
        return [f"{src['dir']}/{src['license_file']}: license file not found"]
    text = lic.read_text(encoding="utf-8", errors="replace")
    return [f"{src['dir']}/{src['license_file']}: missing {m!r}"
            for m in src["license_markers"] if m not in text]


def current_commit(base: Path):
    r = subprocess.run(["git", "-C", str(base), "rev-parse", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def _git(*args, cwd=None):
    env = dict(os.environ, GIT_LFS_SKIP_SMUDGE="1")
    r = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()[:300]}")


def fetch(src: dict, sha=None, root: Path = ROOT) -> str:
    """Clone one dataset (shallow). With a pinned commit, fetch exactly that commit."""
    base = root / src["dir"]
    if (base / ".git").is_dir():
        return "already present"
    base.parent.mkdir(parents=True, exist_ok=True)
    if sha:
        base.mkdir(parents=True)
        _git("init", "-q", cwd=base)
        _git("remote", "add", "origin", src["repo"], cwd=base)
        _git("fetch", "-q", "--depth", "1", "origin", sha, cwd=base)
        _git("checkout", "-q", "FETCH_HEAD", cwd=base)
    else:
        _git("clone", "-q", "--depth", "1", src["repo"], str(base))
    return "fetched"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--fetch", nargs="*", metavar="ID")
    ap.add_argument("--update-lock", action="store_true")
    a = ap.parse_args(argv)
    registry = fetchable(load_registry())
    lock = json.loads(LOCK.read_text(encoding="utf-8")) if LOCK.exists() else {}
    status = 0

    if a.fetch is not None:
        for sid in (a.fetch or registry):
            if sid not in registry:
                print(f"{sid}: unknown or not fetchable")
                status = 1
                continue
            try:
                print(f"{sid}: {fetch(registry[sid], (lock.get(sid) or {}).get('commit'))}")
            except RuntimeError as e:
                print(f"{sid}: {e}")
                status = 1

    if a.update_lock:
        new = {}
        for sid, src in registry.items():
            sha = current_commit(ROOT / src["dir"])
            if sha:
                new[sid] = {"commit": sha}
        LOCK.write_text(json.dumps(new, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"lock written for {len(new)} datasets")

    if a.check or (a.fetch is None and not a.update_lock):
        for sid, src in registry.items():
            problems = check_license(src)
            print(f"{sid}: {'OK ' + src['license'] if not problems else 'PROBLEM'}")
            for p in problems:
                print(f"  - {p}")
            status = status or (1 if problems else 0)
    return status


if __name__ == "__main__":
    sys.exit(main())
