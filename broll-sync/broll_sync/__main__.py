import argparse, json, os, sys, fcntl
from .drive import Drive, AuthError
from .sync import Sync
from . import state


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/sources.json")
    ap.add_argument("--overrides", default="config/known_subjects.json")
    ap.add_argument("--pilot", default=None, help="pilot config: ONLY the files listed there are touched")
    ap.add_argument("--dry-run", action="store_true", help="read-only preview")
    ap.add_argument("--state-dir", default="state")
    a = ap.parse_args()
    cfg = json.load(open(a.config)); ov = json.load(open(a.overrides)) if os.path.exists(a.overrides) else {}
    runs_path = os.path.join(a.state_dir, "pilot_runs.jsonl" if a.pilot else "runs.jsonl")
    prev = (state.load(runs_path) or [{}])[-1]
    lock = open("/tmp/broll_sync.lock", "w")
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError: print("another run is active; exiting"); return 0
    try:
        s = Sync(Drive.from_env(), cfg, ov, dry_run=a.dry_run, previous=prev)
        summary = s.run_pilot(json.load(open(a.pilot))) if a.pilot else s.run()
    except AuthError as e:
        print(f"AUTH FAILURE (needs human re-consent or access fix): {e}"); return 2
    print("SUMMARY " + json.dumps(summary))
    if not a.dry_run:                       # previews never write state
        state.append(runs_path, summary)
        for r in s.rows:
            state.append(os.path.join(a.state_dir, "pilot_mapping.jsonl" if a.pilot else "mapping.jsonl"), r)
    return 0 if summary["status"] == "ok" else 1


sys.exit(main())
