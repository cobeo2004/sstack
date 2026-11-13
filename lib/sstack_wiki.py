"""The sstack wiki: flat, linked Markdown pages in `<repo>/.sstack/wiki/` and `~/.sstack/wiki/`, a
generated `index.md`, backlinks and lint (docs/guide/wiki.md). Also owns the git staleness helpers
`sstack_lessons` uses; this module never imports lessons."""
import argparse
import fnmatch
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sstack_config import _primary, git_root, home_dir


def wiki_dir(scope: str, root: Path | None) -> Path:
    """global: home_dir()/wiki. repo: this checkout's wiki when it holds a page, else the primary's
    when the primary has .sstack/, else this checkout's."""
    if scope == "global":
        return home_dir() / "wiki"
    r = root or Path.cwd()
    own = r / ".sstack" / "wiki"
    if own.is_dir() and any(own.glob("*.md")):
        return own
    p = _primary(r)
    if p != r and (p / ".sstack").is_dir():
        return p / ".sstack" / "wiki"
    return own


def legacy_lessons(scope: str, d: Path) -> Path:
    """Where lessons lived before they moved into the wiki."""
    return Path.home() / ".sstack" / "lessons.md" if scope == "global" else d.parent / "lessons.md"


def match_any(f: str, pats: list[str]) -> bool:
    return any(fnmatch.fnmatch(f, p) for p in pats)  # `*` crosses `/`, as in sstack_route


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


def stale(globs: list[str], commit: str | None, root: Path | None, _seen: dict | None = None) -> bool:
    """Pinned to paths, checked at a commit, and those paths changed since. Unknown commit (or no
    commit) is not stale: the code cannot contradict what we never saw."""
    if not globs or not commit:
        return False
    seen = {} if _seen is None else _seen
    if commit not in seen:
        seen[commit] = changed_since(root, commit)
    return bool(seen[commit]) and any(match_any(f, globs) for f in seen[commit])


LESSONS_SUMMARY = "Imperative rules agents follow, one per line (managed by sstack-lessons)"
_FENCE = re.compile(r"```.*?```", re.S)  # same as tests/test_skills.py::strip_code
_SPAN = re.compile(r"`[^`\n]*`")
_LINK = re.compile(r"\]\(([^)\s]+)\)")
_URL = re.compile(r"^[a-z][a-z0-9+.-]*:")


@dataclass
class Page:
    name: str
    path: Path
    summary: str
    paths: list[str]
    updated: str | None
    has_meta: bool
    lines: int
    text: str
    links: list[str] = field(default_factory=list)  # edges: page names
    problems: list[tuple[str, str]] = field(default_factory=list)  # (raw target, "broken"|"cross-scope")

    @property
    def lessons(self) -> bool:
        return self.name == "lessons"


def parse_page(path: Path) -> Page:
    """Frontmatter is `---` on line 1 up to the next `---` line, `key: value` per line. lessons.md
    has a fixed summary and its frontmatter is never parsed."""
    text = path.read_text()
    rows = text.splitlines()
    page = Page(path.stem, path, "", [], None, False, len(rows), text)
    if page.lessons:
        page.summary = LESSONS_SUMMARY
        return page
    if rows and rows[0] == "---" and "---" in rows[1:]:
        meta = {}
        for row in rows[1:rows.index("---", 1)]:
            k, sep, v = row.partition(": ")
            if sep:
                meta[k.strip()] = v.strip()
        page.has_meta = True
        page.summary = meta.get("summary", "")
        # ponytail: ", " separates globs (as lessons' path_globs) so `[a,b]` survives
        page.paths = [g.strip() for g in meta.get("paths", "").split(", ") if g.strip()]
        page.updated = meta.get("updated") or None
    return page


def link_targets(text: str) -> list[str]:
    """Raw `.md` link targets outside code, minus URLs and pure #fragments."""
    out = []
    for target in _LINK.findall(_SPAN.sub("", _FENCE.sub("", text))):
        if _URL.match(target) or target.startswith("#"):
            continue
        if re.split(r"[#?]", target, maxsplit=1)[0].endswith(".md"):
            out.append(target)
    return out


def _cross_scope(t: Path) -> bool:
    parts = t.parts
    in_home = t.is_relative_to(Path(os.path.normpath(home_dir() / "wiki")))
    return in_home or any(parts[i:i + 2] == (".sstack", "wiki") for i in range(len(parts) - 1))


def load(d: Path) -> dict[str, Page]:
    """Every page in `d` by name (sorted), with links and problems classified lexically: no resolve(),
    so a symlink inside the wiki is judged by where its link text points."""
    d = Path(os.path.normpath(d))
    # a symlinked page is skipped: its text lives outside the wiki
    pages = {p.stem: parse_page(p) for p in sorted(d.glob("*.md")) if p.name != "index.md" and not p.is_symlink()}
    for page in pages.values():
        for raw in link_targets(page.text):
            path = re.split(r"[#?]", raw, maxsplit=1)[0]
            t = Path(os.path.normpath(d / os.path.expanduser(path)))
            if t.parent == d and t.stem in pages:
                if t.stem != page.name and t.stem not in page.links:
                    page.links.append(t.stem)
                continue
            if t == d / "index.md":
                continue
            kind = "broken" if t.is_relative_to(d) else "cross-scope" if _cross_scope(t) else None
            if kind and (raw, kind) not in page.problems:
                page.problems.append((raw, kind))
    return pages


def backlinks(pages: dict[str, Page]) -> dict[str, list[str]]:
    """Page name -> sorted names of the pages linking to it."""
    out: dict[str, list[str]] = {n: [] for n in pages}
    for page in pages.values():
        for target in page.links:
            out[target].append(page.name)
    return {n: sorted(v) for n, v in out.items()}


INDEX_HEAD = ("# Wiki index\n\n"
              "<!-- generated by sstack-wiki index from page summaries; edit the pages, not this file -->\n\n")
_STALE = re.compile(r" \[stale\]$", re.M)
MAX_SUMMARY, MAX_LINES = 120, 150


def stale_names(pages: dict[str, Page], root: Path | None) -> set[str]:
    """Pages whose `paths` changed since `updated`. Global callers pass root=None: never stale."""
    seen: dict = {}
    return {n for n, p in pages.items() if stale(p.paths, p.updated, root, seen)}


def render_index(pages: dict[str, Page], stale: set[str]) -> str:
    return INDEX_HEAD + "".join(
        f"- [{n}]({n}.md) — {p.summary or '(no summary)'}{' [stale]' if n in stale else ''}\n"
        for n, p in sorted(pages.items()))


def lint(d: Path, scope: str, root: Path | None) -> tuple[list[str], list[str]]:
    """(errors, warnings), each `<file>: <msg>` without the ERROR/WARN prefix; nothing when `d` is missing."""
    if not d.is_dir():
        return [], []
    pages = load(d)
    errors, warnings = [], []
    for p in pages.values():
        errors += [f"{p.name}.md: {kind} link {raw}" for raw, kind in p.problems]
    index = d / "index.md"
    want = render_index(pages, stale_names(pages, root if scope == "repo" else None))
    if index.is_file():
        have = index.read_text()
        if _STALE.sub("", have) != _STALE.sub("", want):
            errors.append("index.md: out of sync; run sstack-wiki index")
        elif have != want:
            warnings.append("index.md: stale markers out of date; run sstack-wiki index")
    elif pages:
        errors.append("index.md: out of sync; run sstack-wiki index")
    back = backlinks(pages)
    for p in pages.values():
        if p.lessons:
            continue  # one rule per line, managed by sstack-lessons: no frontmatter, size or orphan checks
        f = f"{p.name}.md"
        if not back[p.name]:
            warnings.append(f"{f}: orphan (no page links here)")
        if len(p.summary) > MAX_SUMMARY:
            warnings.append(f"{f}: summary is {len(p.summary)} chars (max {MAX_SUMMARY})")
        if p.lines > MAX_LINES:
            warnings.append(f"{f}: {p.lines} lines (max {MAX_LINES})")
        if not p.summary:
            warnings.append(f"{f}: no frontmatter summary")
    old = legacy_lessons(scope, d)
    if "lessons" in pages and old.exists():
        warnings.append(f"lessons.md: old lessons file {old} also exists; the wiki copy wins")
    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sstack-wiki")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("index")
    sub.add_parser("backlinks").add_argument("page")
    sub.add_parser("lint")
    for p in sub.choices.values():
        p.add_argument("--scope", choices=("repo", "global"), default="repo")
    a = ap.parse_args(argv)
    root = git_root(Path.cwd())
    d = wiki_dir(a.scope, root)
    sroot = root if a.scope == "repo" else None
    if a.cmd == "index":
        if not d.is_dir():
            print(f"sstack-wiki: no wiki at {d}", file=sys.stderr)
            return 1
        pages = load(d)
        stale_set = stale_names(pages, sroot)
        (d / "index.md").write_text(render_index(pages, stale_set))
        print(f"wrote {d}/index.md ({len(pages)} pages, {len(stale_set)} stale)")
    elif a.cmd == "backlinks":
        name = a.page[:-3] if a.page.endswith(".md") else a.page
        pages = load(d) if d.is_dir() else {}
        if name not in pages:
            print(f"sstack-wiki: no page {a.page} in {d}", file=sys.stderr)
            return 1
        for n in backlinks(pages)[name]:
            print(f"{n}.md")
    else:
        if not d.is_dir():
            print(f"lint: no wiki at {d}")
            return 0
        errors, warnings = lint(d, a.scope, sroot)
        for e in errors:
            print(f"ERROR {e}")
        for w in warnings:
            print(f"WARN {w}")
        print(f"lint: {len(errors)} errors, {len(warnings)} warnings")
        return 1 if errors else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
