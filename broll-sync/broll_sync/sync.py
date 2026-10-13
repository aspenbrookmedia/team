"""Weekly STYLST B-roll sync: individual-file Drive shortcuts into the existing library.

Never moves/edits/deletes originals. Dedupes by original file ID against the shortcuts that
already exist in the library (the library itself is the source of truth), plus a state file.
"""
import json, re, sys, time, datetime as dt
from .drive import FOLDER, SHORTCUT, DriveError, AuthError

MEDIA_PREFIXES = ("image/", "video/")
# Never traverse folders matching these (config can add more).
DEFAULT_EXCLUDE = re.compile(r"(?i)\b(meetings?|hr|legal|payroll|pay|contracts?|invoices?|b-?roll library|final(s)?)\b")


def is_media(f):
    return f["mimeType"].startswith(MEDIA_PREFIXES)


def clean(s):
    return re.sub(r"\s+", " ", s.replace("/", "-")).strip()


class Sync:
    def __init__(self, drive, cfg, overrides=None, dry_run=False, log=print, now=None):
        self.d, self.cfg, self.ov = drive, cfg, overrides or {}
        self.dry, self.log = dry_run, log
        self.exclude = re.compile(cfg["exclude_regex"]) if cfg.get("exclude_regex") else DEFAULT_EXCLUDE
        self.library, self.unsorted = cfg["library_id"], cfg["unsorted_id"]
        self.now = now or (lambda: dt.datetime.now(dt.timezone.utc).isoformat())
        self.rows, self.errors, self.unresolved = [], [], []

    # ---- library index -------------------------------------------------
    def library_tree(self):
        """Return (subject folders {name:id}, set of target IDs already shortcut, in all library folders)."""
        subjects, targets, seen = {}, {}, set()
        stack = [self.library]
        while stack:
            fid = stack.pop()
            if fid in seen: continue
            seen.add(fid)
            for c in self.d.children(fid):
                if c["mimeType"] == FOLDER:
                    if fid == self.library: subjects[c["name"]] = c["id"]
                    stack.append(c["id"])
                elif c["mimeType"] == SHORTCUT:
                    t = c.get("shortcutDetails", {}).get("targetId")
                    if t: targets[t] = c["id"]
        return subjects, targets

    def subject_id(self, subjects, prefix):
        m = [i for n, i in subjects.items() if n.lower().startswith(prefix.lower())]
        if len(m) != 1:
            raise RuntimeError(f"subject folder prefix {prefix!r} matched {len(m)} folders")
        return m[0]

    # ---- source discovery ---------------------------------------------
    def discover(self, creator, root_id):
        """Yield media files under root (recursive). Records unreadable folders instead of hiding them."""
        stack, seen = [root_id], set()
        while stack:
            fid = stack.pop()
            if fid in seen: continue
            seen.add(fid)
            try:
                kids = self.d.children(fid)
            except DriveError as e:
                self.unresolved.append({"creator": creator, "folder": fid, "error": str(e)})
                continue
            for k in kids:
                if k["mimeType"] == FOLDER:
                    if self.exclude.search(k["name"]): continue
                    stack.append(k["id"])
                elif k["mimeType"] == SHORTCUT:
                    continue  # never follow shortcuts (cycles / other people's files)
                elif is_media(k):
                    yield k

    # ---- run -----------------------------------------------------------
    def run(self):
        started = self.now()
        subjects, targets = self.library_tree()
        added = skipped = held = 0
        for src in self.cfg["sources"]:
            creator = src["creator"]
            try:
                self.d.get(src["folder_id"], "id")
            except DriveError as e:
                self.unresolved.append({"creator": creator, "folder": src["folder_id"], "error": str(e)})
                continue
            for f in self.discover(creator, src["folder_id"]):
                fid = f["id"]
                if fid in targets:
                    skipped += 1; continue
                ov = self.ov.get(fid)
                if ov:
                    dest = self.subject_id(subjects, ov["folder_prefix"]); title = ov["title"]; reviewed = True
                else:
                    dest = self.unsorted
                    title = f"{creator}: {f['name']} (not visually reviewed)"; reviewed = False
                row = {"original_id": fid, "creator": creator, "destination": dest, "title": clean(title),
                       "visually_reviewed": reviewed, "scanned_at": self.now()}
                try:
                    if self.dry:
                        row.update(result="would_create", shortcut_id=None)
                    else:
                        sc = self.d.create_shortcut(clean(title), fid, dest)
                        if sc.get("shortcutDetails", {}).get("targetId") != fid:
                            raise RuntimeError("readback mismatch: shortcut target differs")
                        row.update(result="created", shortcut_id=sc["id"]); targets[fid] = sc["id"]
                    added += 1
                except AuthError:
                    raise
                except Exception as e:  # keep going; recorded and retried next run
                    row.update(result="error", error=str(e)); self.errors.append(row)
                self.rows.append(row)
                self.log(json.dumps(row))
        return {"started": started, "finished": self.now(), "added": added, "skipped_existing": skipped,
                "held": held, "errors": len(self.errors), "unresolved_folders": self.unresolved,
                "status": "ok" if not self.errors and not self.unresolved else "partial"}
