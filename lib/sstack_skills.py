"""Skills a child must use (docs/spec/dispatch.md#skills): the role's `skills`, `[skills.kinds]` for
the work kind, and project `[practices]` globs matching the files, deduped; each name resolved to
the first SKILL.md on the skill path. Doc paths and URLs pass through as "read" links, plus repo
sstack wiki pages whose `paths` match the files."""
import fnmatch
import os
import sys
from pathlib import Path

import sstack_wiki as W

SSTACK_SKILLS = Path(__file__).resolve().parent.parent / "skills"
# Harness skill dirs; a harness file's `skill_dirs` replaces its entry. Kept here, not in
# the template's harnesses/*.toml, so the frozen load() fixtures stay valid.
SKILL_DIRS = {"claude": ["~/.claude/skills", "~/.agents/skills"], "codex": ["~/.codex/skills", "~/.agents/skills"],
              "cursor": ["~/.cursor/skills", "~/.agents/skills"], "pi": ["~/.pi/agent/skills", "~/.agents/skills"]}
REPO_DIRS = (".agents/skills", ".claude/skills", ".pi/skills")


def is_doc(name: str) -> bool:
    return "/" in name or name.endswith(".md")


def names(cfg: dict, role: str, kind: str | None, files: list[str]) -> list[str]:
    out = list((cfg.get("role", {}).get(role) or {}).get("skills", []))
    out += cfg.get("skills", {}).get("kinds", {}).get(kind, []) if kind else []
    for glob, xs in cfg.get("project", {}).get("practices", {}).items():
        if any(fnmatch.fnmatch(f, glob) for f in files):
            out += xs
    return list(dict.fromkeys(out))


def configured(cfg: dict) -> list[str]:
    """Every name in any role, kind or practice (sstack-doctor)."""
    out = [n for r in cfg.get("role", {}).values() for n in (r or {}).get("skills", [])]
    out += [n for xs in cfg.get("skills", {}).get("kinds", {}).values() for n in xs]
    out += [n for xs in cfg.get("project", {}).get("practices", {}).values() for n in xs]
    return [n for n in dict.fromkeys(out) if not is_doc(n)]


def path(cfg: dict, root: Path, harnesses: list[str]) -> list[Path]:
    dirs = [d for h in harnesses
            for d in cfg.get("harness", {}).get(h, {}).get("skill_dirs", SKILL_DIRS.get(h, ["~/.agents/skills"]))]
    dirs += [str(root / d) for d in REPO_DIRS] + [str(SSTACK_SKILLS)]
    # a relative dir means the repo's; children run elsewhere, so every path handed out is absolute
    return [(root / Path(d).expanduser()).resolve() for d in dict.fromkeys(dirs)]


def find(name: str, dirs: list[Path]) -> str | None:
    return next((str(d / name / "SKILL.md") for d in dirs if (d / name / "SKILL.md").is_file()), None)


def resolve(cfg: dict, root: Path, role: str, kind: str | None, files: list[str],
            harnesses: list[str], only: list[str] | None = None) -> tuple[list[tuple[str, str]], list[str]]:
    """([(name, absolute SKILL.md or doc link)], [missing names]) in union order. `only`: resolve
    these names instead of the union (a stage variant's own `skills`)."""
    dirs, found, missing = path(cfg, root, harnesses), [], []
    for n in names(cfg, role, kind, files) if only is None else only:
        if is_doc(n):
            found.append((n, n if "://" in n or Path(n).is_absolute() else str(root / n)))
        elif (p := find(n, dirs)):
            found.append((n, p))
        else:
            missing.append(n)
    if only is None:
        have = {os.path.normpath(link) for _, link in found}  # a page [practices] already names isn't listed twice
        found += [(path, link) for path, link in wiki_pages(root, files) if path not in have]
    return found, missing


def wiki_pages(root: Path, files: list[str]) -> list[tuple[str, str]]:
    """Repo sstack wiki pages whose `paths` match the files: [practices] derived from frontmatter.
    The link carries a stale note when those paths changed since the page's `updated`."""
    d = W.wiki_dir("repo", root)
    if not files or not d.is_dir():
        return []
    try:
        loaded = W.load(d)
    except (OSError, UnicodeDecodeError) as e:  # the wiki is optional: never fail a dispatch over it
        print(f"sstack-dispatch: skipping the sstack wiki ({e}); run sstack-wiki lint", file=sys.stderr)
        return []
    pages = {n: p for n, p in loaded.items()
             if p.paths and any(W.match_any(f, p.paths) for f in files)}
    stale = W.stale_names(pages, root)
    return [(str(p.path), str(p.path) + (f" (stale since {p.updated}: trust the code)" if n in stale else ""))
            for n, p in pages.items()]


def section(found: list[tuple[str, str]], missing: list[str]) -> str:
    lines = ["", "", "## Skills to use", "", "Read each before starting."]
    lines += [f"- read: {p}" if is_doc(n) else f"- `{n}`: {p}" for n, p in found]
    lines += [f"- `{n}` not installed — carry on without it" for n in missing]
    return "\n".join(lines) + "\n"


def lines(found: list[tuple[str, str]], missing: list[str]) -> list[str]:
    """stdout lines for --dry-run and the local (exit 3) route."""
    return [f"skills: read {p}" if is_doc(n) else f"skills: {n} {p}" for n, p in found] + \
           [f"missing skill: {n}" for n in missing]
