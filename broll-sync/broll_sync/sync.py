"""STYLST B-roll sync: individual-file Drive shortcuts into the existing library.

Never moves/edits/deletes originals and never changes sharing. Dedupe is by original file ID against the
shortcuts already in the library (the library is the source of truth); filenames are never used for matching.
"""
import json, re, time, datetime as dt
from .drive import FOLDER, SHORTCUT, DriveError, AuthError, AmbiguousWrite

DEFAULT_EXCLUDE = re.compile(r"(?i)\b(meetings?|hr|legal|payroll|contracts?|invoices?|b-?roll library)\b")


def is_media(f):
    return f["mimeType"].startswith(("image/", "video/"))


def clean(s):
    return re.sub(r"\s+", " ", s.replace("/", "-")).strip()


class Sync:
    def __init__(self, drive, cfg, overrides=None, dry_run=False, log=print, now=None, sleep=time.sleep, previous=None):
        self.d, self.cfg, self.ov = drive, cfg, overrides or {}
        self.dry, self.log, self.sleep = dry_run, log, sleep
        self.exclude = re.compile(cfg["exclude_regex"]) if cfg.get("exclude_regex") else DEFAULT_EXCLUDE
        self.library, self.unsorted = cfg["library_id"], cfg["unsorted_id"]
        self.now = now or (lambda: dt.datetime.now(dt.timezone.utc).isoformat())
        self.rows, self.errors, self.unresolved = [], [], []
        self.lib_folders = set()
        self.previous = previous or {}          # last saved run record, read from state

    # ---- preflight -----------------------------------------------------
    def preflight(self):
        want = self.cfg.get("expected_account")
        if want and hasattr(self.d, "about"):
            got = self.d.about()["user"]["emailAddress"].lower()
            if got != want.lower():
                raise AuthError(f"authorized as {got}, expected {want}")
        for name, fid in (("library", self.library), ("unsorted", self.unsorted)):
            if not self.d.get(fid, "id,capabilities(canAddChildren)").get("capabilities", {}).get("canAddChildren"):
                raise AuthError(f"account cannot add shortcuts to {name} folder")

    # ---- library index -------------------------------------------------
    def library_tree(self):
        subjects, targets = {}, {}
        stack = [self.library]
        while stack:
            fid = stack.pop()
            if fid in self.lib_folders: continue
            self.lib_folders.add(fid)
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

    # ---- discovery -----------------------------------------------------
    def discover(self, creator, root_id):
        stack, seen = [root_id], set()
        while stack:
            fid = stack.pop()
            if fid in seen: continue
            seen.add(fid)
            try:
                kids = self.d.children(fid)
            except DriveError as e:
                self.unresolved.append({"creator": creator, "folder": fid, "error": str(e)[:200]})
                continue
            for k in kids:
                if k["mimeType"] == FOLDER:
                    if not self.exclude.search(k["name"]): stack.append(k["id"])
                elif k["mimeType"] == SHORTCUT:
                    continue
                elif is_media(k):
                    yield k

    # ---- one file ------------------------------------------------------
    def _in_library(self, sc):
        return any(p in self.lib_folders for p in sc.get("parents", []))

    def _existing(self, fid):
        return [s for s in self.d.find_shortcuts(fid) if self._in_library(s)]

    def _handle(self, creator, f, subjects, targets, counts):
        fid = f["id"]
        if fid in targets:
            counts["skipped"] += 1; return
        ov = self.ov.get(fid)
        if ov:
            dest, title, reviewed = self.subject_id(subjects, ov["folder_prefix"]), ov["title"], True
        else:
            dest, title, reviewed = self.unsorted, f"{creator}: {f['name']} (not visually reviewed)", False
        title = clean(title)
        row = {"original_id": fid, "creator": creator, "destination": dest, "title": title,
               "visually_reviewed": reviewed, "scanned_at": self.now()}
        try:
            ex = self._existing(fid)            # re-check right before writing: covers overlapping runs
            if ex:
                row.update(result="already_present", shortcut_id=ex[0]["id"]); targets[fid] = ex[0]["id"]
                counts["skipped"] += 1
            elif self.dry:
                row.update(result="would_create", shortcut_id=None); counts["added"] += 1
            else:
                try:
                    sc = self.d.create_shortcut(title, fid, dest)
                    row["result"] = "created"
                except AmbiguousWrite:          # response lost: look before ever writing again
                    self.sleep(5)
                    ex = self._existing(fid)
                    if not ex: raise
                    sc, row["result"] = ex[0], "created_response_lost_recovered"
                back = self.d.get(sc["id"], "id,name,parents,shortcutDetails,webViewLink")
                if back.get("shortcutDetails", {}).get("targetId") != fid:
                    raise RuntimeError("readback mismatch: shortcut target differs")
                row.update(shortcut_id=back["id"], link=back.get("webViewLink"), readback_parent=back.get("parents"))
                targets[fid] = back["id"]; counts["added"] += 1
        except AuthError:
            raise
        except Exception as e:
            row.update(result="error", error=str(e)[:300]); self.errors.append(row)
        self.rows.append(row)
        # console/CI log is deliberately minimal (no filenames, no creator names); the full row goes to saved state only
        self.log(json.dumps({k: row.get(k) for k in ("original_id", "result", "shortcut_id", "destination")}))

    # ---- runs ----------------------------------------------------------
    def _summary(self, started, counts, targets, mode):
        broken = [] if mode == "pilot" else self.check_broken(targets, {r["original_id"] for r in self.rows})
        failed_before = set(self.previous.get("failed_ids", []))
        failed_now = [r["original_id"] for r in self.errors]
        done_ids = {r["original_id"] for r in self.rows if r["result"] != "error"}
        return {"mode": mode, "dry_run": self.dry, "started": started, "finished": self.now(),
                "added": counts["added"], "skipped_existing": counts["skipped"], "errors": len(self.errors),
                "failed_ids": failed_now, "carried_over_resolved": sorted(failed_before & done_ids),
                "previous_run_started": self.previous.get("started"),
                "unresolved_folders": self.unresolved, "broken_shortcuts": broken,
                "status": "ok" if not (self.errors or self.unresolved or broken) else "partial"}

    def run(self):
        started = self.now(); self.preflight()
        subjects, targets = self.library_tree(); counts = {"added": 0, "skipped": 0}
        for src in self.cfg["sources"]:
            try:
                self.d.get(src["folder_id"], "id")
            except DriveError as e:
                self.unresolved.append({"creator": src["creator"], "folder": src["folder_id"], "error": str(e)[:200]})
                continue
            for f in self.discover(src["creator"], src["folder_id"]):
                self._handle(src["creator"], f, subjects, targets, counts)
        return self._summary(started, counts, targets, "full")

    def run_pilot(self, pilot):
        """Only the files listed in pilot config. No source scan, no other writes."""
        started = self.now(); self.preflight()
        subjects, targets = self.library_tree(); counts = {"added": 0, "skipped": 0}
        for ent in pilot["files"]:
            try:
                f = self.d.get(ent["id"], "id,name,mimeType,trashed")
                if f.get("trashed") or not is_media(f): raise RuntimeError("pilot file is trashed or not photo/video")
            except DriveError as e:
                self.errors.append({"original_id": ent["id"], "result": "error", "error": str(e)[:200]}); continue
            except RuntimeError as e:
                self.errors.append({"original_id": ent["id"], "result": "error", "error": str(e)}); continue
            self._handle(ent["creator"], f, subjects, targets, counts)
        return self._summary(started, counts, targets, "pilot")

    def check_broken(self, targets, just_created):
        broken = []
        for tid, sid in targets.items():
            if tid in just_created: continue
            try:
                if self.d.get(tid, "id,trashed").get("trashed"): broken.append({"shortcut": sid, "target": tid, "why": "trashed"})
            except DriveError as e:
                broken.append({"shortcut": sid, "target": tid, "why": str(e)[:120]})
        return broken
