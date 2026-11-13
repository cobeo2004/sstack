"""Lessons store: one Markdown file per scope, one lesson per line. Unknown lines are kept as-is."""
import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sstack_config import ConfigError, git_root, home_dir, load, repo_file
# head_commit and changed_since moved to sstack_wiki; re-exported for sstack-reflect-hook and older callers
from sstack_wiki import changed_since, head_commit, legacy_lessons, match_any as _match, stale, wiki_dir  # noqa: F401

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
    """The lessons file to read: the wiki copy, else the old pre-wiki file while it is the only one."""
    if scope == "global":
        new, old = home_dir() / "wiki" / "lessons.md", legacy_lessons("global", Path())
    else:
        r = root or Path.cwd()  # repo_file, not wiki_dir: a lesson must not land in a throwaway worktree
        new, old = repo_file(r, "wiki/lessons.md"), repo_file(r, "lessons.md")
    return new if new.exists() or not old.exists() else old


def _read(path: Path) -> list:
    return parse(path.read_text()) if path.exists() else parse("# Lessons\n\n")


def _target(path: Path) -> Path:
    """Where an old pre-wiki lessons file moves to."""
    if path == legacy_lessons("global", Path()):
        return home_dir() / "wiki" / "lessons.md"
    return path.parent / "wiki" / "lessons.md"


def _write(path: Path, items: list) -> None:
    """Write `items`; an old .sstack/lessons.md moves into the wiki unless the wiki copy exists."""
    target = _target(path) if path.parent.name == ".sstack" else path
    if target != path and target.exists():
        target = path  # never clobber the wiki copy; lint warns about the pair
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(items))
    if target != path:
        path.unlink(missing_ok=True)  # items were read from it, so no line is lost


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


def applies(lesson: Lesson, files: list[str]) -> bool:
    """Whether the lesson is about any of `files`. No `path` = always; none given = only then."""
    globs = path_globs(lesson)
    return True if not globs else bool(files) and any(_match(f, globs) for f in files)


def is_stale(lesson: Lesson, root: Path | None, _seen: dict | None = None) -> bool:
    """A lesson pinned to paths, learned at a commit, whose paths changed since."""
    return stale(path_globs(lesson), lesson.fields.get("commit"), root, _seen)


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
            for l, stale in select(_read(path), a.paths, root):
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
