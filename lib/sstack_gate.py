"""The deterministic gate (docs/spec/gate.md): run the base branch's `verify` commands,
check protected paths and the run's protected manifest, and enforce PR evidence."""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import os
import re
import shlex
import signal
import subprocess
import sys
import tomllib
from pathlib import Path

from sstack_config import git_root, home_dir, trusted
from sstack_route import _kind
from sstack_worktree import base_ref

PROJECT = ".sstack/project.toml"
MANIFEST = "SHA256SUMS"
TIMEOUT = 900
IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
VIDEOS = {".mp4", ".mov", ".webm"}
VISUAL = IMAGES | VIDEOS
DIAGRAM = {".mmd"}
SVG = {".svg"}  # an archify extra: pairs like a visual, never required
SUFFIX = re.compile(r"^(before|after)-(.+)\.([A-Za-z0-9]+)$")


class SetupError(Exception):
    pass


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _base_config(root: Path) -> tuple[str, str, str]:
    """(raw project.toml text, source label, base ref). Never reads the local layer."""
    base = base_ref(root)
    shown = _git(root, "show", f"{base}:{PROJECT}")
    if shown.returncode == 0:
        return shown.stdout, f"base {base} {PROJECT}", base
    path = root / PROJECT
    if path.is_file():
        return path.read_text(), f"working tree {PROJECT} (base {base} has none)", base
    return "", f"none (base {base} and working tree have no {PROJECT})", base


def _parse(text: str, label: str) -> dict:
    try:
        return tomllib.loads(text) if text.strip() else {}
    except tomllib.TOMLDecodeError as e:
        raise SetupError(f"{label}: {e}") from None


def _strings(value, key: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return value
    raise SetupError(f"{key} must be a string or a list of strings")


def _merge_base(root: Path, base: str) -> str:
    r = _git(root, "merge-base", base, "HEAD")
    if r.returncode:
        raise SetupError(f"git merge-base {base} HEAD: {r.stderr.strip()}")
    return r.stdout.strip()


def _changed(root: Path, base_sha: str) -> list[tuple[str, str]]:
    """(path, name-status) against the working tree, including untracked files as added."""
    # -z: literal paths; without it git quotes non-ASCII names and globs never match them
    r = _git(root, "diff", "--name-status", "--no-renames", "-z", base_sha)
    if r.returncode:
        raise SetupError(f"git diff {base_sha}: {r.stderr.strip()}")
    changes: dict[str, str] = {}
    fields = r.stdout.split("\0")
    for status, path in zip(fields[::2], fields[1::2]):
        if path:
            changes[path] = status[:1]
    r = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    if r.returncode:
        raise SetupError(f"git ls-files --others: {r.stderr.strip()}")
    for path in filter(None, r.stdout.split("\0")):
        changes.setdefault(path, "A")
    return sorted(changes.items())


def _protected(changes: list[tuple[str, str]], patterns: list[str]) -> list[str]:
    errors = []
    for path, status in changes:
        if status == "A":
            continue  # added files never break a protected glob
        if any(fnmatch.fnmatch(path, pat) for pat in patterns):
            errors.append(f"{path}: protected file {status} against base")
    return errors


def _manifest_command(protected: Path) -> str:
    """A portable command that records the backups in shasum format."""
    d = shlex.quote(str(protected))
    return ("(cd %s && find . -type f ! -name %s ! -name mode -print | sed 's#^./##' | sort | "
            "while IFS= read -r f; do printf '%%s  %%s\\n' "
            "\"$(shasum -a 256 \"$f\" | cut -d' ' -f1)\" \"$f\"; done > %s)"
            % (d, MANIFEST, MANIFEST))


def _manifest(run: Path, root: Path) -> tuple[list[str], str]:
    protected = run / "protected"
    if not protected.is_dir():
        return [], "nothing to check"
    manifest = protected / MANIFEST
    if not manifest.is_file():
        backups = [p for p in protected.rglob("*")
                   if p.is_file() and p.name not in (MANIFEST, "mode")]
        if backups:
            return [f"protected backups have no {MANIFEST}; write it with: {_manifest_command(protected)}"], "FAIL"
        return [], "nothing to check"
    errors = []
    checked = 0
    for n, raw in enumerate(manifest.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            errors.append(f"{manifest}:{n}: expected '<sha256>  <repo-relative path>'")
            continue
        digest, rel = parts[0].lower(), parts[1].strip()
        if rel.startswith("*"):  # shasum's binary marker
            rel = rel[1:]
        rel_path = Path(rel)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            errors.append(f"{manifest}:{n}: path must stay inside the repo: {rel}")
            continue
        path = root / rel_path
        if not path.resolve().is_relative_to(root.resolve()):
            errors.append(f"{rel}: resolves outside the repo")
            continue
        if not path.is_file():
            errors.append(f"{rel}: protected file is missing")
            continue
        if _sha256(path) != digest:
            errors.append(f"{rel}: hash differs from {manifest}")
        checked += 1
    return errors, ("ok (%d path(s))" % checked if not errors else "FAIL")


def _run_verify(root: Path, commands: list[str]) -> tuple[bool, str, list[str], str]:
    chunks: list[str] = []
    if not commands:
        return True, "no commands", [], "(no verify commands)\n"
    for n, cmd in enumerate(commands, 1):
        chunks.append(f"$ {cmd}\n")
        try:
            p = subprocess.Popen(["sh", "-c", cmd], cwd=root, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, start_new_session=True)
        except OSError as e:
            chunks.append(f"[could not start: {e}]\n")
            return (False, f"FAIL command {n} (could not start)",
                    [f"verify command {n} could not start: {e}"], "".join(chunks))
        timed_out = False
        try:
            out, err = p.communicate(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, err = p.communicate()
        chunks += [x if not x or x.endswith("\n") else x + "\n" for x in (out, err)]
        if timed_out:
            chunks.append(f"[timed out after {TIMEOUT}s]\n")
            return (False, f"FAIL command {n} timed out",
                    [f"verify command {n} timed out after {TIMEOUT}s: {cmd}"], "".join(chunks))
        if p.returncode:
            chunks.append(f"[exit {p.returncode}]\n")
            return (False, f"FAIL command {n} (exit {p.returncode})",
                    [f"verify command {n} failed (exit {p.returncode}): {cmd}"], "".join(chunks))
        chunks.append("[exit 0]\n")
    return True, f"{len(commands)} command(s) passed", [], "".join(chunks)


def _reason(path: Path) -> str:
    return " ".join(path.read_text().split()) if path.is_file() else ""


def _is_test(path: str) -> bool:
    p = Path(path)
    name = p.name
    return ("tests" in p.parts or "test" in p.parts or "__tests__" in p.parts
            or name.startswith("test_") or name.endswith("_test.py")
            or ".test." in name or ".spec." in name)


def _media(media: Path) -> list[tuple[str, str, str, str]]:
    """(side, key, kind, name) for before-/after- files the PR tool can show."""
    if not media.is_dir():
        return []
    out = []
    for p in sorted(media.iterdir(), key=lambda x: x.name):
        if not p.is_file() or not (m := SUFFIX.match(p.name)):
            continue
        ext = "." + m.group(3).lower()
        if ext in DIAGRAM:
            kind = "diagram"
        elif ext in VISUAL | SVG:
            kind = "visual"
        else:
            continue
        out.append((m.group(1), m.group(2), kind, p.name))
    return out


def _evidence(run: Path, changes: list[tuple[str, str]]) -> tuple[list[str], str]:
    media = run / "media"
    if (media / "skip.md").is_file():
        reason = _reason(media / "skip.md") or "(no reason given)"
        return [], f"MEDIA WAIVED: {reason}"

    need_visual = need_diagram = False
    for path, _ in changes:
        if _is_test(path):
            continue
        kind = _kind(path)
        need_visual = need_visual or kind in ("frontend", "mobile")
        need_diagram = need_diagram or kind in ("backend", "security")

    items = _media(media)
    after = [(key, kind, name) for side, key, kind, name in items if side == "after"]
    errors = []
    if need_diagram and not any(kind == "diagram" for _, kind, _ in after):
        errors.append("backend/security change needs an after-*.mmd diagram")
    if need_visual and not any(kind == "visual" and Path(name).suffix.lower() in VISUAL
                               for _, kind, name in after):
        errors.append("frontend/mobile change needs an after-* image or video")

    reason = _reason(media / "no-before.md")
    if not reason:
        before = {(key, kind) for side, key, kind, _ in items if side == "before"}
        missing = sorted(f"after-{key} ({kind})" for key, kind, _ in after
                         if (key, kind) not in before)
        if missing:
            errors.append("every after-* needs a matching before-* "
                          "(or media/no-before.md): " + ", ".join(missing))

    if errors:
        summary = "FAIL"
    elif not need_visual and not need_diagram:
        summary = "nothing owed"
    else:
        summary = "ok"
    if reason:
        summary += f"; no-before: {reason}"
    return errors, summary


def _tail(log: str, limit: int = 6000) -> str:
    if len(log) <= limit:
        return log
    cut = log[-limit:]
    return cut.split("\n", 1)[-1]


def _verdict(config: str, changes: list[tuple[str, str]], base_sha: str, verify: str,
             run: str | None, errors: list[str], log: str) -> str:
    status = "FAIL" if errors else "PASS"
    bullets = [
        f"Config: {config}",
        f"Diff: {len(changes)} changed file(s) against {base_sha[:12]}",
        f"Verify: {verify}",
    ]
    if run:
        bullets.append(f"Run: {run}")
    out = [f"GATE: {status}", "", "## Summary", ""]
    out += [f"- {b}" for b in bullets]
    if errors:
        out += ["", "## Details", ""] + [f"- {e}" for e in errors]
    out += ["", "## Log", "", "```text", _tail(log).rstrip() or "(empty)", "```"]
    return "\n".join(out) + "\n"


def _next(gate: Path) -> int:
    nums = [int(m[1]) for p in gate.glob("*.md") if (m := re.fullmatch(r"(\d+)(?:-pr)?\.md", p.name))]
    return max(nums, default=0) + 1


def _write(run: Path, pr: bool, verdict: str, log: str) -> None:
    gate = run / "gate"
    gate.mkdir(parents=True, exist_ok=True)
    n = _next(gate)
    stem = f"{n}{'-pr' if pr else ''}"
    (gate / f"{stem}.md").write_text(verdict)
    (gate / f"{stem}.log").write_text(log)


def _evaluate(run: Path | None, pr: bool) -> tuple[int, str, str]:
    root = git_root(Path.cwd())
    if root is None:
        raise SetupError("not a git repository")
    if not trusted(root):
        raise SetupError(f"{root} is not in {home_dir() / 'repos.txt'}")
    if pr and run is None:
        raise SetupError("--pr needs --run")

    config_text, config_label, base = _base_config(root)
    config = _parse(config_text, config_label)
    verify_cmds = _strings(config.get("verify"), "verify")
    protected = _strings(config.get("protected"), "protected") + [PROJECT]
    base_sha = _merge_base(root, base)
    ok, verify_label, verify_errors, log = _run_verify(root, verify_cmds)
    changes = _changed(root, base_sha)  # after verify, so files it rewrites count too
    errors = _protected(changes, protected) + verify_errors
    run_label = None
    if run is not None:
        manifest_errors, manifest_label = _manifest(run, root)
        errors += manifest_errors
        parts = [f"protected {manifest_label}"]
        if pr:
            evidence_errors, evidence_label = _evidence(run, changes)
            errors += evidence_errors
            parts.append(f"evidence {evidence_label}")
        run_label = "; ".join(parts)

    verdict = _verdict(config_label, changes, base_sha, verify_label, run_label, errors, log)
    return (1 if errors else 0), verdict, log


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sstack-gate",
                                 description="Run the repo's base verify commands and write a gate verdict.")
    ap.add_argument("--run", type=Path, metavar="RUN", help="run directory for verdict and log files")
    ap.add_argument("--pr", action="store_true", help="also enforce before/after PR evidence in RUN/media")
    a = ap.parse_args(argv)
    run = a.run.expanduser() if a.run else None
    try:
        code, verdict, log = _evaluate(run, a.pr)
        if run is not None:
            _write(run, a.pr, verdict, log)
    except (SetupError, OSError) as e:
        print(f"sstack-gate: {e}", file=sys.stderr)
        return 2
    if run is None:
        sys.stdout.write(verdict)
    return code


if __name__ == "__main__":
    sys.exit(main())
