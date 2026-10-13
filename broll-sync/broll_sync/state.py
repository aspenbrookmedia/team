"""Append-only JSONL run records. Tolerates a truncated last line (crash mid-write). No credentials ever stored."""
import json, os


def load(path):
    rows = []
    if not os.path.exists(path): return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try: rows.append(json.loads(line))
            except ValueError: continue   # truncated/corrupt line: skip, keep everything else
    return rows


def append(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a+b") as f:            # a crash may have left a partial line: start a fresh one
        f.seek(0, 2)
        if f.tell():
            f.seek(-1, 2)
            if f.read(1) != b"\n": f.write(b"\n")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, sort_keys=True) + "\n"); f.flush(); os.fsync(f.fileno())


def last_success(runs):
    ok = [r for r in runs if r.get("status") == "ok"]
    return ok[-1] if ok else None
