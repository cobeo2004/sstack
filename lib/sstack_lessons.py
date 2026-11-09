"""Lessons store: one Markdown file per scope, one lesson per line. Unknown lines are kept as-is."""
import argparse
import fnmatch
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sstack_config import ConfigError, git_root, load, repo_file

LINE = re.compile(r"^- \[(pending|accepted|encoded)\] seen=(\d+) id=(\S+) \| (.*)$")
STATUSES = ("pending", "accepted", "encoded")


@dataclass
class Lesson:
    id: str
    status: str
    seen: int
    text: str
    fields: dict[str, str] = field(default_factory=dict)

    def line(self) -> str:
        extra = "".join(f" | {k}: {v}" for k, v in self.fields.items())
        return f"- [{self.status}] seen={self.seen} id={self.id} | {self.text}{extra}"


def _parse_line(line: str) -> "Lesson | str":
    m = LINE.match(line)
    if not m:
        return line
    parts = m.group(4).split(" | ")
    fields = {}
    for p in parts[1:]:
        k, sep, v = p.partition(": ")
        if not sep:
            return line  # not our grammar; keep verbatim
        fields[k] = v
    return Lesson(m.group(3), m.group(1), int(m.group(2)), parts[0], fields)


def parse(text: str) -> list["Lesson | str"]:
    return [_parse_line(l) for l in text.split("\n")]


def render(items: list["Lesson | str"]) -> str:
    return "\n".join(i.line() if isinstance(i, Lesson) else i for i in items)


def lessons_path(scope: str, root: Path | None) -> Path:
    if scope == "global":
        return Path.home() / ".sstack" / "lessons.md"
    return repo_file(root or Path.cwd(), "lessons.md")


def _read(path: Path) -> list:
    return parse(path.read_text()) if path.exists() else parse("# Lessons\n\n")


def _write(path: Path, items: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(items))


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def _clean(s: str) -> str:
    return " ".join(s.split()).replace(" | ", " / ")  # keep the line grammar intact


def _lessons(items):
    return [i for i in items if isinstance(i, Lesson)]


def path_globs(lesson: Lesson) -> list[str]:
    """The lesson's path globs (`path: a, b`), [] when it is about no particular file."""
    # ponytail: ", " separates globs so `[a,b]` survives; a glob containing ", " would split
    return [p.strip() for p in lesson.fields.get("path", "").split(", ") if p.strip()]


def _match(f: str, pats: list[str]) -> bool:
    return any(fnmatch.fnmatch(f, p) for p in pats)  # `*` crosses `/`, as in sstack_route


def applies(lesson: Lesson, files: list[str]) -> bool:
    """Whether the lesson is about any of `files`. No `path` = always; none given = only then."""
    globs = path_globs(lesson)
    return True if not globs else bool(files) and any(_match(f, globs) for f in files)


def head_commit(root: Path | None) -> str | None:
    """The short sha a lesson learned now would be pinned to; None outside a repo or before HEAD."""
    if root is None:
        return None
    r = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                       capture_output=True, text=True)
    return (r.stdout.strip() or None) if r.returncode == 0 else None


def changed_since(root: Path | None, commit: str) -> list[str] | None:
    """Files changed between `commit` and HEAD, or None when that commit is unknown."""
    if root is None:
        return None
    r = subprocess.run(["git", "-C", str(root), "diff", "--name-only", "-z", f"{commit}..HEAD"],
                       capture_output=True, text=True)  # -z: literal names, no quoting of non-ASCII
    return [f for f in r.stdout.split("\0") if f] if r.returncode == 0 else None


def is_stale(lesson: Lesson, root: Path | None, _seen: dict | None = None) -> bool:
    """A lesson pinned to paths, learned at a commit, whose paths changed since. Unknown commit
    (or no commit) is not stale: the code cannot contradict what we never saw."""
    globs, commit = path_globs(lesson), lesson.fields.get("commit")
    if not globs or not commit:
        return False
    seen = {} if _seen is None else _seen
    if commit not in seen:
        seen[commit] = changed_since(root, commit)
    return bool(seen[commit]) and any(_match(f, globs) for f in seen[commit])


def select(items: list, files: list[str] | None, root: Path | None) -> list[tuple[Lesson, bool]]:
    """(lesson, stale) for `list`: filtered to `files` when given, all lessons otherwise."""
    seen: dict = {}
    return [(l, is_stale(l, root, seen)) for l in _lessons(items) if files is None or applies(l, files)]


def add(path: Path, text: str, evidence: str | None,
        paths: list[str] | None = None, commit: str | None = None) -> Lesson:
    items = _read(path)
    text = _clean(text)
    evidence = _clean(evidence) if evidence else None
    fresh = {}
    if evidence:
        fresh["evidence"] = evidence
    globs = [g.strip() for g in paths or [] if g.strip()]
    if globs:
        fresh["path"] = ", ".join(globs)
    if commit:
        fresh["commit"] = commit
    for l in _lessons(items):
        if _norm(l.text) == _norm(text):
            return bump(path, l.id, evidence, fresh)
    nums = [int(l.id[1:]) for l in _lessons(items) if re.fullmatch(r"L\d+", l.id)]
    new = Lesson(f"L{max(nums, default=0) + 1}", "pending", 1, text, fresh)
    if items and items[-1] == "":  # keep a trailing newline
        items.insert(len(items) - 1, new)
    else:
        items.append(new)
    _write(path, items)
    return new


def _find(items, lesson_id: str) -> Lesson:
    for l in _lessons(items):
        if l.id == lesson_id:
            return l
    raise KeyError(lesson_id)


def bump(path: Path, lesson_id: str, evidence: str | None,
         fields: dict[str, str] | None = None) -> Lesson:
    """Count one more sighting. Fields the lesson already has win, so a lesson keeps the paths and
    commit it was learned at rather than drifting to wherever it was last seen. A lesson stored
    without `path` applies everywhere, so a later sighting never narrows it to a path."""
    items = _read(path)
    l = _find(items, lesson_id)
    l.seen += 1
    evidence = _clean(evidence) if evidence else None
    if evidence:
        old = l.fields.get("evidence")
        l.fields["evidence"] = f"{old}; {evidence}" if old else evidence
    for k, v in (fields or {}).items():
        if k not in ("evidence", "path") and k not in l.fields:
            l.fields[k] = v
    _write(path, items)
    return l


def set_status(path: Path, lesson_id: str, status: str, encoded: str | None = None) -> Lesson:
    if status not in STATUSES:
        raise ValueError(status)
    items = _read(path)
    l = _find(items, lesson_id)
    l.status = status
    if encoded:
        l.fields["encoded"] = encoded
    _write(path, items)
    return l


def forget(path: Path, lesson_id: str) -> None:
    items = _read(path)
    l = _find(items, lesson_id)
    _write(path, [i for i in items if i is not l])


def accepted(path: Path) -> list[Lesson]:
    return [l for l in _lessons(_read(path)) if l.status == "accepted"] if path.exists() else []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sstack-lessons")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a_add = sub.add_parser("add"); a_add.add_argument("text"); a_add.add_argument("--evidence")
    a_add.add_argument("--path", action="append", dest="paths", metavar="GLOB")
    a_list = sub.add_parser("list"); a_list.add_argument("--status", choices=STATUSES)
    a_list.add_argument("--paths", nargs="+", metavar="FILE")
    for name in ("accept", "forget", "encode"):
        p = sub.add_parser(name); p.add_argument("id")
        if name == "encode":
            p.add_argument("--target", required=True)
    for p in sub.choices.values():
        p.add_argument("--scope", choices=("repo", "global"), default="repo")
    a = ap.parse_args(argv)
    root = git_root(Path.cwd())
    path = lessons_path(a.scope, root)
    try:
        if a.cmd == "add":
            l = add(path, a.text, a.evidence, paths=a.paths, commit=head_commit(root))
            print(f"{l.id} seen={l.seen}")
            if l.status != "encoded" and l.seen >= int(load(root).get("reflect", {}).get("encode_at", 2)):
                print("ENCODE")
        elif a.cmd == "list":
            for l, stale in select(_read(path) if path.exists() else [], a.paths, root):
                if not a.status or l.status == a.status:
                    print(l.line() + (" [stale]" if stale else ""))
        elif a.cmd == "accept":
            set_status(path, a.id, "accepted")
        elif a.cmd == "forget":
            forget(path, a.id)
        elif a.cmd == "encode":
            set_status(path, a.id, "encoded", encoded=a.target)
    except KeyError as e:
        print(f"sstack-lessons: no lesson {e} in {path}", file=sys.stderr)
        return 1
    except ConfigError as e:
        print(f"sstack-lessons: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
