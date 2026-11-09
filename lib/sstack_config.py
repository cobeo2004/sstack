"""Load the three sstack config layers and resolve a role to harness members."""
import subprocess
import tomllib
from pathlib import Path

from sstack_worktree import primary_of

READONLY_ROLES = {"scout", "investigate", "plan", "review"}
WHOLE = {"role", "harness", "tier"}  # tables whose children are replaced whole


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
    A linked worktree usually excludes `.sstack/` from git, so its config and lessons live
    in the primary one. Runs stay per-checkout (they name this checkout's paths)."""
    own = root / ".sstack" / name
    if own.exists():
        return own
    primary = _primary(root)
    # ponytail: the fallback is per `.sstack/` directory, not per file, so a worktree that
    # wants no repo config at all cannot say so with an empty `.sstack/`.
    if primary == root or not (primary / ".sstack").is_dir():
        return own
    return primary / ".sstack" / name


def layer_paths(root: Path | None) -> list[tuple[str, Path]]:
    out = [("global", Path.home() / ".sstack" / "config.toml")]
    if root is not None:
        out += [("repo", repo_file(root, "config.toml")),
                ("local", repo_file(root, "config.local.toml"))]
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


def _layers(root):
    return [(name, _read(p)) for name, p in layer_paths(root) if p.is_file()]


def load(root: Path | None) -> dict:
    cfg: dict = {}
    for _, data in _layers(root):
        cfg = merge(cfg, data)
    return cfg


def source_layer(root: Path | None, dotted: str) -> str | None:
    found = None
    for name, data in _layers(root):
        node = data
        for part in dotted.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if node is not None:
            found = name
    return found


def _member(cfg: dict, m: dict) -> dict | None:
    h = m.get("harness")
    if not h or h == "local":
        return None
    if h not in cfg.get("harness", {}):
        raise ConfigError(f"unknown harness {h!r} (define [harness.{h}])")
    return {"harness": h, "model": m.get("model"), "effort": m.get("effort")}


def resolve(cfg: dict, role: str) -> list[dict] | None:
    """None = run locally in this session; else a list of members."""
    if cfg.get("transport", {}).get("mode") == "local":
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
