import json, unittest
from broll_sync.sync import Sync
from broll_sync.drive import FOLDER, SHORTCUT, DriveError, AuthError


class Fake:
    """In-memory Drive."""
    def __init__(self, files):
        self.f = {x["id"]: dict(x) for x in files}; self.n = 0
    def children(self, fid):
        if self.f.get(fid, {}).get("denied"): raise DriveError(404, "not found")
        return [x for x in self.f.values() if fid in x.get("parents", [])]
    def get(self, fid, fields=""):
        if fid not in self.f or self.f[fid].get("denied"): raise DriveError(404, "nf")
        return self.f[fid]
    def create_shortcut(self, name, target, parent):
        self.n += 1; i = f"sc{self.n}"
        self.f[i] = {"id": i, "name": name, "mimeType": SHORTCUT, "parents": [parent], "shortcutDetails": {"targetId": target}}
        return self.f[i]


def folder(i, n, p=None): return {"id": i, "name": n, "mimeType": FOLDER, "parents": [p] if p else []}
def media(i, n, p, mt="image/jpeg"): return {"id": i, "name": n, "mimeType": mt, "parents": [p]}

CFG = {"library_id": "LIB", "unsorted_id": "UNS", "exclude_regex": "(?i)meetings?",
       "sources": [{"creator": "Grace", "folder_id": "GS"}, {"creator": "Marchel", "folder_id": "MS"}]}
OV = {"g1": {"folder_prefix": "03 Closet", "title": "Grace: cream sweater dress by Christmas tree (photo)"}}


def world():
    return Fake([folder("LIB", "B-roll Library"), folder("UNS", "00 Unsorted Pile", "LIB"),
                 folder("CL", "03 Closet, Outfits, Trying On, Shopping", "LIB"),
                 folder("GS", "Grace B-roll"), media("g1", "IMG.jpeg", "GS"),
                 folder("MS", "Marchel B-roll"), media("m1", "IMG_4174.MOV", "MS", "video/quicktime"),
                 {"id": "doc", "name": "notes", "mimeType": "application/pdf", "parents": ["MS"]},
                 folder("nest", "Raw 2026", "MS"), media("m2", "deep.mov", "nest", "video/quicktime"),
                 folder("mt", "Meetings", "MS"), media("secret", "rec.mov", "mt", "video/quicktime")])


class T(unittest.TestCase):
    def run_sync(self, d, **kw):
        return Sync(d, CFG, OV, log=lambda *_: None, **kw)

    def test_pilot_titles_and_destinations(self):
        d = world(); s = self.run_sync(d); r = s.run()
        by = {x["original_id"]: x for x in s.rows}
        self.assertEqual(by["g1"]["title"], "Grace: cream sweater dress by Christmas tree (photo)")
        self.assertEqual(by["g1"]["destination"], "CL")
        self.assertEqual(by["m1"]["title"], "Marchel: IMG_4174.MOV (not visually reviewed)")
        self.assertEqual(by["m1"]["destination"], "UNS")
        self.assertIn("m2", by)            # nested discovered
        self.assertNotIn("secret", by)     # Meetings excluded
        self.assertNotIn("doc", by)        # non-media ignored
        self.assertEqual(r["added"], 3)

    def test_rerun_zero_duplicates(self):
        d = world(); self.run_sync(d).run()
        r = self.run_sync(d).run()
        self.assertEqual(r["added"], 0); self.assertEqual(r["skipped_existing"], 3)

    def test_dedupe_ignores_filename(self):
        d = world(); self.run_sync(d).run()
        for x in d.f.values():
            if x["mimeType"] == SHORTCUT: x["name"] = "renamed by human"
        self.assertEqual(self.run_sync(d).run()["added"], 0)

    def test_inaccessible_source_is_failure_not_success(self):
        d = world(); d.f["GS"]["denied"] = True
        r = self.run_sync(d).run()
        self.assertEqual(r["status"], "partial"); self.assertEqual(len(r["unresolved_folders"]), 1)

    def test_create_error_recorded_and_retried(self):
        d = world(); orig = d.create_shortcut; calls = {"n": 0}
        def flaky(*a):
            calls["n"] += 1
            if calls["n"] == 1: raise DriveError(500, "boom")
            return orig(*a)
        d.create_shortcut = flaky
        r = self.run_sync(d).run(); self.assertEqual(r["errors"], 1); self.assertEqual(r["status"], "partial")
        d.create_shortcut = orig
        self.assertEqual(self.run_sync(d).run()["added"], 1)   # only the failed one

    def test_dry_run_creates_nothing(self):
        d = world(); self.run_sync(d, dry_run=True).run()
        self.assertFalse([x for x in d.f.values() if x["mimeType"] == SHORTCUT])

    def test_auth_error_propagates(self):
        d = world()
        def bad(*a): raise AuthError("revoked")
        d.create_shortcut = bad
        with self.assertRaises(AuthError): self.run_sync(d).run()

if __name__ == "__main__": unittest.main()
