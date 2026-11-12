"""Load the layered, split sstack config (docs/spec/config.md) and resolve a role to members.

Layers, lowest first: home ($SSTACK_HOME or ~/.sstack) → repo .sstack → .sstack/local. In each:
config.toml (merged key by key), project.toml (repo layers only, replaced whole), harnesses/ roles/
tiers/ ades/ (one file per thing, replaced whole). <sstack>/defaults is the profile template that
`sstack-config sync` copies into home; at runtime only its code files (steps/*/run.sh, ades/*.hook)
are read, as a fallback when no layer has one."""
import os
import subprocess
import tomllib
from pathlib import Path

from sstack_worktree import primary_of

TEMPLATE = Path(__file__).resolve().parent.parent / "defaults"
READONLY_ROLES = {"scout", "investigate", "plan", "review"}
VARIANT_STAGES = ("investigate", "plan", "review")  # stages that take roles/<stage>/<name>.toml
WHOLE = {"role", "harness", "tier"}  # tables whose children are replaced whole
KINDS = {"harnesses": "harness", "roles": "role", "tiers": "tier"}  # dir → load() table
LAYOUT = ("config.toml", "project.toml", "harnesses", "roles", "tiers", "ades", "steps")
STEP_FILES = ("step.toml", "brief.md", "run.sh")  # what a steps/<name>/ folder may hold
LEGACY_TABLES = {"harness", "role", "tier", "project", "transport"}
MIGRATE = "run `sstack-config migrate` to split it into the new layout (docs/spec/config.md)"
SYNC = "run `sstack-config sync`"


class ConfigError(Exception):
    pass


def git_root(cwd: Path) -> Path | None:
    r = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    return Path(r.stdout.strip()) if r.returncode == 0 else None


def _primary(root: Path) -> Path:
    """The primary checkout of a linked worktree; `root` itself otherwise."""
    if (root / ".git").is_dir():
        return root  # a primary checkout's .git is a directory; a linked worktree's is a file
    try:
        return primary_of(root)
    except (subprocess.CalledProcessError, OSError, IndexError):
        return root


def repo_file(root: Path, name: str) -> Path:
    """This checkout's `.sstack/<name>`, else the primary checkout's, else this checkout's.
    Used for lessons. Runs stay per-checkout (they name this checkout's paths)."""
    own = root / ".sstack" / name
    if own.exists():
        return own
    primary = _primary(root)
    if primary == root or not (primary / ".sstack").is_dir():
        return own
    return primary / ".sstack" / name


def _has_config(d: Path) -> bool:
    """A file of the layout, or a layout dir holding at least one file (a variant's roles/<stage>/
    file counts); empty dirs don't count."""
    return any((d / n).is_file() or ((d / n).is_dir() and any(c.is_file() for c in (d / n).rglob("*")))
               for n in LAYOUT + ("config.local.toml",))


def _repo_dir(root: Path, rel: str) -> Path:
    """This checkout's `<rel>` dir if it holds any config, else the primary checkout's.
    A linked worktree usually excludes `.sstack/` from git, so its config lives in the primary.
    ponytail: the fallback is per layer directory, so a worktree can't opt out with an empty dir."""
    own = root / rel
    if _has_config(own):
        return own
    primary = _primary(root) / rel
    return primary if primary != own and _has_config(primary) else own


def home_dir() -> Path:
    return Path(os.environ.get("SSTACK_HOME") or Path.home() / ".sstack")


def trusted(root: Path) -> bool:
    """Whether this checkout (or its primary) is listed in `~/.sstack/repos.txt`."""
    f = home_dir() / "repos.txt"
    entries = set()
    if f.is_file():
        for line in f.read_text().splitlines():
            if line.strip():
                entries.add(str(Path(line.strip()).expanduser().resolve()))
    return bool({str(root.resolve()), str(_primary(root).resolve())} & entries)


def layers(root: Path | None) -> list[tuple[str, Path]]:
    """[(name, dir)] lowest first: home, then repo and local when in a git repo."""
    out = [("home", home_dir())]
    if root is not None:
        out += [("repo", _repo_dir(root, ".sstack")), ("local", _repo_dir(root, ".sstack/local"))]
    return out


def merge(base: dict, over: dict, _path: tuple = ()) -> dict:
    out = dict(base)
    for k, v in over.items():
        whole = (len(_path) == 1 and _path[0] in WHOLE) or (not _path and k == "project")
        if isinstance(v, dict) and isinstance(out.get(k), dict) and not whole:
            out[k] = merge(out[k], v, _path + (k,))
        else:
            out[k] = v
    return out


def _read(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from None


def _is_legacy(p: Path) -> bool:
    if p.name == "config.local.toml":
        return p.is_file()
    try:
        return p.is_file() and bool(LEGACY_TABLES & tomllib.loads(p.read_text()).keys())
    except tomllib.TOMLDecodeError:
        return False


def legacy(root: Path | None, _ls: list | None = None) -> list[Path]:
    """Old single-file configs: a config.toml holding [harness|role|tier|project|transport]
    tables, or any `config.local.toml`. Deduped (home == repo when $HOME is the git repo)."""
    out = []
    for name, d in _ls or layers(root):
        cands = [d / "config.toml"] + ([d / "config.local.toml"] if name == "repo" else [])
        out += [p for p in cands if _is_legacy(p) and p.resolve() not in {q.resolve() for q in out}]
    return out


def _layer_data(name: str, d: Path) -> dict:
    data = _read(d / "config.toml") if (d / "config.toml").is_file() else {}
    if name in ("repo", "local") and (d / "project.toml").is_file():
        data["project"] = _read(d / "project.toml")
    for kind, table in KINDS.items():
        for p in sorted((d / kind).glob("*.toml")):
            data.setdefault(table, {})[p.stem] = _read(p)
    return data


def require_profile(root: Path | None, _ls: list | None = None) -> None:
    """Raise when the home layer has no config.toml: nothing falls back to the template."""
    home = dict(_ls or layers(root)).get("home")
    if home is not None and not (home / "config.toml").is_file():
        raise ConfigError(f"no sstack profile at {home}: {SYNC}")


def _layer_datas(root, _ls: list | None = None):
    ls = _ls or layers(root)
    if old := legacy(root, ls):  # hard cut: any legacy file, even beside split files
        raise ConfigError(f"legacy sstack config {', '.join(map(str, old))}: {MIGRATE}")
    require_profile(root, ls)
    return [(name, _layer_data(name, d)) for name, d in ls]


def load(root: Path | None, _ls: list | None = None) -> dict:
    """Effective config: {harness: {name: {...}}, role: {...}, tier: {...}, project: {...},
    plus config.toml keys (ade, dispatch, rules, reflect, routing)}. ADEs: see ades().
    `_ls` reads a different [(name, dir)] stack, for validating a staged layer."""
    cfg: dict = {}
    for _, data in _layer_datas(root, _ls):
        cfg = merge(cfg, data)
    return cfg


PLAN_GATES = ("auto", "inbox")


def unattended(cfg: dict, env=None) -> dict:
    """{"enabled": bool, "plan_gate": "auto" | "inbox"} from `[unattended]` in the merged config (any
    layer, the local one included) and the env: SSTACK_UNATTENDED=1 turns it on, SSTACK_PLAN_GATE
    overrides plan_gate for this process. Defaults: off, "inbox". A bad value raises ConfigError."""
    env = os.environ if env is None else env
    t = cfg.get("unattended", {})
    if not isinstance(t, dict):
        raise ConfigError(f"unattended {t!r} is not a table")
    from_env = "SSTACK_PLAN_GATE" in env  # present, even empty, so a bad value is never ignored
    enabled, gate = t.get("enabled", False), env["SSTACK_PLAN_GATE"] if from_env else t.get("plan_gate", "inbox")
    where = "SSTACK_PLAN_GATE" if from_env else "[unattended] plan_gate"
    if gate not in PLAN_GATES:
        raise ConfigError(f"{where} {gate!r} is not one of: {', '.join(PLAN_GATES)}")
    if type(enabled) is not bool:
        raise ConfigError(f"[unattended] enabled {enabled!r} is not true or false")
    return {"enabled": enabled or env.get("SSTACK_UNATTENDED") == "1", "plan_gate": gate}


def source(root: Path | None, kind: str, name: str | None, _ls: list | None = None) -> tuple[str, Path] | None:
    """(layer, path) of the file that wins for one thing: kind = config | project | harnesses |
    roles | tiers | ades | steps (name = the file stem, dots allowed; ades also takes "t3.md" /
    "t3.hook"; roles also takes a variant "<stage>/<name>" or "<stage>/<name>.md"; steps takes
    "<step>/<file>" for step.toml, brief.md or run.sh).
    Only names listed in the kind's dir match, so a name can't climb out of it. A code file
    (steps run.sh, ades .hook) that no layer has comes from the template, labelled "template"."""
    found = None
    sub, _, tail = (name or "").rpartition("/")
    if kind == "steps":
        if not sub or tail not in STEP_FILES:
            return None
    elif sub and (kind != "roles" or sub not in VARIANT_STAGES):
        return None
    name = tail
    ls = list(_ls or layers(root))
    if (kind, name) == ("steps", "run.sh") or (kind == "ades" and name.endswith(".hook")):
        ls = [("template", TEMPLATE)] + ls  # lowest: any layer's copy wins
    for layer, d in ls:
        if kind == "project" and layer not in ("repo", "local"):
            continue
        if kind in ("config", "project"):
            p = d / f"{kind}.toml"
        else:
            where = d / kind / sub if sub else d / kind
            have = {e.name for e in where.iterdir()} if where.is_dir() else set()
            p = next((where / n for n in (f"{name}.toml", name) if n in have), None)
        if p is not None and p.is_file():
            found = (layer, p)
    return found


def ades(root: Path | None, _ls: list | None = None) -> list[dict]:
    """Adapters in detection order: layers nearest first (local, repo, home); within a layer the
    user's own ADEs alphabetically, then the template's built-ins alphabetically; a nearer file
    replaces a farther one of the same name whole. hook_path / note_path resolve per file (nearest
    layer that has one, then the template for a hook)."""
    ls = _ls or layers(root)
    out, seen = [], set()
    for layer, d in reversed(ls):
        for p in sorted((d / "ades").glob("*.toml"),
                        key=lambda p: ((TEMPLATE / "ades" / p.name).is_file(), p.stem)):
            if p.stem in seen:
                continue
            seen.add(p.stem)
            toml = _read(p)
            hook, note = (source(root, "ades", f"{p.stem}.{x}", ls) for x in ("hook", "md"))
            out.append({"name": p.stem, "layer": layer, "toml": toml,
                        "hook_path": hook[1] if hook else None, "note_path": note[1] if note else None,
                        "auto": toml.get("auto", True)})
    return out


def variants(root: Path | None, _ls: list | None = None) -> list[dict]:
    """Stage variants (roles/<stage>/<name>.toml + .md), by stage then name. The .toml and the .md
    each come from the nearest layer that has one; `enabled = false` there drops the variant."""
    ls = _ls or layers(root)
    out = []
    for stage in VARIANT_STAGES:
        for n in sorted({p.stem for _, d in ls for p in (d / "roles" / stage).glob("*.toml")}):
            layer, path = source(root, "roles", f"{stage}/{n}", ls)
            spec = _read(path)
            if spec.get("enabled", True) is False:
                continue
            lens = source(root, "roles", f"{stage}/{n}.md", ls)
            out.append({"id": f"{stage}/{n}", "stage": stage, "name": n, "layer": layer, "path": path,
                        "spec": spec, "lens_path": lens[1] if lens else None})
    return out


def _step_names(ls: list[tuple[str, Path]]) -> list[str]:
    names = set()
    for _, d in ls:
        base = d / "steps"
        if not base.is_dir():
            continue
        names |= {p.name for p in base.iterdir()
                  if p.is_dir() and any((p / f).is_file() for f in STEP_FILES)}
    return sorted(names)


def steps(root: Path | None, _ls: list | None = None) -> dict:
    """The `steps/<name>/` folders of every layer: {"spec": step.toml merged key by key, "source":
    {key or file: layer, "template" for a template run.sh}, "brief"/"run": the nearest layer's
    file or None, "builtin": ships in the template's steps/}. Read beside load(), never in it, so load() output is unchanged."""
    ls = _ls or layers(root)
    out = {}
    for name in _step_names(ls):
        spec, src = {}, {}
        for layer, d in ls:
            p = d / "steps" / name / "step.toml"
            if p.is_file():
                data = _read(p)
                spec = merge(spec, data)
                src.update({k: layer for k in data})
        brief = source(root, "steps", f"{name}/brief.md", ls)
        run = source(root, "steps", f"{name}/run.sh", ls)
        if brief:
            src["brief"] = brief[0]
        if run:
            src["run"] = run[0]
        out[name] = {"spec": spec, "source": src, "brief": brief[1] if brief else None,
                     "run": run[1] if run else None, "builtin": (TEMPLATE / "steps" / name).is_dir()}
    return out


def _member(cfg: dict, m: dict) -> dict | None:
    h = m.get("harness")
    if not h or h == "local":
        return None
    if h not in cfg.get("harness", {}):
        raise ConfigError(f"unknown harness {h!r} (add harnesses/{h}.toml or {SYNC})")
    return {"harness": h, "model": m.get("model"), "effort": m.get("effort")}


def resolve(cfg: dict, role: str) -> list[dict] | None:
    """None = run locally in this session; else a list of members."""
    if cfg.get("dispatch", {}).get("via") == "local":
        return None
    spec = cfg.get("role", {}).get(role)
    if not spec:
        return None
    raw = spec["panel"] if "panel" in spec else [spec]
    members = [m for m in (_member(cfg, x) for x in raw) if m]
    if role == "review" and cfg.get("rules", {}).get("review_not_implementer", True):
        impl = resolve(cfg, "implement")
        if impl:
            key = (impl[0]["harness"], impl[0]["model"])
            members = [m for m in members if (m["harness"], m["model"]) != key]
    return members or None
