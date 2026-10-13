import json, os, tempfile, unittest
from broll_sync.sync import Sync
from broll_sync.drive import FOLDER, SHORTCUT, DriveError, AuthError, AmbiguousWrite
from broll_sync import state


class Fake:
    def __init__(self, files, email="founders@stylst.co"):
        self.f = {x["id"]: dict(x) for x in files}; self.n = 0; self.email = email
    def about(self): return {"user": {"emailAddress": self.email}}
    def children(self, fid):
        if self.f.get(fid, {}).get("denied"): raise DriveError(404, "not found")
        return [x for x in self.f.values() if fid in x.get("parents", []) and not x.get("trashed")]
    def get(self, fid, fields=""):
        x = self.f.get(fid)
        if not x or x.get("denied"): raise DriveError(404, "nf")
        return {**x, "capabilities": {"canAddChildren": x.get("nowrite") is None}}
    def find_shortcuts(self, target):
        return [x for x in self.f.values() if x["mimeType"] == SHORTCUT and x["shortcutDetails"]["targetId"] == target]
    def create_shortcut(self, name, target, parent):
        self.n += 1; i = f"sc{self.n}"
        self.f[i] = {"id": i, "name": name, "mimeType": SHORTCUT, "parents": [parent],
                     "shortcutDetails": {"targetId": target}, "webViewLink": f"https://drive/{i}"}
        return self.f[i]
    def shortcuts(self): return [x for x in self.f.values() if x["mimeType"] == SHORTCUT]


def folder(i, n, p=None): return {"id": i, "name": n, "mimeType": FOLDER, "parents": [p] if p else []}
def media(i, n, p, mt="image/jpeg"): return {"id": i, "name": n, "mimeType": mt, "parents": [p]}

CFG = {"library_id": "LIB", "unsorted_id": "UNS", "exclude_regex": "(?i)meetings?", "expected_account": "founders@stylst.co",
       "sources": [{"creator": "Grace", "folder_id": "GS"}, {"creator": "Marchel", "folder_id": "MS"}]}
OV = {"g1": {"folder_prefix": "03 Closet", "title": "Grace: cream sweater dress by Christmas tree (photo)"}}
PILOT = {"files": [{"id": "g1", "creator": "Grace"}, {"id": "m1", "creator": "Marchel"}]}


def world():
    return Fake([folder("LIB", "B-roll Library"), folder("UNS", "00 Unsorted Pile", "LIB"),
                 folder("CL", "03 Closet, Outfits, Trying On, Shopping", "LIB"),
                 folder("GS", "Grace B-roll"), media("g1", "IMG.jpeg", "GS"),
                 folder("MS", "Marchel B-roll"), media("m1", "IMG_4174.MOV", "MS", "video/quicktime"),
                 {"id": "doc", "name": "notes", "mimeType": "application/pdf", "parents": ["MS"]},
                 folder("nest", "Raw 2026", "MS"), media("m2", "deep.mov", "nest", "video/quicktime"),
                 folder("mt", "Meetings", "MS"), media("secret", "rec.mov", "mt", "video/quicktime")])


def S(d, **kw): return Sync(d, CFG, OV, log=lambda *_: None, sleep=lambda *_: None, **kw)


class Core(unittest.TestCase):
    def test_titles_destinations_nested_exclusions(self):
        d = world(); s = S(d); r = s.run(); by = {x["original_id"]: x for x in s.rows}
        self.assertEqual(by["g1"]["title"], "Grace: cream sweater dress by Christmas tree (photo)")
        self.assertEqual(by["g1"]["destination"], "CL")
        self.assertEqual(by["m1"]["title"], "Marchel: IMG_4174.MOV (not visually reviewed)")
        self.assertEqual(by["m1"]["destination"], "UNS")
        self.assertIn("m2", by); self.assertNotIn("secret", by); self.assertNotIn("doc", by)
        self.assertEqual(r["added"], 3)

    def test_rerun_zero_duplicates_and_rename_safe(self):
        d = world(); S(d).run()
        for x in d.shortcuts(): x["name"] = "renamed"
        r = S(d).run(); self.assertEqual(r["added"], 0); self.assertEqual(len(d.shortcuts()), 3)

    def test_inaccessible_source_is_partial(self):
        d = world(); d.f["GS"]["denied"] = True
        r = S(d).run(); self.assertEqual(r["status"], "partial"); self.assertEqual(len(r["unresolved_folders"]), 1)

    def test_broken_shortcut_reported(self):
        d = world(); S(d).run(); d.f["m2"]["denied"] = True; d.f["m1"]["trashed"] = True
        r = S(d).run(); self.assertEqual(r["status"], "partial"); self.assertEqual(len(r["broken_shortcuts"]), 2)

    def test_dry_run_creates_nothing(self):
        d = world(); r = S(d, dry_run=True).run()
        self.assertEqual(len(d.shortcuts()), 0); self.assertEqual(r["added"], 3)

    def test_wrong_account_stops_everything(self):
        d = world(); d.email = "someone@else.com"
        with self.assertRaises(AuthError): S(d).run()
        self.assertEqual(len(d.shortcuts()), 0)

    def test_no_write_access_stops_everything(self):
        d = world(); d.f["UNS"]["nowrite"] = True
        with self.assertRaises(AuthError): S(d).run()


class Failures(unittest.TestCase):
    def test_lost_response_then_retry_makes_no_duplicate(self):
        d = world(); real = d.create_shortcut; calls = {"n": 0}
        def lossy(*a):
            calls["n"] += 1; real(*a)                       # write happens ...
            if calls["n"] == 1: raise AmbiguousWrite("timeout")   # ... response is lost
            return d.f[f"sc{d.n}"]
        d.create_shortcut = lossy
        s = S(d); r = s.run()
        self.assertEqual(len(d.shortcuts()), 3, "lost response must not duplicate")
        self.assertEqual(r["status"], "ok")
        self.assertEqual([x["result"] for x in s.rows].count("created_response_lost_recovered"), 1)
        self.assertEqual(S(d).run()["added"], 0)

    def test_lost_response_with_nothing_written_is_error_then_next_run_creates_once(self):
        d = world(); real = d.create_shortcut; st = {"n": 0}
        def fail_before_write(*a):
            st["n"] += 1
            if st["n"] == 1: raise AmbiguousWrite("timeout")
            return real(*a)
        d.create_shortcut = fail_before_write
        r = S(d).run(); self.assertEqual(r["errors"], 1); self.assertEqual(r["status"], "partial")
        r2 = S(d, previous=r).run()
        self.assertEqual(len(d.shortcuts()), 3); self.assertEqual(r2["carried_over_resolved"], r["failed_ids"])

    def test_overlapping_runs_no_duplicate(self):
        d = world(); a = S(d); real = d.find_shortcuts; fired = {"done": False}
        def find_then_other_run_first(t):
            if not fired["done"]:
                fired["done"] = True; S(d).run()        # run B completes while A is mid-flight
            return real(t)
        d.find_shortcuts = find_then_other_run_first
        a.run(); self.assertEqual(len(d.shortcuts()), 3)

    def test_auth_error_propagates(self):
        d = world()
        def bad(*a): raise AuthError("revoked")
        d.create_shortcut = bad
        with self.assertRaises(AuthError): S(d).run()


class Pilot(unittest.TestCase):
    def test_pilot_touches_only_two_files(self):
        d = world(); r = S(d).run_pilot(PILOT)
        self.assertEqual({x["shortcutDetails"]["targetId"] for x in d.shortcuts()}, {"g1", "m1"})
        self.assertEqual(r["mode"], "pilot"); self.assertEqual(r["added"], 2)
        r2 = S(d).run_pilot(PILOT); self.assertEqual(r2["added"], 0); self.assertEqual(len(d.shortcuts()), 2)

    def test_pilot_dry_run_read_only(self):
        d = world(); r = S(d, dry_run=True).run_pilot(PILOT)
        self.assertEqual(len(d.shortcuts()), 0); self.assertEqual(r["added"], 2)

    def test_pilot_skips_existing_shortcut_made_elsewhere_in_library(self):
        d = world(); d.create_shortcut("manual", "g1", "CL")
        r = S(d).run_pilot(PILOT); self.assertEqual(r["added"], 1); self.assertEqual(len(d.shortcuts()), 2)

    def test_pilot_missing_file_is_failure(self):
        d = world(); del d.f["m1"]
        r = S(d).run_pilot(PILOT); self.assertEqual(r["status"], "partial")


class State(unittest.TestCase):
    def test_roundtrip_and_next_run_reads_previous(self):
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "runs.jsonl"); d = world()
            r1 = S(d).run(); state.append(p, r1)
            prev = state.load(p)[-1]; r2 = S(d, previous=prev).run()
            self.assertEqual(r2["previous_run_started"], r1["started"])

    def test_truncated_last_line_recovers(self):
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "runs.jsonl")
            state.append(p, {"status": "ok", "started": "a"}); state.append(p, {"status": "partial", "started": "b"})
            open(p, "a").write('{"status": "ok", "star')       # crash mid-write
            rows = state.load(p); self.assertEqual(len(rows), 2)
            self.assertEqual(state.last_success(rows)["started"], "a")
            state.append(p, {"status": "ok", "started": "c"}); self.assertEqual(state.last_success(state.load(p))["started"], "c")

    def test_partial_never_counts_as_success(self):
        d = world(); d.f["GS"]["denied"] = True; r = S(d).run()
        self.assertIsNone(state.last_success([r]))

    def test_no_credentials_in_records(self):
        d = world(); s = S(d); r = s.run(); blob = json.dumps([r, s.rows]).lower()
        for w in ("token", "secret", "client_id", "refresh"): self.assertNotIn(w, blob)

if __name__ == "__main__": unittest.main()
