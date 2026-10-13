#!/usr/bin/env bash
# Commit broll-sync/state/* to the orphan-capable branch `broll-state`. Credentials are never in these files.
set -euo pipefail
git config user.name "broll-sync"; git config user.email "broll-sync@users.noreply.github.com"
rm -rf /tmp/sw; git worktree prune; git fetch -q origin broll-state 2>/dev/null || true
if git rev-parse -q --verify origin/broll-state >/dev/null; then git worktree add -q --detach /tmp/sw origin/broll-state
else git worktree add -q --detach /tmp/sw; git -C /tmp/sw checkout -q --orphan broll-state; git -C /tmp/sw rm -rqf . || true; fi
rm -rf /tmp/sw/state; cp -r broll-sync/state /tmp/sw/state
cd /tmp/sw; git add state
git diff --cached --quiet && { echo "no state change"; exit 0; }
git commit -q -m "run record $(date -u +%FT%TZ)"; git push -q origin HEAD:refs/heads/broll-state
