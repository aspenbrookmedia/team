# STYLST B-roll sync

Weekly job that adds one native Drive **shortcut per photo/video** to the existing B-roll Library.
Originals are never moved, edited, deleted or re-shared. Python 3 + `requests`, no other deps.

- `config/sources.json`: library, 00 Unsorted Pile, and creator source folders. Add new contributors here.
- `config/known_subjects.json`: file ID -> subject folder prefix + title, only for footage someone has actually viewed.
  Everything else goes to 00 Unsorted Pile as `Creator: original name (not visually reviewed)`.
- Dedupe: the library's existing shortcuts (`shortcutDetails.targetId`) are the source of truth, so renames, moves
  inside the library, and reruns never create a second shortcut. Filenames are never used for matching.
- Inaccessible folders are reported as `partial` (exit 1), never as success. Revoked auth exits 2.
- Run log: one JSON line per file (original ID, shortcut ID, destination, creator, scan time, result) + a SUMMARY line,
  kept as a GitHub Actions artifact for 90 days.
- Overlap: GitHub `concurrency` group plus a local file lock.

## Run
`GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN` (OAuth, scope `drive`, account founders@stylst.co) as repo secrets.
Manual/pilot: Actions > "STYLST B-roll weekly sync" > Run workflow (dry_run on by default; `only_ids` for a pilot).
Weekly: Sunday 8 AM Pacific (two UTC crons + a Pacific-hour guard for DST). Scheduled runs only act when repo
variable `BROLL_PRODUCTION=true`, set at cutover from ChatGPT's "STYLST B-roll Upkeep".
Tests: `cd broll-sync && python -m unittest discover -s tests -t .`
