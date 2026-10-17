#!/usr/bin/env python3
"""audit_dir_guard.py - may a sandboxed audit run write to this directory?

collect_tokens.sh (TOKENSTATS_AUDIT_DIR) copies a freshly built tokens.json,
with a fresh generated_at, into the audit dir before its 98% guard runs. Inside
any checkout of this repository that would hand the next live reconcile a
ledger it trusts, so such a dir is refused.

Directories are compared by identity (device + inode, what `test -ef` does),
never by spelling: the Mac's disk is case-insensitive, so
/Users/maxmohammadi/MAXMONEYCASH/data IS the live data/, and a symlinked
parent spells the same directory differently again. Walking up from the audit
dir, it is refused when any ancestor is

  - this checkout, any worktree of its repository (the live ~/maxmoneycash
    included), their .git, or the shared git dir;
  - ~/maxmoneycash or its .git, even if git cannot list it;
  - any directory holding scripts/collect_tokens.sh (a separate full clone,
    or a copy of this collector);

or when the enclosing git repository's origin is maxmoneycash/maxmoneycash.

Usage: audit_dir_guard.py <audit-dir> <repo-dir>
Exit 0 and print the physical audit dir when it is safe; exit 2 and print
"REFUSED: <reason>" when it is not (any error also exits non-zero).
"""
import os
import pathlib
import subprocess
import sys

ORIGIN_MARK = "maxmoneycash/maxmoneycash"
COLLECTOR = pathlib.Path("scripts") / "collect_tokens.sh"


def git(cwd, *args):
    try:
        out = subprocess.run(["git", "-C", str(cwd), *args],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def protected_dirs(repo):
    repo = pathlib.Path(repo)
    dirs = [repo, repo / ".git"]
    common = git(repo, "rev-parse", "--git-common-dir")
    if common:
        dirs.append(pathlib.Path(common) if os.path.isabs(common) else repo / common)
    for line in git(repo, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            worktree = pathlib.Path(line[len("worktree "):])
            dirs += [worktree, worktree / ".git"]
    live = pathlib.Path.home() / "maxmoneycash"
    dirs += [live, live / ".git"]
    return [d for d in dirs if d.exists()]


def same(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def refusal(audit_dir, repo):
    """Why audit_dir may not be used, or None."""
    target = pathlib.Path(os.path.realpath(audit_dir))
    existing = [a for a in (target, *target.parents) if a.is_dir()]
    protected = protected_dirs(repo)
    for ancestor in existing:
        for p in protected:
            if same(ancestor, p):
                return f"{audit_dir} is inside {p} (same directory as {ancestor})"
        if (ancestor / COLLECTOR).is_file():
            return f"{audit_dir} is inside {ancestor}, which holds a copy of this collector"
    if existing:
        origin = git(existing[0], "config", "--get", "remote.origin.url")
        if ORIGIN_MARK in origin.lower():
            return f"{audit_dir} is inside a clone of {origin}"
    return None


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("REFUSED: usage: audit_dir_guard.py <audit-dir> <repo-dir>")
        return 2
    reason = refusal(args[0], args[1])
    if reason:
        print(f"REFUSED: {reason}")
        return 2
    print(os.path.realpath(args[0]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
