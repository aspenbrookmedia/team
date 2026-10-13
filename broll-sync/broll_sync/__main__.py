import argparse, json, os, sys, fcntl
from .drive import Drive, AuthError
from .sync import Sync


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/sources.json")
    ap.add_argument("--overrides", default="config/known_subjects.json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only-ids", help="comma list of original IDs to restrict to (pilot)")
    a = ap.parse_args()
    cfg = json.load(open(a.config)); ov = json.load(open(a.overrides)) if os.path.exists(a.overrides) else {}
    lock = open("/tmp/broll_sync.lock", "w")
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError: print("another run is active; exiting"); return 0
    try:
        s = Sync(Drive.from_env(), cfg, ov, dry_run=a.dry_run)
        if a.only_ids:
            keep = set(a.only_ids.split(",")); orig = s.discover
            s.discover = lambda c, r: (f for f in orig(c, r) if f["id"] in keep)
        summary = s.run()
    except AuthError as e:
        print(f"::error::AUTH FAILURE (needs human re-consent): {e}"); return 2
    print("SUMMARY " + json.dumps(summary))
    return 0 if summary["status"] == "ok" else 1


sys.exit(main())
