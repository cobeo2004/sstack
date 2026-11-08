"""sstack-ui: local dashboard. Reads and writes only the files agents use."""
import argparse
import json
import re
import secrets
import shutil
import subprocess
import sys
import time
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import sstack_lessons as L
from sstack_config import ConfigError, layer_paths, load, resolve, source_layer

REPO = Path(__file__).resolve().parent.parent
ROLES = ["scout", "investigate", "plan", "implement", "review"]
PHASES = [  # mirrors skills/work/SKILL.md
    {"n": 0, "name": "Recon", "role": "scout", "gate": "report and stop"},
    {"n": 1, "name": "Plan", "role": "plan", "gate": "plan approval + answer key"},
    {"n": 2, "name": "Implement", "role": "implement", "gate": None},
    {"n": 3, "name": "Test / fix", "role": "review", "gate": "green checks + review resolved"},
    {"n": 4, "name": "PR", "role": None, "gate": "your yes before commit/push/PR"},
]


def _toml_str(v: str) -> str:
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def replace_role_table(text: str, role: str, fields: dict[str, str]) -> str:
    block = f"[role.{role}]\n" + "".join(
        f"{k} = {_toml_str(fields[k])}\n" for k in ("harness", "model", "effort") if fields.get(k))
    lines = text.splitlines(keepends=True)
    head = re.compile(rf"^\s*\[\s*role\.{re.escape(role)}\s*\]")
    start = next((i for i, l in enumerate(lines) if head.match(l)), None)
    if start is None:
        if not text:
            return block
        return text + ("" if text.endswith("\n") else "\n") + "\n" + block
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
    # keep blank/comment lines that separate this table from the next one
    while end - 1 > start and end < len(lines) and (not lines[end - 1].strip() or lines[end - 1].lstrip().startswith("#")):
        end -= 1
    return "".join(lines[:start]) + block + "".join(lines[end:])


def _root(q) -> Path | None:
    r = q.get("repo", ["global"])[0]
    return None if r == "global" else Path(r)


def _runs(root: Path | None) -> list[dict]:
    if root is None:
        return []
    p = root / ".sstack" / "runs" / "index.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out[::-1][:200]


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
    return {"available": True, "status": (r.stdout + r.stderr).strip(), "built": (root / ".code-review-graph").exists()}


def _config(root):
    cfg = load(root)
    roles = []
    for role in ROLES:
        try:
            members, err = resolve(cfg, role), None
        except ConfigError as e:
            members, err = None, str(e)
        spec = cfg.get("role", {}).get(role, {})
        roles.append({"role": role, "members": members or [], "local": not members, "error": err,
                      "panel": "panel" in spec, "source": source_layer(root, f"role.{role}")})
    return {"roles": roles, "harnesses": sorted(cfg.get("harness", {})),
            "transport": cfg.get("transport", {}).get("mode", "auto"),
            "layers": [{"name": n, "path": str(p), "exists": p.exists()} for n, p in layer_paths(root)]}


def _overview(root):
    cfg = load(root)
    week = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 7 * 86400))
    runs = _runs(root)
    product = None
    if root and (root / ".sstack" / "product.md").exists():
        product = next((l.strip() for l in (root / ".sstack" / "product.md").read_text().splitlines()
                        if l.strip() and not l.startswith("#")), None)
    graph_db = root / ".code-review-graph" / "graph.db" if root else None
    try:
        impl = resolve(cfg, "implement")
    except ConfigError:
        impl = None
    return {"product": product,
            "lessons_pending": sum(1 for l in _lessons(root) if l["status"] == "pending"),
            "runs_week": sum(1 for r in runs if str(r.get("ts", "")) >= week),
            "implement": impl[0] if impl else None,
            "transport": cfg.get("transport", {}).get("mode", "auto"),
            "graph_updated": time.strftime("%Y-%m-%d %H:%M", time.localtime(graph_db.stat().st_mtime))
            if graph_db and graph_db.exists() else None,
            "last_run": runs[0] if runs else None}


def _workflows(root):
    cfg = load(root)
    phases = []
    for ph in PHASES:
        try:
            m = resolve(cfg, ph["role"]) if ph["role"] else None
        except ConfigError:
            m = None
        phases.append({**ph, "route": m or "local"})
    names = lambda d: sorted(p.stem for p in d.glob("*.md")) if d.is_dir() else []
    return {"phases": phases, "playbooks": names(REPO / "skills" / "work" / "playbooks"),
            "repo_playbooks": names(root / ".sstack" / "playbooks") if root else []}


def _save_role(b):
    root = None if b["repo"] == "global" else Path(b["repo"])
    layers = dict(layer_paths(root))
    if b.get("layer") not in layers or b.get("role") not in ROLES:
        raise ValueError("bad layer or role")
    p = layers[b["layer"]]
    text = p.read_text() if p.exists() else ""
    p.parent.mkdir(parents=True, exist_ok=True)
    new = replace_role_table(text, b["role"], {k: b.get(k) or None for k in ("harness", "model", "effort")})
    tomllib.loads(new)  # refuse to write a file the agents can't read (TOMLDecodeError is a ValueError → 400)
    p.write_text(new)
    load(root)  # surfaces a broken file now, not on the next agent run
    return {"ok": True, "path": str(p)}


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


def _report(root, q):
    runs = _runs(root)
    n = int(q.get("n", ["0"])[0])
    p = Path(runs[n]["report"]) if 0 <= n < len(runs) and runs[n].get("report") else None
    return {"text": p.read_text()[:200_000] if p and p.is_file() else None, "path": str(p) if p else None}


def _repos():
    f = Path.home() / ".sstack" / "repos.txt"
    lines = f.read_text().splitlines() if f.exists() else []
    return {"repos": [l.strip() for l in dict.fromkeys(lines) if l.strip() and Path(l.strip()).is_dir()]}


GETS = {"/api/repos": lambda q: _repos(), "/api/overview": lambda q: _overview(_root(q)),
        "/api/lessons": lambda q: {"lessons": _lessons(_root(q))}, "/api/config": lambda q: _config(_root(q)),
        "/api/runs": lambda q: {"runs": _runs(_root(q))}, "/api/workflows": lambda q: _workflows(_root(q)),
        "/api/graph": lambda q: _graph(_root(q)), "/api/report": lambda q: _report(_root(q), q)}
POSTS = {"/api/lessons/accept": lambda b: _lesson_action(b, "accept"),
         "/api/lessons/forget": lambda b: _lesson_action(b, "forget"),
         "/api/roles": _save_role, "/api/graph/rebuild": _rebuild}


def make_server(port: int, token: str) -> ThreadingHTTPServer:
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _authed(self, q):
            # token only, never a cookie: a cookie would let any 127.0.0.1 page POST here (CSRF)
            return secrets.compare_digest(q.get("t", [""])[0].encode(), token.encode())

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _handle(self, table, arg_fn):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if not self._authed(q):
                return self.send_error(403)
            if self.command == "GET" and u.path in ("/", "/index.html"):
                return self._send(200, (REPO / "ui" / "index.html").read_bytes(), "text/html; charset=utf-8")
            fn = table.get(u.path)
            if not fn:
                return self.send_error(404)
            try:
                self._send(200, fn(arg_fn(q)))
            except (ConfigError, ValueError, KeyError, OSError, subprocess.SubprocessError) as e:
                self._send(400, {"error": f"{type(e).__name__}: {e}"})

        def do_GET(self):
            self._handle(GETS, lambda q: q)

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self._send(400, {"error": "bad JSON"})
            self._handle(POSTS, lambda q: body)

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
