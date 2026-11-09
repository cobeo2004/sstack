"""`sstack-config migrate` and `show` (docs/spec/config.md)."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

import sstack_config as C

KEY = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*=")
NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
SPLIT = {"harness": "harnesses", "role": "roles", "tier": "tiers"}
KIND_OF = {"harnesses": "harness", "roles": "role", "tiers": "tier"}
MODE = {"thread": "ade-cli", "auto": "auto", "headless": "headless", "local": "local"}
SHOW_KINDS = ("harnesses", "roles", "tiers", "ades")
GITIGNORE = (".sstack/local/", ".sstack/config.local.toml.bak")
T3_PROVIDER_NOTE = "provider ids live in ades/t3.toml [providers]"
T3_CLI_NOTE = "thread start is [cli] in defaults/ades/t3.toml; override with ades/t3.toml"
PROJECT_HOME_NOTE = "project is repo-only; dropped [project] from the home layer"


class MigrationError(Exception):
    pass


class _Unsafe(Exception):
    """A generated file that does not parse, or that parses to other data than the legacy file."""


def _parse(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise MigrationError(f"{path}: {e}") from None


def _dispatch_values(data: dict) -> dict:
    """transport.mode/timeout_min → [dispatch]; an existing timeout_min wins."""
    transport = data.get("transport") or {}
    dispatch = data.get("dispatch") or {}
    out = {}
    if isinstance(transport, dict):
        if "mode" in transport:
            out["via"] = MODE.get(transport["mode"], transport["mode"])
        if "timeout_min" in transport and "timeout_min" not in dispatch:
            out["timeout_min"] = transport["timeout_min"]
    return out


def _key(line: str) -> str | None:
    m = KEY.match(line)
    return m.group(1) if m else None


def _flat(prefix: str, value) -> list[str]:
    """`transport.a.b = 1` lines for every leaf, so a dropped key can be named exactly."""
    if isinstance(value, dict) and value:
        return [line for k, v in value.items() for line in _flat(f"{prefix}.{k}", v)]
    try:
        text = json.dumps(value, ensure_ascii=False)
    except TypeError:  # a TOML date/time has no JSON form
        text = str(value)
    return [f"{prefix} = {text}"]


def _notes(data: dict, layer: str) -> list[str]:
    notes = []
    if "project" in data and layer == "home":
        notes.append(PROJECT_HOME_NOTE)
    harnesses = data.get("harness")
    if isinstance(harnesses, dict) and any(
            isinstance(h, dict) and "t3_provider" in h for h in harnesses.values()):
        notes.append(T3_PROVIDER_NOTE)
    transport = data.get("transport")
    if isinstance(transport, dict):
        if "t3" in transport:
            notes.append(T3_CLI_NOTE)
        for k, v in transport.items():
            if k not in ("mode", "timeout_min", "t3"):
                notes += [f"dropped {line}" for line in _flat(f"transport.{k}", v)]
    return notes


def _header(line: str) -> tuple[str, ...] | None:
    """The key path a table header declares: `[role."a.b"]` → ("role", "a.b"); else None.
    tomllib parses it, so quoted keys keep their dots and a value line never looks like a header."""
    text = line.strip()
    if not text.startswith("["):
        return None
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None
    path: tuple[str, ...] = ()
    node = data
    while isinstance(node, dict) and len(node) == 1:
        k, node = next(iter(node.items()))
        path += (k,)
        if isinstance(node, list):  # [[a.b]] declares an array of tables
            return path
    return path if path and node == {} else None


def _scan(line: str, ml: str | None, depth: int) -> tuple[str | None, int]:
    """Carry the multi-line-string / open-bracket state over one physical line, so a line inside
    a multi-line value is never mistaken for a table header."""
    i, n = 0, len(line)
    while i < n:
        if ml is not None:
            j = line.find(ml, i)
            if j < 0:
                return ml, depth
            i, ml = j + 3, None
            continue
        ch = line[i]
        if ch == "#":
            break
        if ch in "\"'":
            if line.startswith(ch * 3, i):
                i, ml = i + 3, ch * 3
                continue
            i += 1
            while i < n:
                if ch == '"' and line[i] == "\\":
                    i += 2
                    continue
                if line[i] == ch:
                    i += 1
                    break
                i += 1
            continue
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth = max(0, depth - 1)
        i += 1
    return ml, depth


def _sub_header(line: str, path: tuple[str, ...]) -> str:
    """A split file's own top level: `[role.x.hint.ui]` → `[hint.ui]`, `[[role.x.panel]]` → `[[panel]]`."""
    if not path:
        return ""
    double = line.lstrip().startswith("[[")
    open_br, close_br = ("[[", "]]") if double else ("[", "]")
    return f"{open_br}{'.'.join(_quote(k) for k in path)}{close_br}\n"


def _quote(key: str) -> str:
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else json.dumps(key, ensure_ascii=False)


def _split_legacy(path: Path, data: dict, layer: str) -> tuple[dict[str, str], list[str]]:
    """Textual split so comments and unknown keys survive; the TOML is validated first."""
    files: dict[str, str] = {}
    notes = _notes(data, layer)
    generated = _dispatch_values(data)
    dispatch_added = False
    section: tuple[str, ...] | None = None
    dest: str | None = "config.toml"
    ml, depth = None, 0
    pending: list[str] = []  # comment lines: a block directly above a header moves with it

    def add(rel: str | None, text: str) -> None:
        if rel is not None and text:
            files[rel] = files.get(rel, "") + text

    for line in path.read_text().splitlines(keepends=True):
        hdr = _header(line) if ml is None and depth == 0 else None
        ml, depth = _scan(line, ml, depth)
        body = line.lstrip()
        if hdr is None and body.startswith("#"):
            pending.append(line)
            continue
        if hdr is not None:
            section, top = hdr, hdr[0]
            dest, header, extra = "config.toml", line, ""
            if top in SPLIT and len(hdr) > 1:
                if not NAME.match(hdr[1]):
                    raise MigrationError(f"bad {KIND_OF[SPLIT[top]]} name {hdr[1]!r} in {path}")
                dest, header = f"{SPLIT[top]}/{hdr[1]}.toml", _sub_header(line, hdr[2:])
            elif top == "project":
                dest = None if layer == "home" else "project.toml"
                header = "" if dest is None else _sub_header(line, hdr[1:])
            elif top == "transport":
                dest, header = None, ""
            elif top == "dispatch" and not dispatch_added:
                extra = "".join(f"{k} = {json.dumps(v, ensure_ascii=False)}\n"
                                for k, v in generated.items())
                dispatch_added = True
            add(dest, "".join(pending))
            pending = []
            add(dest, header)
            add(dest, extra)
            continue

        add(dest, "".join(pending))
        pending = []
        if not body.strip():  # a blank line detaches the comment block above it
            add(dest, line)
            continue
        if dest is None:
            continue
        if section and section[0] == "harness" and len(section) == 2 and _key(line) == "t3_provider":
            continue
        if section == ("dispatch",) and _key(line) in generated:
            continue  # replaced by the transport.mode value written under the header
        add(dest, line)

    add(dest, "".join(pending))
    if generated and not dispatch_added:
        add("config.toml", "\n[dispatch]\n" + "".join(
            f"{k} = {json.dumps(v, ensure_ascii=False)}\n" for k, v in generated.items()))

    # A split file starts at its own top level; remove whitespace left by the old header.
    return {rel: text.lstrip("\n") for rel, text in files.items() if text.strip()}, notes


def _fold(files: dict[str, str]) -> dict:
    """Read the generated files back as the tables they will load into."""
    out: dict = {}
    for rel, text in files.items():
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as e:
            raise _Unsafe(f"{rel}: {e}") from None
        head, _, name = rel.partition("/")
        if rel == "project.toml":
            out["project"] = data
        elif rel == "config.toml":
            out["config"] = data
        else:
            out.setdefault(KIND_OF[head], {})[name.removesuffix(".toml")] = data
    return out


def _mapped(data: dict, layer: str) -> dict:
    """What the legacy file's tables must become (the spec's mapping table)."""
    out = {"config": {k: v for k, v in data.items()
                      if k not in (*SPLIT, "project", "transport")}}
    for table in SPLIT:
        if table in data:
            out[table] = data[table]
    if "project" in data and layer != "home":
        out["project"] = data["project"]
    if isinstance(out.get("harness"), dict):
        out["harness"] = {name: {k: v for k, v in h.items() if k != "t3_provider"}
                          if isinstance(h, dict) else h for name, h in out["harness"].items()}
    dispatch = dict(out["config"].get("dispatch") or {})
    dispatch.update(_dispatch_values(data))
    if dispatch:
        out["config"] = {**out["config"], "dispatch": dispatch}
    return out


_MISSING = object()


def _compact(tables: dict) -> dict:
    """An absent table and an empty one are the same thing."""
    return {k: v for k, v in tables.items() if v != {}}


def _first_diff(left, right, path: tuple[str, ...] = ()) -> str | None:
    """The dotted path of the first difference, or None. An empty path means the root itself."""
    if isinstance(left, dict) and isinstance(right, dict):
        for k in sorted({*left, *right}):
            found = _first_diff(left.get(k, _MISSING), right.get(k, _MISSING), path + (k,))
            if found is not None:
                return found
        return None
    if isinstance(left, list) and isinstance(right, list):
        for i in range(max(len(left), len(right))):
            one = left[i] if i < len(left) else _MISSING
            other = right[i] if i < len(right) else _MISSING
            found = _first_diff(one, other, path + (str(i),))
            if found is not None:
                return found
        return None
    if left is _MISSING or right is _MISSING:
        return ".".join(path)
    if type(left) is not type(right) or left != right:  # true vs 1, 1 vs 1.0
        return ".".join(path)
    return None


def _selected_dirs(root: Path | None, scope: str) -> list[tuple[str, Path]]:
    if scope == "repo" and root is None:
        raise MigrationError("not in a git repository")
    by_name = dict(C.layers(root))  # the repo/local dirs fall back to the primary in a worktree
    out = []
    if scope in ("all", "global"):
        out.append(("home", by_name["home"]))
    if scope in ("all", "repo") and root is not None:
        out.append(("repo", by_name["repo"]))
    seen, unique = {}, []
    for name, d in out:
        key = d.resolve()
        if key not in seen:
            seen[key] = len(unique)
            unique.append((name, d))
        elif name == "repo":  # the same dir is the repo layer too: migrate its config.local
            unique[seen[key]] = (name, d)
    return unique


def _sources(dirs: list[tuple[str, Path]]) -> list[tuple[Path, str, dict]]:
    out = []
    for name, d in dirs:
        cfg = d / "config.toml"
        if cfg.is_file():
            data = _parse(cfg)  # bad TOML is an error even when the file is not legacy
            if C.LEGACY_TABLES & set(data):
                out.append((cfg, name, data))
        local = d / "config.local.toml"
        if name == "repo" and local.is_file():
            out.append((local, "repo", _parse(local)))
    return out


def _ignored(repo: Path, rel: str) -> bool:
    """Whether git already ignores `rel` in this repo, whatever pattern form it used."""
    r = subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", rel], capture_output=True)
    return r.returncode == 0


def _gitignore(repo_dir: Path, sources: list) -> tuple[Path, list[str]] | None:
    if not any(p.name == "config.local.toml" for p, _, _ in sources):
        return None
    repo = repo_dir.parent
    gi = repo / ".gitignore"
    have = set(gi.read_text().splitlines()) if gi.exists() else set()
    missing = [rel for rel in GITIGNORE if rel not in have and not _ignored(repo, rel)]
    return (gi, missing) if missing else None


def _safe_split(source: Path, data: dict, layer: str) -> tuple[dict[str, str], list[str]]:
    """Split, then refuse anything the generated files would not load back as the same config."""
    files, notes = _split_legacy(source, data, layer)
    try:
        folded = _fold(files)
    except _Unsafe as e:
        raise MigrationError(f"cannot split {source} safely: {e}") from None
    expected = _compact(_mapped(data, layer))
    pairs = ((folded.get("config") or {}, expected.get("config") or {}),
             (_compact({k: v for k, v in folded.items() if k != "config"}),
              _compact({k: v for k, v in expected.items() if k != "config"})))
    for left, right in pairs:
        diff = _first_diff(left, right)
        if diff is not None:
            raise MigrationError(f"cannot split {source} safely: {diff or '<root>'}")
    return files, notes


def _inside(path: Path, base: Path) -> bool:
    """Whether `path` resolves inside `base`, whatever the name looked like."""
    try:
        path.resolve().relative_to(base.resolve())
    except (OSError, ValueError):
        return False
    return True


def _plan(dirs: list[tuple[str, Path]]):
    legacy = _sources(dirs)
    plans, files, notes = [], {}, []
    for source, layer, data in legacy:
        split, found = _safe_split(source, data, layer)
        dest_dir = source.parent / "local" if source.name == "config.local.toml" else source.parent
        plans.append({"source": source, "backup": source.with_name(source.name + ".bak"),
                      "dir": dest_dir, "files": split})
        for rel, text in split.items():
            target = dest_dir / rel
            if not _inside(target, dest_dir):
                raise MigrationError(f"target outside {dest_dir}: {target}")
            files[target] = text
        notes += [n for n in found if n not in notes]

    for item in plans:
        if item["backup"].exists():
            raise MigrationError(f"target exists: {item['backup']}")
    moved = {item["source"] for item in plans}  # a target that is also a source is written later
    for p in files:
        if p.exists() and p not in moved:
            raise MigrationError(f"target exists: {p}")
        if p.parent.exists() and not p.parent.is_dir():
            raise MigrationError(f"not a directory: {p.parent}")

    repo_dir = next((d for name, d in dirs if name == "repo"), None)
    gi = _gitignore(repo_dir, legacy) if repo_dir else None
    return plans, files, notes, gi


def _print_plan(immediate: dict, plans: list[dict], deferred: dict, notes: list[str],
                gi: tuple[Path, list[str]] | None) -> None:
    for p in immediate:
        print(f"write {p}")
    for item in plans:
        print(f"rename {item['source']} → {item['backup']}")
    for p in deferred:
        print(f"write {p}")
    if gi is not None:
        print(f"write {gi[0]}")
    for note in notes:
        print(f"note: {note}")


def _atomic_write(path: Path, text: str) -> None:
    """Write beside the target and rename, so a half-finished write never lands on the target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _write(path: Path, text: str, log: list[tuple[Path, str | None]]) -> None:
    old = path.read_text() if path.is_file() else None
    _atomic_write(path, text)
    log.append((path, old))


def _append(gi: tuple[Path, list[str]]) -> str:
    path, lines = gi
    old = path.read_text() if path.exists() else ""
    if old and not old.endswith("\n"):
        old += "\n"
    return old + "".join(f"{line}\n" for line in lines)


def _rollback(written: list[tuple[Path, str | None]], renamed: list[dict]) -> list[str]:
    """Undo this run: unlink what it created, restore what it changed, rename sources back.
    Returns one message per step that could not be undone."""
    errors = []
    for path, old in reversed(written):
        try:
            if old is None:  # created by this run
                path.unlink(missing_ok=True)
            else:
                _atomic_write(path, old)
        except OSError as e:
            errors.append(f"rollback failed: {path}: {e}")
    for item in reversed(renamed):
        try:
            item["backup"].rename(item["source"])
        except OSError as e:
            errors.append(f"rollback failed: {item['source']}: {e}")
    return errors


def migrate(root: Path | None, scope: str = "all", dry_run: bool = False) -> int:
    try:
        dirs = _selected_dirs(root, scope)
        plans, files, notes, gi = _plan(dirs)
    except Exception as e:  # a MigrationError, or a bug: both exit 1 with nothing written
        print(f"error: {e}", file=sys.stderr)
        return 1

    if not plans:
        print("no legacy config")
        return 0

    # A target that is also a source can only be written once the source has moved aside.
    sources = {item["source"] for item in plans}
    deferred = {p: t for p, t in files.items() if p in sources}
    immediate = {p: t for p, t in files.items() if p not in sources}

    _print_plan(immediate, plans, deferred, notes, gi)
    if dry_run:
        return 0

    written: list[tuple[Path, str | None]] = []
    renamed: list[dict] = []
    try:
        for p, text in immediate.items():
            _write(p, text, written)
        for item in plans:
            item["source"].rename(item["backup"])
            renamed.append(item)
        for p, text in deferred.items():
            _write(p, text, written)
        if gi is not None:
            _write(gi[0], _append(gi), written)
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        for line in _rollback(written, renamed):
            print(f"error: {line}", file=sys.stderr)
        for item in plans:  # a backup still here is the user's way back
            if item["backup"].exists():
                print(f"recover: mv {item['backup']} {item['source']}", file=sys.stderr)
        return 1

    if rest := C.legacy(root):
        for p in rest:
            print(f"note: still legacy: {p}")
    else:
        try:
            C.load(root)
        except C.ConfigError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
    print("next: ask the user, then `sstack-doctor --smoke`")
    return 0


def _source_text(layer: str, path: Path) -> str:
    text = path.read_text()
    if not text.endswith("\n"):
        text += "\n"
    return f"# {layer}: {path}\n{text}"


def _list(root: Path | None) -> int:
    for kind in SHOW_KINDS:
        names = set()
        for _, d in C.layers(root):
            p = d / kind
            if p.is_dir():
                names.update(x.stem for x in p.glob("*.toml"))
        for name in sorted(names):
            found = C.source(root, kind, name)
            if found:
                layer, path = found
                print(f"{kind}/{name}  {layer}  {path}")
    return 0


def show(root: Path | None, target: str | None) -> int:
    if old := C.legacy(root):
        print(f"legacy sstack config {', '.join(map(str, old))}: {C.MIGRATE}", file=sys.stderr)
        return 1
    if target is None:
        return _list(root)
    if target == "config":
        for layer, d in C.layers(root):
            p = d / "config.toml"
            if p.is_file():
                print(_source_text(layer, p), end="")
        return 0
    if target == "project":
        found = C.source(root, "project", None)
    else:
        kind, sep, name = target.partition("/")
        found = C.source(root, kind, name) if sep and kind in SHOW_KINDS and name else None
    if not found:
        print(f"no {target} in any layer", file=sys.stderr)
        return 1
    layer, path = found
    print(_source_text(layer, path), end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sstack-config")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("migrate", help="split legacy config.toml files")
    where = m.add_mutually_exclusive_group()
    where.add_argument("--global", dest="scope", action="store_const", const="global")
    where.add_argument("--repo", dest="scope", action="store_const", const="repo")
    m.set_defaults(scope="all")
    m.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("show", help="print effective config and its layer")
    s.add_argument("target", nargs="?")
    a = ap.parse_args(argv)

    root = C.git_root(Path.cwd())
    if a.cmd == "migrate":
        return migrate(root, a.scope, a.dry_run)
    return show(root, a.target)


if __name__ == "__main__":
    raise SystemExit(main())
