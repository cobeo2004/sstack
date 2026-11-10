"""sstack-ui: a local cockpit for layered config, ADEs, runs, lessons and the code graph."""

import argparse
import json
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

import sstack_ade as A
import sstack_lessons as L
from sstack_config import _has_config, _primary, ConfigError, ades, git_root, home_dir, layers, load, resolve, source

REPO = Path(__file__).resolve().parent.parent
KINDS = {"harnesses": "harness", "roles": "role", "tiers": "tier"}
EDITABLE_LAYERS = ("home", "repo", "local")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
THING_TABLES = ("harness", "role", "tier", "project")  # owned by their own files, not config.toml
# What the loader reads out of a layer; validation copies exactly this, never runs/ or lessons.
LAYER_ENTRIES = ("config.toml", "config.local.toml", "project.toml",
                 "harnesses", "roles", "tiers", "ades")
MUTATION = threading.Lock()  # one save or reset at a time, so staging and publishing can't interleave


def _root(q) -> Path | None:
    """`repo=` must name the root of a git repository; anything else is a config path we invent."""
    r = q.get("repo", ["global"])[0]
    if r == "global":
        return None
    p = Path(r).resolve()
    if git_root(p) != p:
        raise ValueError(f"repo {r!r} is not the root of a git repository")
    return p


def _layer_map(root: Path | None) -> dict[str, Path]:
    return {name: d for name, d in layers(root)[1:]}


def _check_layer(root: Path | None, layer: str) -> Path:
    if layer not in EDITABLE_LAYERS:
        raise ValueError("layer must be home, repo or local")
    have = _layer_map(root)
    if layer not in have:
        raise ValueError(f"layer {layer!r} is unavailable for this repo")
    d = have[layer]
    # ponytail: ~/.sstack may be a dotfiles symlink (your choice); a repo's .sstack or .sstack/local may not
    for x in ((d, d.parent) if layer == "local" else (d,) if layer == "repo" else ()):
        if x.is_symlink():
            raise ValueError(f"refusing a symlinked layer dir: {x}")
    return d


def _config_path(root: Path | None, layer: str, kind: str, name: str) -> Path:
    """Resolve one editable config file, refusing defaults, hooks, notes and escapes."""
    base = _check_layer(root, layer)
    if kind in ("config", "project"):
        if name not in ("", kind, f"{kind}.toml"):
            raise ValueError(f"{kind} takes no name")
        if kind == "project" and layer not in ("repo", "local"):
            raise ValueError("project.toml exists only in repo and local layers")
        p = base / f"{kind}.toml"
    elif kind in ("harnesses", "roles", "tiers", "ades"):
        stem = name[:-5] if name.endswith(".toml") else name
        if not stem or not NAME_RE.fullmatch(stem):
            raise ValueError("bad name")
        if kind == "ades" and stem.endswith((".hook", ".md")):
            raise ValueError("ADEs are edited as TOML only; hooks and notes are never written")
        p = base / kind / f"{stem}.toml"
    else:
        raise ValueError("unknown kind")
    root_dir = base.resolve()
    if not p.resolve().is_relative_to(root_dir):
        raise ValueError("path outside the layer")
    return p


def _file_payload(root: Path | None, layer: str, kind: str, name: str) -> dict:
    p = _config_path(root, layer, kind, name)
    exists = p.is_file()
    return {"layer": layer, "kind": kind, "name": name, "path": str(p),
            "text": p.read_text() if exists else "", "exists": exists}


def _refuse_symlink(p: Path, base: Path) -> None:
    """A config file must be a real file in its layer: no symlinked target, no symlinked parent."""
    if not p.is_relative_to(base):
        raise ValueError("path outside the layer")
    cur = base
    for part in p.relative_to(base).parts:
        cur = cur / part
        if cur.is_symlink():
            raise ValueError(f"refusing to write through a symlink: {cur}")


def _atomic_write(p: Path, base: Path, text: str) -> None:
    """Write beside the target with O_EXCL, then rename. The temp name is never predictable."""
    _refuse_symlink(p, base)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=p.parent, prefix=p.name + ".", suffix=".tmp")
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _copy_layer(src: Path, dst: Path) -> None:
    """Copy only what the loader reads, so validation never drags runs/ or lessons along."""
    for name in LAYER_ENTRIES:
        entry = src / name
        if entry.is_dir():
            shutil.copytree(entry, dst / name, dirs_exist_ok=True)
        elif entry.is_file():
            (dst / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(entry, dst / name)


def _staged(root: Path | None, base: Path, staged: Path) -> list[tuple[str, Path]]:
    """The real layer stack with `base` swapped for its staged copy."""
    out = []
    for n, d in layers(root):
        if d == base:
            d = staged
            if root is not None and n in ("repo", "local") and not _has_config(staged):
                prim = _primary(root) / base.relative_to(root) if base.is_relative_to(root) else base
                d = prim if prim != base and _has_config(prim) else staged  # the loader's worktree fallback
        out.append((n, d))
    return out


def _validate(root: Path | None, staged_ls: list) -> None:
    """The whole tree must load, every role must resolve, and ADE detect/delegate must be tables."""
    cfg = load(root, staged_ls)
    for role in sorted(cfg.get("role", {})):
        resolve(cfg, role)
    for ade in ades(root, staged_ls):
        for key in ("detect", "delegate"):
            if key in ade["toml"] and not isinstance(ade["toml"][key], dict):
                raise ConfigError(f"ades/{ade['name']}.toml: {key} must be a table")


def _stage_and_validate(root: Path | None, base: Path, p: Path, text: str | None) -> None:
    """Apply the change to a throwaway copy of `p`'s layer and validate that, never the live tree."""
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp)
        _copy_layer(base, staged)
        target = staged / p.relative_to(base)
        if text is None:
            target.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        _validate(root, _staged(root, base, staged))


def _write_config(root: Path | None, layer: str, kind: str, name: str, body: dict) -> dict:
    text = body.get("text")
    if not isinstance(text, str):
        raise ValueError("body must be {\"text\": \"<TOML>\"}")
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"invalid TOML: {e}") from None
    with MUTATION:
        base = _check_layer(root, layer)
        p = _config_path(root, layer, kind, name)
        _stage_and_validate(root, base, p, text)
        _atomic_write(p, base, text)
    return {"ok": True, "layer": layer, "kind": kind, "name": name, "path": str(p)}


def _delete_config(root: Path | None, layer: str, kind: str, name: str) -> dict:
    with MUTATION:
        base = _check_layer(root, layer)
        p = _config_path(root, layer, kind, name)
        _refuse_symlink(p, base)
        removed = p.is_file()
        _stage_and_validate(root, base, p, None)
        p.unlink(missing_ok=True)
    return {"ok": True, "removed": removed, "layer": layer, "kind": kind,
            "name": name, "path": str(p)}


def _layer_count(d: Path) -> int:
    n = sum(1 for f in ("config.toml", "project.toml") if (d / f).is_file())
    for kind in ("harnesses", "roles", "tiers", "ades"):
        n += len(list((d / kind).glob("*.toml"))) if (d / kind).is_dir() else 0
    return n


def _thing(root: Path | None, kind: str, name: str, value, label: str) -> dict:
    s = source(root, kind, name or None)
    return {"kind": kind, "name": name, "label": label, "value": value,
            "source": s[0] if s else None, "path": str(s[1]) if s else None}


def _config(root: Path | None) -> dict:
    cfg = load(root)
    merged = {k: v for k, v in cfg.items() if k not in THING_TABLES}
    ls = layers(root)
    things = [_thing(root, "config", "", merged, "config.toml")]
    popt = _thing(root, "project", "", cfg["project"], "project.toml") if "project" in cfg else None
    if popt and root is not None:
        things.append(popt)
    for kind, table in KINDS.items():
        for name in sorted(cfg.get(table, {})):
            things.append(_thing(root, kind, name, cfg[table][name], f"{kind}/{name}"))
    for a in ades(root):
        things.append(_thing(root, "ades", a["name"], a["toml"], f"ades/{a['name']}"))
    return {"effective": merged, "things": things,
            "layers": [{"name": name, "path": str(d), "exists": d.exists(), "count": _layer_count(d)}
                       for name, d in ls]}


def _ade(root: Path | None) -> dict:
    """The `sstack-dispatch ade` JSON plus the note text, from the same code dispatch uses."""
    d = A.describe(*A.active(root, load(root), os.environ))
    note = Path(d["note"]) if d["note"] else None
    return {**d, "note_text": note.read_text()[:200_000] if note and note.is_file() else None}


def _run_groups(root: Path | None) -> list[dict]:
    if root is None:
        return []
    p = root / ".sstack" / "runs" / "index.jsonl"
    if not p.exists():
        return []
    groups: dict[str, dict] = {}
    order: list[str] = []
    for line in p.read_text().splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        key = str(rec.get("run_dir") or "(unknown run)")
        if key not in groups:
            groups[key] = {"run_dir": rec.get("run_dir"), "lines": []}
            order.append(key)
        groups[key]["lines"].append(rec)

    out = []
    for key in order:
        g = groups[key]
        g["lines"].sort(key=lambda x: str(x.get("ts", "")))
        warnings = []
        for line in g["lines"]:
            for w in line.get("readonly_warning") or []:
                if w not in warnings:
                    warnings.append(w)
        g["readonly_warning"] = warnings
        g["ts"] = max((str(x.get("ts", "")) for x in g["lines"]), default="")
        g["run"] = None
        if g["run_dir"]:
            rp = Path(g["run_dir"])
            rp = rp if rp.is_absolute() else root / rp
            try:
                g["run"] = json.loads((rp / "run.json").read_text())
            except (OSError, json.JSONDecodeError):
                pass
        out.append(g)
    tasks: dict[str, dict] = {}
    for g in out:
        path = Path(str(g["run_dir"] or "(unknown run)"))
        try:
            below = path.relative_to(".sstack/runs")
        except ValueError:
            task = str(g["run_dir"] or "(unknown run)")
        else:
            task = (Path(".sstack/runs") / below.parts[0]).as_posix() if len(below.parts) > 1 else \
                str(g["run_dir"])
        group = tasks.setdefault(task, {"task": task, "children": []})
        group["children"].append(g)
    for group in tasks.values():
        group["children"].sort(key=lambda g: g["ts"], reverse=True)
        group["ts"] = max((g["ts"] for g in group["children"]), default="")
        group["workflow"] = _task_workflow(root, group["task"])
    return sorted(tasks.values(), key=lambda g: g["ts"], reverse=True)


def _task_workflow(root: Path, task: str) -> dict | None:
    """The task's `<run>/workflow.json`, or None when it is missing or unreadable."""
    d = Path(task)
    d = d if d.is_absolute() else root / d
    try:
        state = json.loads((d / "workflow.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return state if isinstance(state, dict) else None


def _lessons(root: Path | None) -> list[dict]:
    out = []
    scopes = [("global", None)] + ([("repo", root)] if root else [])
    for scope, r in scopes:
        p = L.lessons_path(scope, r)
        if p.exists():
            for l in L.parse(p.read_text()):
                if isinstance(l, L.Lesson):
                    out.append({"scope": scope, "id": l.id, "status": l.status, "seen": l.seen,
                                "text": l.text, **l.fields})
    return out


def _graph(root: Path | None) -> dict:
    if root is None or not shutil.which("code-review-graph"):
        return {"available": False}
    if not (root / ".code-review-graph").exists():
        return {"available": True, "built": False, "status": "No graph yet."}  # status would create one
    r = subprocess.run(["code-review-graph", "status"], cwd=root, capture_output=True, text=True, timeout=60)
    return {"available": True, "status": (r.stdout + r.stderr).strip(),
            "built": (root / ".code-review-graph").exists()}


def _lesson_action(b, action):
    root = None if b["repo"] == "global" else Path(b["repo"])
    p = L.lessons_path(b["scope"], root)
    if action == "accept":
        L.set_status(p, b["id"], "accepted")
    else:
        L.forget(p, b["id"])
    return {"ok": True}


def _rebuild(b):
    root = Path(b["repo"])
    if not shutil.which("code-review-graph"):
        return {"ok": False, "error": "code-review-graph not installed"}
    sub = "update" if (root / ".code-review-graph").exists() else "build"
    r = subprocess.run(["code-review-graph", sub], cwd=root, capture_output=True, text=True, timeout=600)
    return {"ok": r.returncode == 0, "output": (r.stdout + r.stderr)[-4000:]}


def _repos():
    f = home_dir() / "repos.txt"
    lines = f.read_text().splitlines() if f.exists() else []
    return {"repos": [l.strip() for l in dict.fromkeys(lines) if l.strip() and Path(l.strip()).is_dir()]}


GETS = {
    "/api/repos": lambda q: _repos(),
    "/api/lessons": lambda q: {"lessons": _lessons(_root(q))},
    "/api/config": lambda q: _config(_root(q)),
    "/api/ade": lambda q: _ade(_root(q)),
    "/api/runs": lambda q: {"runs": _run_groups(_root(q))},
    "/api/graph": lambda q: _graph(_root(q)),
}
POSTS = {
    "/api/lessons/accept": lambda b: _lesson_action(b, "accept"),
    "/api/lessons/forget": lambda b: _lesson_action(b, "forget"),
    "/api/graph/rebuild": _rebuild,
}


def _config_route(path: str):
    parts = path.split("/")
    if len(parts) not in (5, 6) or parts[:3] != ["", "api", "config"]:
        raise ValueError("bad config path")
    layer, kind = unquote(parts[3]), unquote(parts[4])
    name = unquote(parts[5]) if len(parts) == 6 else ""
    return layer, kind, name


def make_server(port: int, token: str) -> ThreadingHTTPServer:
    class H(BaseHTTPRequestHandler):
        server_version = "sstack-ui"

        def log_message(self, *a):
            pass

        def _authed(self, q):
            # token only, never a cookie: a cookie would let any 127.0.0.1 page POST here (CSRF)
            return secrets.compare_digest(q.get("t", [""])[0].encode(), token.encode())

        def _loopback_host(self) -> bool:
            """A DNS-rebinding page sends its own name in Host; only our two names are ours."""
            host = (self.headers.get("Host") or "").strip().lower()
            port = self.server.server_address[1]
            return host in (f"127.0.0.1:{port}", f"localhost:{port}")

        def _gate(self, q) -> bool:
            if not self._loopback_host():
                self._error(403, "bad host")
                return False
            if not self._authed(q):
                self._error(403, "bad token")
                return False
            return True

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _error(self, code, message):
            self._send(code, {"error": message})

        def _json_body(self):
            ctype = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if ctype != "application/json":
                raise ValueError("Content-Type must be application/json")
            n = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                raise ValueError("bad JSON") from None
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
            return body

        def _static(self, path: str):
            rel = unquote(path[len("/ui/"):])
            base = (REPO / "ui").resolve()
            p = (base / rel).resolve()
            if not p.is_relative_to(base) or not p.is_file():
                return self._error(404, "not found")
            ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            self._send(200, p.read_bytes(), ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""))

        def _get(self, q):
            u = urlparse(self.path)
            if u.path in ("/", "/index.html"):
                html = (REPO / "ui" / "index.html").read_text().replace("__TOKEN__", quote(token, safe=""))
                return self._send(200, html.encode(), "text/html; charset=utf-8")
            if u.path.startswith("/ui/"):
                return self._static(u.path)
            if u.path.startswith("/api/config/"):
                try:
                    layer, kind, name = _config_route(u.path)
                    return self._send(200, _file_payload(_root(q), layer, kind, name))
                except (ValueError, KeyError, OSError) as e:
                    return self._error(400, f"{type(e).__name__}: {e}")
            fn = GETS.get(u.path)
            if not fn:
                return self._error(404, "not found")
            try:
                self._send(200, fn(q))
            except (ConfigError, ValueError, KeyError, OSError, subprocess.SubprocessError) as e:
                self._error(400, f"{type(e).__name__}: {e}")

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if not self._gate(q):
                return
            self._get(q)

        def do_POST(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if not self._gate(q):
                return
            fn = POSTS.get(u.path)
            if not fn:
                return self._error(404, "not found")
            try:
                self._send(200, fn(self._json_body()))
            except (ConfigError, ValueError, KeyError, OSError, subprocess.SubprocessError) as e:
                self._error(400, f"{type(e).__name__}: {e}")

        def _write(self, delete: bool):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if not self._gate(q):
                return
            if not u.path.startswith("/api/config/"):
                return self._error(404, "not found")
            try:
                body = {} if delete else self._json_body()
                layer, kind, name = _config_route(u.path)
                out = (_delete_config(_root(q), layer, kind, name) if delete
                       else _write_config(_root(q), layer, kind, name, body))
                self._send(200, out)
            except (ConfigError, ValueError, KeyError, OSError) as e:
                self._error(400, f"{type(e).__name__}: {e}")

        def do_PUT(self):
            self._write(False)

        def do_DELETE(self):
            self._write(True)

    return ThreadingHTTPServer(("127.0.0.1", port), H)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sstack-ui")
    ap.add_argument("--port", type=int, default=0)
    a = ap.parse_args(argv)
    token = secrets.token_urlsafe(16)
    srv = make_server(a.port, token)
    print(f"http://127.0.0.1:{srv.server_address[1]}/?t={token}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
