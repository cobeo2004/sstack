"""Skills a child must use (docs/spec/dispatch.md#skills): the role's `skills`, `[skills.kinds]` for
the work kind, and project `[practices]` globs matching the files, deduped; each name resolved to
the first SKILL.md on the skill path. Doc paths and URLs pass through as "read" links."""
import fnmatch
from pathlib import Path

SSTACK_SKILLS = Path(__file__).resolve().parent.parent / "skills"
# Harness skill dirs; a harness file's `skill_dirs` replaces its entry. Kept here, not in
# defaults/harnesses/*.toml, so the frozen load() fixtures stay valid.
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
    return found, missing


def section(found: list[tuple[str, str]], missing: list[str]) -> str:
    lines = ["", "", "## Skills to use", "", "Read each before starting."]
    lines += [f"- read: {p}" if is_doc(n) else f"- `{n}`: {p}" for n, p in found]
    lines += [f"- `{n}` not installed — carry on without it" for n in missing]
    return "\n".join(lines) + "\n"


def lines(found: list[tuple[str, str]], missing: list[str]) -> list[str]:
    """stdout lines for --dry-run and the local (exit 3) route."""
    return [f"skills: read {p}" if is_doc(n) else f"skills: {n} {p}" for n, p in found] + \
           [f"missing skill: {n}" for n in missing]
