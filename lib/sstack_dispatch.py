"""sstack-dispatch (docs/spec/dispatch.md): route a role's brief to its member(s) through the active
ADE (agent-tool payload, exit 4), its hook, its [cli], or the harness headless; `record` closes a
tool-shaped run; `ade` prints the active adapter."""
import argparse
import fcntl
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import sstack_ade as A
import sstack_route as R
import sstack_skills as S
from sstack_config import READONLY_ROLES, ConfigError, ades, git_root, load, resolve

VIAS = ("auto", "headless", "local", "ade-cli")
WARNING = "\n\nWARNING: read-only role changed the working tree:\n"
INDEX = ".sstack/runs/index.jsonl"
fill, key = A.fill, A.key


def slug(model: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9.-]", "-", model or "default")


def report_base(report: Path) -> str:
    return str(report)[:-3] if str(report).endswith(".md") else str(report)


def report_path(report: Path, member: dict, n_members: int) -> Path:
    """The member's report: `--report` itself alone, `<report_base>.<harness>-<model slug>.md` in a panel."""
    return report if n_members == 1 else Path(f"{report_base(report)}.{member['harness']}-{slug(member['model'])}.md")


def rel(root: Path, p) -> str:
    p = Path(p).resolve()
    return str(p.relative_to(root)) if p.is_relative_to(root) else str(p)


def headless_argv(cfg: dict, role: str, member: dict, title: str) -> list[str]:
    h = cfg["harness"][member["harness"]]
    k = "headless_readonly" if role in READONLY_ROLES else "headless"
    if k not in h:
        raise ConfigError(f"role {role!r} is read-only but harness {member['harness']!r} has no headless_readonly")
    return fill(h[k], {"model": member["model"], "effort": member["effort"], "title": title})


def run_member(argv: list[str], cwd: Path, brief: str, deadline: float, report: Path) -> int:
    report.parent.mkdir(parents=True, exist_ok=True)
    err = report.with_name(report.name + ".err")
    with open(report, "w") as out, open(err, "w") as errf:
        try:
            # SSTACK_REFLECT=1: a child's own SessionEnd must not start another reflect pass
            p = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=out, stderr=errf, text=True,
                                 start_new_session=True, env={**os.environ, "SSTACK_REFLECT": "1"})
        except OSError as e:
            errf.write(f"cannot start {argv[0]}: {e}\n")
            return 1
        try:
            p.communicate(brief, timeout=A.left(deadline))
        except (subprocess.TimeoutExpired, A.HookTimeout):
            A.kill_group(p)
            return 2
    if err.stat().st_size == 0:
        err.unlink()
    if p.returncode != 0:
        return 1
    return 0 if report.stat().st_size > 0 else 1


# ---- run dir, read-only baseline, index ------------------------------------------------------

def _git(root: Path, *a) -> str | None:
    r = subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def _entries(status: str) -> dict[str, str]:
    """`git status --porcelain=v1 -z` → {path: XY}. A rename/copy entry is followed by its source path."""
    out, fields = {}, iter(status.split("\0"))
    for e in fields:
        if e:
            out[e[3:]] = e[:2]
            if any(c in "RC" for c in e[:2]):  # staged or worktree rename/copy carries a source path
                next(fields, None)
    return out


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def snapshot(root: Path) -> dict:
    status = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all") or ""
    files = {p: _sha((root / p).read_bytes()) if (root / p).is_file() else None for p in _entries(status)}
    idx = root / INDEX
    data = idx.read_bytes() if idx.is_file() else None
    return {"head": (_git(root, "rev-parse", "HEAD") or "").strip() or None, "status": status, "files": files,
            "index": {"size": len(data), "sha256": _sha(data)} if data is not None else None}


def _appended(root: Path, base: dict) -> bool:
    """index.jsonl only grew: its baseline content is a prefix of what is there now."""
    old, idx = base.get("index"), root / INDEX
    if not old:
        return True
    data = idx.read_bytes() if idx.is_file() else b""
    return len(data) >= old["size"] and _sha(data[:old["size"]]) == old["sha256"]


def tree_changes(root: Path, base: dict, skip: list[str]) -> list[str]:
    """Paths changed since `base` (content hash, presence, status XY), minus `skip` (paths, or dirs
    ending in "/"), and minus index.jsonl when it was only appended to; plus `HEAD old..new`."""
    now = snapshot(root)
    old_s, new_s = _entries(base["status"]), _entries(now["status"])
    gone = object()
    paths = set(old_s) | set(new_s) | set(base["files"]) | set(now["files"])
    changed = sorted(p for p in paths
                     if (old_s.get(p) != new_s.get(p) or base["files"].get(p, gone) != now["files"].get(p, gone))
                     and not any(p == s or (s.endswith("/") and p.startswith(s)) for s in skip)
                     and p != INDEX)
    if not _appended(root, base):  # checked even when .sstack/runs/ is gitignored (not in status)
        changed.append(INDEX)
    if base["head"] != now["head"]:
        changed.append(f"HEAD {base['head']}..{now['head']}")
    return changed


def readonly_check(root: Path, run_dir: Path, run: dict, report: Path) -> list[str]:
    """The baseline check (docs/spec/dispatch.md): warn in the report, never fail."""
    try:
        base = json.loads((run_dir / "baseline.json").read_text())
    except (OSError, ValueError):
        return []
    rb, n = run["report_base"], len(run["members"])
    reports = [report, root / f"{rb}.failed.md"]  # .failed.md: the escalation moved a report aside
    reports += [root / f"{rb}.{h}-{slug(m)}.md" for h, _, m in (x.partition("/") for x in run["members"])]
    if run.get("panel_report"):
        reports.append(root / run["panel_report"])
    elif n == 1:
        reports.append(root / f"{rb}.md")
    # this run's dir and every other run dir under .sstack/runs/ are sstack's; index.jsonl is checked
    # append-only in tree_changes
    skip = [rel(root, run_dir) + "/"]
    skip += [str(p.relative_to(root)) + "/" for p in (root / ".sstack" / "runs").glob("*/")]
    skip += [rel(root, p) for r in reports for p in (r, Path(str(r) + ".err"))]
    changed = tree_changes(root, base, skip)
    if changed and report.exists():
        with open(report, "a") as f:
            f.write(WARNING + "\n".join(changed) + "\n")
    return changed


def _run_parent(root: Path, report: Path) -> tuple[Path, bool]:
    """The dispatch parent: <report folder>/dispatch for a report strictly under runs/, else runs/."""
    runs = (root / ".sstack" / "runs").resolve()
    parent = report.resolve().parent
    if parent == runs or not parent.is_relative_to(runs):
        return runs, False
    if not (parent / "dispatch").resolve().is_relative_to(runs):
        return runs, False  # a symlinked dispatch/ would escape runs/: stay flat
    return parent / "dispatch", True


def _run_candidate(parent: Path, role: str, stamp: str, n: int) -> Path:
    return parent / (f"{stamp}-{role}" if n == 1 else f"{stamp}-{role}-{n}")


def planned_run_dir(root: Path, role: str, report: Path) -> Path:
    """The run dir dispatch would create, without creating anything (--route)."""
    parent, nested = _run_parent(root, report)
    stamp, n = time.strftime("%H%M" if nested else "%Y%m%d-%H%M"), 1
    while True:
        d = _run_candidate(parent, role, stamp, n)
        if not d.exists():
            return d
        n += 1


def new_run(root: Path, role: str, members: list[dict], report: Path, readonly: bool, extra: dict) -> Path:
    parent, nested = _run_parent(root, report)
    parent.mkdir(parents=True, exist_ok=True)
    stamp, n = time.strftime("%H%M" if nested else "%Y%m%d-%H%M"), 1
    while True:
        d = _run_candidate(parent, role, stamp, n)
        try:
            d.mkdir()
            break
        except FileExistsError:
            n += 1
    run = {"role": role, "members": [key(m) for m in members], "report_base": rel(root, report_base(report)),
           "panel_report": rel(root, report) if len(members) > 1 else None, "started_at": time.time(),
           "readonly": readonly, **extra}
    write_run(d, run)
    if readonly:
        (d / "baseline.json").write_text(json.dumps(snapshot(root), indent=2) + "\n")
    return d


def write_run(d: Path, run: dict) -> None:
    (d / "run.json").write_text(json.dumps(run, indent=2) + "\n")


def append_index(root: Path, line: dict) -> None:
    p = root / ".sstack" / "runs" / "index.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps(line) + "\n")


def index_line(root: Path, run_dir: Path, run: dict, rec: dict) -> None:
    """rec: member, exit, secs, report, ade, via, readonly_warning."""
    h, _, m = rec["member"].partition("/")
    append_index(root, {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "task": run.get("title") or f"sstack {run['role']}",
                        "role": run["role"], "ade": rec["ade"], "via": rec["via"], "harness": h, "model": m,
                        "exit": rec["exit"], "secs": rec["secs"], "run_dir": rel(root, run_dir),
                        "report": rel(root, rec["report"]), "route": run.get("route"),
                        "readonly_warning": rec["readonly_warning"],
                        **{k: run[k] for k in ("skills", "skills_missing") if k in run}})


def panel_index(root: Path, run_dir: Path, run: dict) -> int | None:
    """Once every member has an index line from this run dir, write the panel index (latest line
    per member) at panel_report, once (run.json `panel_written`). Returns 0/1 (any member ok) when
    written, else None."""
    if not run.get("panel_report") or run.get("panel_written"):
        return None
    rd, latest = rel(root, run_dir), {}
    p = root / ".sstack" / "runs" / "index.jsonl"
    for l in p.read_text().splitlines() if p.exists() else []:
        try:
            rec = json.loads(l)
        except ValueError:
            continue
        if rec.get("run_dir") == rd:
            latest[f"{rec['harness']}/{rec['model']}"] = rec
    if not all(m in latest for m in run["members"]):
        return None
    out = [f"# {run['role']} panel\n"]
    for m in run["members"]:
        r = latest[m]
        out.append(f"- {m}: exit {r['exit']} → {r['report'] if r['exit'] == 0 else 'gap (no report)'}")
    (root / run["panel_report"]).write_text("\n".join(out) + "\n")
    run["panel_written"] = True
    write_run(run_dir, run)
    return 0 if any(latest[m]["exit"] == 0 for m in run["members"]) else 1


# ---- exit-4 payload ----------------------------------------------------------------------------

def payload(ade: dict, role: str, members: list[dict], run_dir: str, title: str, brief: str, report: Path) -> dict:
    readonly = role in READONLY_ROLES
    calls = []
    for m in members:
        rp = str(report_path(report, m, len(members)))
        rec = " ".join(shlex.quote(x) for x in ("sstack-dispatch", "record", role, "--report", rp, "--member", key(m)))
        rec += f" --exit {{exit}} --run-dir {shlex.quote(run_dir)}"
        calls.append(A.tool_call(ade, role, readonly, m, title, brief, rp, rec))
    return {"ade": ade["name"], "role": role, "readonly": readonly, "run_dir": run_dir, "calls": calls}


def _escalate(root: Path, run_dir: Path, run: dict, failed: dict, report: Path, code: int, cfg: dict,
              isolated: bool = False):
    """Single-member run failed: (member one tier up, brief with a note), moving the failed report
    aside; None when there is nowhere to go. Escalates once per run (run.json `escalated`).
    `isolated`: the failed child worked in its own worktree, so its edits are not in this tree."""
    if run.get("escalated") or run.get("no_escalate") or len(run["members"]) != 1 or not cfg.get("rules", {}).get("auto_escalate", True):
        return None
    avoid = R.pick(cfg, "implement", run.get("hint"), [])[0] if run["role"] == "review" else None
    up = R.escalation(cfg, failed, avoid)
    if not up:
        return None
    gone = Path(f"{report_base(report)}.failed.md")
    for src, dst in ((report, gone), (Path(str(report) + ".err"), Path(str(gone) + ".err"))):
        if src.exists():
            src.replace(dst)
    print(f"sstack-dispatch: {key(failed)} exit {code}; escalating once to tier.{up[1]} ({key(up[0])})",
          file=sys.stderr)
    edits = ("Its partial edits, if any, are in its own worktree, not in this tree; start from this tree."
             if isolated else "The working tree may hold its partial edits: read `git diff` first and keep "
                              "only what is right.")
    note = (f"\n\n---\nNote: a previous attempt on a cheaper model failed (exit {code}); its report is "
            f"{gone}. {edits}\n")
    bp = root / run["brief"] if run.get("brief") else None
    brief = bp.read_text() if bp and bp.is_file() else ""
    run.update(members=[key(up[0])], escalated=True, started_at=time.time(),
               route=f"escalated from {run.get('route')} → tier.{up[1]}")
    return up[0], brief + note


def record(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="sstack-dispatch record")
    ap.add_argument("role")
    ap.add_argument("--report", required=True)
    ap.add_argument("--member", required=True, help="<harness>/<model>")
    ap.add_argument("--exit", type=int, required=True)
    ap.add_argument("--run-dir", required=True)
    a = ap.parse_args(argv)
    run_dir = Path(a.run_dir).resolve()
    ss = next((p for p in run_dir.parents if p.name == ".sstack"), None)
    runs = ss / "runs" if ss else None
    if runs is None or run_dir == runs or not run_dir.is_relative_to(runs):
        print(f"sstack-dispatch record: --run-dir {a.run_dir} is not under <repo>/.sstack/runs/", file=sys.stderr)
        return 1
    root = ss.parent
    try:
        lock = open(run_dir / "run.lock", "a")
    except OSError as e:
        print(f"sstack-dispatch record: {e}", file=sys.stderr)
        return 1
    with lock:  # members of one run record concurrently: one read-modify-write of run.json at a time
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _record(a, root, run_dir)


def _record(a, root: Path, run_dir: Path) -> int:
    try:
        run = json.loads((run_dir / "run.json").read_text())
    except (OSError, ValueError) as e:
        print(f"sstack-dispatch record: {run_dir}/run.json: {e}", file=sys.stderr)
        return 1
    if a.member not in run["members"]:
        print(f"sstack-dispatch record: {a.member} is not a member of this run ({', '.join(run['members'])})",
              file=sys.stderr)
        return 1
    report = Path(a.report).resolve()
    code = a.exit if a.exit != 0 else (0 if report.is_file() and report.stat().st_size > 0 else 1)
    warning = readonly_check(root, run_dir, run, report) if run.get("readonly") else []
    index_line(root, run_dir, run, {"member": a.member, "exit": code, "report": report, "ade": run.get("ade"),
                                    "secs": round(time.time() - run.get("started_at", time.time()), 1),
                                    "via": run.get("via", "auto"), "readonly_warning": warning})
    if code != 0:
        h, _, m = a.member.partition("/")
        try:
            cfg = load(git_root(root))
            ade = next((x for x in ades(git_root(root)) if x["name"] == run.get("ade")), None)
            isolated = not run["readonly"] and bool(ade and ade["toml"].get("delegate", {}).get("write_args", {}).get("isolation"))
            up = _escalate(root, run_dir, run, {"harness": h, "model": None if m == "default" else m, "effort": None},
                           report, code, cfg, isolated) if A.kind(ade) == "tool" else None
        except ConfigError as e:
            print(f"sstack-dispatch record: {e}", file=sys.stderr)
            up = None
        if up:
            brief = run_dir / "brief.escalated.md"
            brief.write_text(up[1])
            run["brief"] = rel(root, brief)
            write_run(run_dir, run)
            print(json.dumps(payload(ade, run["role"], [up[0]], str(run_dir), run.get("title") or f"sstack {run['role']}",
                                     str(brief), report), indent=2))
            return 4
    panel = panel_index(root, run_dir, run)
    return code if panel is None else panel


# ---- main --------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cwd = Path.cwd()
    if argv[:1] == ["record"]:
        return record(argv[1:])
    if argv[:1] in (["routes"], ["ade"]):
        try:
            cfg = load(git_root(cwd))
            print(R.routes_text(cfg), end="") if argv[0] == "routes" else \
                print(json.dumps(A.describe(*A.active(git_root(cwd), cfg, os.environ)), indent=2))
        except ConfigError as e:
            print(f"sstack-dispatch: {e}", file=sys.stderr)
            return 1
        return 0
    ap = argparse.ArgumentParser(prog="sstack-dispatch")
    ap.add_argument("role")
    ap.add_argument("--brief")
    ap.add_argument("--report")
    ap.add_argument("--title")
    ap.add_argument("--hint", help="a config hint or a built-in kind (sstack-dispatch routes)")
    ap.add_argument("--files", nargs="*", help="files the work touches; review defaults to git diff")
    ap.add_argument("--base", default="HEAD", help="review: diff base for detection")
    ap.add_argument("--panel", action="store_true", help="review: force the full panel")
    ap.add_argument("--via", choices=VIAS, help="beats [dispatch] via")
    ap.add_argument("--no-escalate", action="store_true", help="never retry a failed member one tier up")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--route", action="store_true", help="print the exit-4 payload shape; creates nothing")
    a = ap.parse_args(argv)
    if not a.route and not (a.brief and a.report):
        ap.error("--brief and --report are required unless --route is given")
    title = a.title or f"sstack {a.role}"
    gr = git_root(cwd)
    root = gr or cwd
    readonly = a.role in READONLY_ROLES
    try:
        cfg = load(gr)
        via = a.via or cfg.get("dispatch", {}).get("via", "auto")
        cfg.setdefault("dispatch", {})["via"] = via  # route.pick / resolve read it (local → exit 3)
        rules = cfg.get("rules", {})
        files, lines = list(a.files or []), 0
        if a.role == "review":  # the diff size gates the panel even when --files names the scope
            detected, lines = R.changed(root, a.base)
            files = files if a.files is not None else detected
        member, route, notes = R.pick(cfg, a.role, a.hint, files)
        if a.role == "review" and via != "local":
            members, route = _review_members(cfg, a, member, files, lines, rules)
        elif route == "panel":
            if not readonly:
                raise ConfigError(f"panel is only for read-only roles ({', '.join(sorted(READONLY_ROLES))}); "
                                  f"route {a.role} with roles/{a.role}.toml [hint.*] or tiers/*.toml")
            members = resolve(cfg, a.role)
        else:
            members = [member] if member else None
        ade, why = A.active(gr, cfg, os.environ) if via in ("auto", "ade-cli") else (None, f"via {via}")
        # the whitelist: only via = ade-cli ever runs the adapter's [cli] (T3: a new top-level thread)
        shape = {"tool": "tool", "hook": "hook", "none": "headless"}[A.kind(ade)] if via == "auto" else \
            "ade-cli" if via == "ade-cli" else "headless"
        if a.route:
            report = Path(a.report).resolve() if a.report else Path("<REPORT>")
            run_dir = str(planned_run_dir(root, a.role, report) if a.report else
                          root / ".sstack" / "runs" / f"{time.strftime('%Y%m%d-%H%M')}-{a.role}")
            if shape == "tool" and members:
                p = payload(ade, a.role, members, run_dir, title,
                            str(Path(a.brief).resolve()) if a.brief else "<BRIEF>", report)
            else:
                p = {"ade": ade and ade["name"], "role": a.role, "readonly": readonly, "run_dir": run_dir,
                     "calls": [{"member": key(m), "via": shape} for m in members or []]}
            print(json.dumps({**p, "route": route}, indent=2))
            return 0 if members else 3
        # the union: role + kind + [practices] by path; local work gets every harness's skill dirs
        # ponytail: one brief per run, so a panel's members share the union of their harnesses' dirs
        kind = a.hint if a.hint in {**R.kind_tiers(cfg), **cfg.get("skills", {}).get("kinds", {})} else R.classify(files)
        harnesses = [m["harness"] for m in members] if members else list(cfg.get("harness", {}))
        found, missing = S.resolve(cfg, root, a.role, kind, files, list(dict.fromkeys(harnesses)))
        if not members:
            print("\n".join(["local", *S.lines(found, missing)]))
            return 3

        def plan(m: dict) -> list[str]:
            return A.cli_argv(ade, m, title, os.environ) if shape == "ade-cli" else headless_argv(cfg, a.role, m, title)

        # argv up front, once: config errors surface before anything runs
        plans = {key(m): plan(m) for m in members} if shape in ("headless", "ade-cli") else {}
    except ConfigError as e:
        print(f"sstack-dispatch: {e}", file=sys.stderr)
        return 1

    if a.dry_run:
        print(f"route: {route}")
        print(f"ade: {ade['name'] if ade else None} ({why})")
        for n in notes:
            print(f"  note: {n}")
        for l in S.lines(found, missing):
            print(l)
        for m in members:
            if shape == "tool":
                c = A.tool_call(ade, a.role, readonly, m, title, str(Path(a.brief).resolve()),
                                str(Path(a.report).resolve()), "")
                print(f"tool {c['tool']}: {json.dumps(c['args'])}" + (f"\n  note: {c['note']}" if "note" in c else ""))
            elif shape == "hook":
                print(f"hook: {ade['hook_path']} delegate ({key(m)})")
            else:
                print(f"{shape}: {shlex.join(plans[key(m)])}")
        return 0

    brief_p = Path(a.brief).resolve()
    report = Path(a.report).resolve()
    ade_name = ade["name"] if ade and shape != "headless" else None
    run_dir = new_run(root, a.role, members, report, readonly,
                      {"title": title, "brief": rel(root, brief_p), "route": route, "ade": ade_name,
                       "via": "headless" if shape == "headless" else via, "hint": a.hint,
                       "no_escalate": a.no_escalate})
    run = json.loads((run_dir / "run.json").read_text())
    if found or missing:  # a derived brief, like brief.escalated.md; escalation reuses run["brief"]
        for n in missing:
            print(f"sstack-dispatch: skill {n} not found", file=sys.stderr)
        brief_p = run_dir / "brief.skills.md"
        brief_p.write_text((root / run["brief"]).read_text() + S.section(found, missing))
        run.update(brief=rel(root, brief_p), skills=[n for n, _ in found], skills_missing=missing)
        write_run(run_dir, run)
    report.parent.mkdir(parents=True, exist_ok=True)  # ADE children write the report themselves
    if shape == "tool":
        print(json.dumps(payload(ade, a.role, members, str(run_dir), title, str(brief_p), report), indent=2))
        return 4

    brief = brief_p.read_text()
    timeout_s = float(cfg.get("dispatch", {}).get("timeout_min", 30)) * 60

    def member(m: dict, text: str, deadline: float, rp: Path) -> tuple[int, str | None, str]:
        """(exit, ade used, via) for one member; one deadline across delegate → run → wait → collect."""
        if shape != "hook":
            return run_member(plans[key(m)], root, text, deadline, rp), ade_name, run["via"]
        state = run_dir / f"hook.{m['harness']}-{slug(m['model'])}"
        state.mkdir(exist_ok=True)
        stdin = {"role": a.role, "readonly": readonly, "member": key(m), "brief": str(brief_p),
                 "report": str(rp), "cwd": str(root), "title": title}
        try:
            act, note = A.delegate(ade, stdin, state, os.environ, deadline)
        except A.HookTimeout:
            return 2, ade_name, run["via"]
        if act is None:
            print(f"sstack-dispatch: note: {note}", file=sys.stderr)
            try:
                argv = headless_argv(cfg, a.role, m, title)
            except ConfigError as e:
                print(f"sstack-dispatch: {e}", file=sys.stderr)
                return 1, None, "headless"
            return run_member(argv, root, text, deadline, rp), None, "headless"
        if act["action"] == "run":
            return run_member(act["argv"], root, text, deadline, rp), ade_name, run["via"]
        return A.run_async(ade, str(act["id"]), state, os.environ, deadline, rp), ade_name, run["via"]

    def go(m: dict, text: str) -> int:
        rp = report_path(report, m, len(run["members"]))
        t = time.monotonic()
        try:
            code, used, how = member(m, text, t + timeout_s, rp)
        except Exception as e:  # one member's crash must not lose the others' records or the panel index
            print(f"sstack-dispatch: {key(m)}: {type(e).__name__}: {e}", file=sys.stderr)
            code, used, how = 1, ade_name, run["via"]
        if code != 0 and len(run["members"]) > 1 and rp.exists() and rp.stat().st_size == 0:
            rp.unlink()
        warning = readonly_check(root, run_dir, run, rp) if readonly else []
        index_line(root, run_dir, run, {"member": key(m), "exit": code, "secs": round(time.monotonic() - t, 1),
                                        "report": rp, "ade": used, "via": how, "readonly_warning": warning})
        return code

    if len(members) == 1:
        code = go(members[0], brief)
        if code == 0:
            return 0
        try:
            up = _escalate(root, run_dir, run, members[0], report, code, cfg)
            if up and shape in ("headless", "ade-cli"):
                plans[key(up[0])] = plan(up[0])
        except ConfigError as e:
            print(f"sstack-dispatch: {e}", file=sys.stderr)
            return code
        if not up:
            return code
        write_run(run_dir, run)
        return go(up[0], up[1])

    with ThreadPoolExecutor(int(rules.get("max_parallel", 4))) as ex:
        codes = list(ex.map(lambda m: go(m, brief), members))
    panel = panel_index(root, run_dir, run)
    return panel if panel is not None else (0 if any(c == 0 for c in codes) else 1)


def _review_members(cfg, a, picked, files, lines, rules):
    """One reviewer by default; the full panel for risky kinds, big diffs, --panel or mode=panel."""
    spec = cfg.get("role", {}).get("review") or {}
    mode = spec.get("mode", "auto")
    kind = a.hint if a.hint in R.KIND_TIER else R.classify(files)
    big = lines > int(rules.get("panel_diff_lines", 400))
    reason = ("--panel" if a.panel else "mode=panel" if mode == "panel" else
              kind if mode == "auto" and kind in R.PANEL_KINDS else
              f"diff {lines} lines" if mode == "auto" and big else None)
    impl = None
    if rules.get("review_not_implementer", True):
        impl, _, _ = R.pick(cfg, "implement", a.hint, files)
    if reason and "panel" in spec:
        panel = [m for m in resolve(cfg, "review") or [] if not R.same(m, impl)]
        return panel, f"panel ({reason})"
    candidates = [picked] + [R._member(cfg, x) for x in spec.get("panel", [])] + [R.tier_member(cfg, "strong")]
    for c in candidates:
        if c and not R.same(c, impl):
            return [c], "single" + (f" ({reason}, no panel configured)" if reason else "")
    return [], "local"
