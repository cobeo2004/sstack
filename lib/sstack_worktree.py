"""Worktree preflight. `status`: where this checkout stands and which gitignored entries
the primary checkout has that this one lacks. `copy`: copy only the files the primary's
`.worktreeinclude` (gitignore syntax) names, never overwriting. Read-only except `copy`."""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def git(cwd, *args, check=True, stdin=None) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          check=check, input=stdin).stdout.strip()


def zlist(cwd, *args) -> list[str]:
    # -z: names come back raw, not C-quoted (café, spaces, quotes).
    return [p for p in git(cwd, *args, "-z").split("\0") if p]


def primary_of(cwd: Path) -> Path:
    # First `worktree` line of the porcelain list is always the main checkout.
    return Path(git(cwd, "worktree", "list", "--porcelain").split("\n")[0].split(" ", 1)[1])


def ignored(root: Path) -> set[str]:
    # --directory collapses an ignored dir (node_modules/) to one entry ending in "/".
    return set(zlist(root, "ls-files", "--others", "--ignored", "--exclude-standard", "--directory"))


def included(primary: Path) -> tuple[list[str], list[str]]:
    """(files to copy, skipped entries). Only gitignored regular files qualify: a
    directory pattern (node_modules/) is reinstalled, not copied; symlinks are skipped."""
    inc = primary / ".worktreeinclude"
    if not inc.is_file():
        return [], []
    hits = zlist(primary, "ls-files", "--others", "--ignored", "--directory",
                 f"--exclude-from={inc}")
    dirs = [h for h in hits if h.endswith("/")]
    cand = [h for h in hits if not h.endswith("/")]
    ign = set(git(primary, "check-ignore", "-z", "--stdin", check=False,
                  stdin="\0".join(cand)).split("\0")) if cand else set()
    files, skipped = [], [f"{d} (directory: reinstall, don't copy)" for d in dirs]
    for c in sorted(cand):
        if c not in ign:
            skipped.append(f"{c} (not gitignored)")
        elif (primary / c).is_symlink() or not (primary / c).is_file():
            skipped.append(f"{c} (symlink or not a regular file)")
        else:
            files.append(c)
    return files, skipped


def base_ref(root: Path) -> str:
    for ref in ("origin/HEAD", "main", "master"):
        if git(root, "rev-parse", "--verify", "-q", ref, check=False):
            return git(root, "rev-parse", "--abbrev-ref", ref) if ref == "origin/HEAD" else ref
    return "main"


def status(root: Path) -> dict:
    primary = primary_of(root)
    s = {"path": str(root), "primary": str(primary), "linked": root != primary,
         "branch": git(root, "branch", "--show-current") or "(detached)",
         "head": git(root, "rev-parse", "--short", "HEAD"),
         "dirty": len([l for l in git(root, "status", "--porcelain").split("\n") if l])}
    base = base_ref(root)
    try:
        behind, ahead = git(root, "rev-list", "--left-right", "--count", f"{base}...HEAD").split()
        s["base"] = f"{base} (behind {behind}, ahead {ahead}, as of the last fetch)"
    except subprocess.CalledProcessError:
        s["base"] = f"{base} (not found)"
    if s["linked"]:
        missing = sorted(ignored(primary) - ignored(root))
        s["missing_files"] = [m for m in missing if not m.endswith("/")]
        s["missing_dirs"] = [m for m in missing if m.endswith("/")]
        files, skipped = included(primary)
        s["copyable"] = [f for f in files if not os.path.lexists(root / f)]
        s["include_skipped"] = skipped
    return s


def copy(root: Path, dry: bool) -> list[str]:
    primary = primary_of(root)
    if root == primary:
        raise SystemExit("sstack-worktree: this is the primary checkout; nothing to copy")
    files, skipped = included(primary)
    lines = [f"skipped  {s}" for s in skipped]
    for rel in files:
        dest = root / rel
        if os.path.lexists(dest):
            lines.append(f"exists  {rel}")
            continue
        lines.append(f"{'would copy' if dry else 'copied'}  {rel}")
        if not dry:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(primary / rel, dest)
    return lines or ["nothing to copy (no .worktreeinclude in the primary, or it matches nothing)"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="sstack-worktree")
    ap.add_argument("cmd", nargs="?", default="status", choices=["status", "copy"])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    try:
        root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel"))
    except subprocess.CalledProcessError:
        print("sstack-worktree: not a git repository", file=sys.stderr)
        return 1
    if a.cmd == "copy":
        print("\n".join(copy(root, a.dry_run)))
        return 0
    for k, v in status(root).items():
        print(f"{k}: {', '.join(v) if isinstance(v, list) else v}" if v != [] else f"{k}: none")
    return 0
