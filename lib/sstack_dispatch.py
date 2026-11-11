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
import sstack_workflow as W
from sstack_config import READONLY_ROLES, VARIANT_STAGES, ConfigError, ades, git_root, load, resolve, variants

VIAS = ("auto", "headless", "local", "ade-cli")
WARNING = "\n\nWARNING: read-only role changed the working tree:\n"
INDEX = ".sstack/runs/index.jsonl"
RUNS = ".sstack/runs"
LOCK = "implement.lock"  # the per-checkout write lock (docs/spec/dispatch.md)
OURS = {INDEX, f"{RUNS}/{LOCK}", f"{RUNS}/{LOCK}.mutex", f"{RUNS}/{LOCK}.tmp"}  # never a warning
fill, key, unkey = A.fill, A.key, A.unkey


def slug(model: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9.-]", "-", model or "default")


def report_base(report: Path) -> str:
    return str(report)[:-3] if str(report).endswith(".md") else str(report)


def report_path(report: Path, member: dict, members: list[dict]) -> Path:
    """The member's report: `--report` itself alone, `<report_base>.<harness>-<model slug>.md` in a panel.
    A stage variant's member writes `<report_base>-<name>.md` (`…-<name>.<harness>-<model slug>.md` in
    a variant panel); only members of the same variant (or the default) count as its panel."""
    v = member.get("variant")
    base = report_base(report) + (f"-{v.partition('/')[2]}" if v else "")
    if sum(m.get("variant") == v for m in members) == 1:
        return Path(base + ".md") if v else report
    return Path(f"{base}.{member['harness']}-{slug(member['model'])}.md")


def max_parallel(cfg: dict) -> int:
    return int(cfg.get("rules", {}).get("max_parallel", 4))


def step_cap(step: dict | None, cfg: dict) -> int:
    """A step's cap: min(max_agents, rules.max_parallel). No --step → rules.max_parallel, as before."""
    return min(int(step["max_agents"]), max_parallel(cfg)) if step else max_parallel(cfg)


def isolates(ade: dict | None, members: list[dict] = ()) -> bool:
    """The ADE runs write children in their own checkout: [delegate.write_args] isolation, and every
    member is one it hosts (a shell child edits this tree)."""
    return bool(ade and A.kind(ade) == "tool"
                and ade["toml"].get("delegate", {}).get("write_args", {}).get("isolation")
                and all(A.native(ade, m) for m in members))


def rel(root: Path, p) -> str:
    p = Path(p).resolve()
    return str(p.relative_to(root)) if p.is_relative_to(root) else str(p)


# ---- write lock, one writer per checkout (docs/spec/dispatch.md) --------------------------------

def lock_owner(root: Path, report: Path) -> str:
    """The task run folder `--report` sits in, relative to the repo root: `.sstack/runs/<task>` for
    a report anywhere below it, else the report's own folder (a flat dispatch). The same string
    sstack_workflow.release() computes from its `--run`."""
    runs, parent = (root / RUNS).resolve(), report.resolve().parent
    if parent == runs or parent.is_relative_to(runs):
        parts = parent.relative_to(runs).parts
        return rel(root, runs / parts[0]) if parts else rel(root, RUNS)
    return rel(root, parent)


def lock_cap(step: dict | None) -> int:
    """The lock's cap: the `--step`'s max_agents (inline 0 counts as 1), else one writer per checkout."""
    return max(1, int(step["max_agents"])) if step else 1


def _lock_read(p: Path) -> dict:
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        return {"holders": []}
    return data if isinstance(data, dict) and isinstance(data.get("holders"), list) else {"holders": []}


def _lock_write(p: Path, data: dict) -> None:
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, p)


def _mutex(root: Path):
    """`<runs>/implement.lock.mutex`, held for one short read-modify-write of the holder list: the
    same lock sstack_workflow.release() takes through lock_release(). Closing the file releases it."""
    p = root / RUNS / f"{LOCK}.mutex"
    p.parent.mkdir(parents=True, exist_ok=True)
    while True:
        f = open(p, "a")
        fcntl.flock(f, fcntl.LOCK_EX)
        try:  # release may have unlinked it while we waited: retry on the file now at that path
            if os.stat(p).st_ino == os.fstat(f.fileno()).st_ino:
                return f
        except FileNotFoundError:
            pass
        f.close()


def _overlaps(files: list[str] | None, held: list[str] | None) -> bool:
    """Two `--files` sets touch the same path (or one names a folder of the other). An empty side is
    unknown, so it counts as overlap: only provably disjoint files run together."""
    a = [f.removeprefix("./").rstrip("/") for f in files or [] if f]
    b = [f.removeprefix("./").rstrip("/") for f in held or [] if f]
    return not a or not b or any(x == y or x.startswith(y + "/") or y.startswith(x + "/")
                                 for x in a for y in b)


def lock_acquire(root: Path, owner: str, run: str, role: str, files: list[str], cap: int,
                 isolated: bool, timeout_s: float, local: bool = True) -> dict | None:
    """Take this checkout's write lock for `owner`: None once held, else the holder that blocks it.
    Holders older than `[dispatch] timeout_min` are dropped first. The same owner reuses its holder
    (one orchestrator never waits on itself); another owner is refused when the ADE does not isolate
    write children, the cap is reached, or `--files` overlap. `local` (exit 3, this session does the
    work) marks the holder so `sstack-workflow done` counts it; a child's holder waits for `record`."""
    p, now = root / RUNS / LOCK, time.time()
    with _mutex(root):
        data = _lock_read(p)
        live = [h for h in data["holders"]
                if isinstance(h, dict) and now - float(h.get("started") or 0) <= timeout_s]
        if not any(h.get("owner") == owner for h in live):
            blocker = next((h for h in live if
                            not isolated or len(live) >= cap or _overlaps(files, h.get("files"))), None)
            if blocker:
                _lock_write(p, {**data, "holders": live})
                return blocker
            live.append({"owner": owner, "run": run, "role": role, "files": list(files), "started": now})
        for h in live:
            if h.get("owner") == owner:
                h["local"] = local
        _lock_write(p, {**data, "holders": live})
    return None


def _other_writers(root: Path, report: Path, cfg: dict) -> bool:
    """A live write-lock holder that is not this report's run."""
    ttl, owner = float(cfg.get("dispatch", {}).get("timeout_min", 30)) * 60, lock_owner(root, report)
    return any(isinstance(h, dict) and h.get("owner") != owner and time.time() - float(h.get("started") or 0) <= ttl
               for h in _lock_read(root / RUNS / LOCK)["holders"])


def lock_release(root: Path, owner: str) -> None:
    """Drop this owner's holders so the next dispatch into this checkout starts. An empty holder
    list removes the lock and its mutex, leaving the runs folder as record found it."""
    p = root / RUNS / LOCK
    if not p.is_file():
        return
    m = _mutex(root)
    try:
        data = _lock_read(p)
        keep = [h for h in data["holders"] if not isinstance(h, dict) or h.get("owner") != owner]
        if len(keep) == len(data["holders"]):
            return
        if keep:
            _lock_write(p, {**data, "holders": keep})
        else:
            p.unlink(missing_ok=True)
            (root / RUNS / f"{LOCK}.mutex").unlink(missing_ok=True)  # _mutex re-checks the inode
    finally:
        m.close()


def busy_line(h: dict) -> str:
    """The exit-5 line: which run holds this checkout, on which files, and that nothing ran."""
    files = " ".join(h.get("files") or []) or "-"
    return f"BUSY: {h.get('run') or h.get('owner')} {files}; nothing started"


def headless_argv(cfg: dict, role: str, member: dict, title: str) -> list[str]:
    h = cfg["harness"][member["harness"]]
    k = "headless_readonly" if role in READONLY_ROLES else "headless"
    if k not in h:
        raise ConfigError(f"role {role!r} is read-only but harness {member['harness']!r} has no headless_readonly")
    return fill(h[k], {"model": member["model"], "effort": member["effort"], "title": title})


def shell_command(cfg: dict, root: Path, role: str, member: dict, title: str, brief: str, report: str) -> str:
    """run_member() as one shell line: the member's headless argv in `root`, brief on stdin."""
    q = shlex.quote
    return (f"cd {q(str(root))} && SSTACK_REFLECT=1 {shlex.join(headless_argv(cfg, role, member, title))} "
            f"< {q(brief)} > {q(report)} 2> {q(report + '.err')}")


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
                     and p not in OURS)
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
    ms = [unkey(k) for k in run["members"]]
    reports = [report, root / f"{rb}.failed.md"]  # .failed.md: the escalation moved a report aside
    reports += [root / f"{rb}.{m['harness']}-{slug(m['model'])}.md" for m in ms]
    reports += [report_path(root / f"{rb}.md", m, ms) for m in ms]  # variant reports
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
    # the panel index sits at --report for a default panel; beside it when only variants made a panel
    plain = sum(not m.get("variant") for m in members)
    panel = report if plain > 1 else Path(f"{report_base(report)}.panel.md") if len(members) > 1 else None
    run = {"role": role, "members": [key(m) for m in members], "report_base": rel(root, report_base(report)),
           "panel_report": rel(root, panel) if panel else None, "started_at": time.time(),
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
    hm, _, v = rec["member"].partition("#")
    h, _, m = hm.partition("/")
    append_index(root, {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "task": run.get("title") or f"sstack {run['role']}",
                        "role": run["role"], "ade": rec["ade"], "via": rec["via"], "harness": h, "model": m,
                        **({"variant": v} if v else {}),
                        "exit": rec["exit"], "secs": rec["secs"], "run_dir": rel(root, run_dir),
                        "report": rel(root, rec["report"]), "route": run.get("route"),
                        "readonly_warning": rec["readonly_warning"],
                        **{k: run[k] for k in ("skills", "skills_missing") if k in run}})


def _latest(root: Path, run_dir: Path) -> dict:
    """The latest index line per member key from this run dir."""
    rd, latest = rel(root, run_dir), {}
    p = root / ".sstack" / "runs" / "index.jsonl"
    for l in p.read_text().splitlines() if p.exists() else []:
        try:
            rec = json.loads(l)
        except ValueError:
            continue
        if rec.get("run_dir") == rd:
            latest[f"{rec['harness']}/{rec['model']}" + (f"#{rec['variant']}" if rec.get("variant") else "")] = rec
    return latest


def panel_index(root: Path, run_dir: Path, run: dict) -> int | None:
    """Once every member has an index line from this run dir, write the panel index (latest line
    per member) at panel_report, once (run.json `panel_written`). Returns 0/1 (any member ok) when
    written, else None."""
    if not run.get("panel_report") or run.get("panel_written"):
        return None
    latest = _latest(root, run_dir)
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

def member_call(ade: dict, cfg: dict, root: Path, role: str, m: dict, title: str, brief: str, rp: str,
                rec: str) -> dict:
    """One member's tool call: the ADE's agent tool, or its shell tool for a member it can't host."""
    cmd = None if A.native(ade, m) else shell_command(cfg, root, role, m, title, brief, rp)
    return A.tool_call(ade, role, role in READONLY_ROLES, m, title, brief, rp, rec, cmd)


def payload(ade: dict, role: str, members: list[dict], run_dir: str, title: str, brief: str, report: Path,
            cap: int, briefs: dict | None = None, cfg: dict | None = None, root: Path | None = None) -> dict:
    """`briefs`: member key → its own brief (a stage variant's, with its lens); `cap`: max_parallel;
    `cfg` and `root`: for a member the ADE hosts as a shell command."""
    readonly = role in READONLY_ROLES
    calls = []
    for m in members:
        rp = str(report_path(report, m, members))
        rec = " ".join(shlex.quote(x) for x in ("sstack-dispatch", "record", role, "--report", rp, "--member", key(m)))
        rec += f" --exit {{exit}} --run-dir {shlex.quote(run_dir)}"
        calls.append(member_call(ade, cfg, root, role, m, title, str((briefs or {}).get(key(m), brief)), rp, rec))
    return {"ade": ade["name"], "role": role, "readonly": readonly, "run_dir": run_dir, "max_parallel": cap,
            "calls": calls}


def _escalate(root: Path, run_dir: Path, run: dict, failed: dict, report: Path, code: int, cfg: dict,
              isolated: bool = False, ade: dict | None = None):
    """The run's single default member failed (stage variants don't count, and never escalate):
    (member one tier up, brief with a note), moving the failed report aside; None when there is
    nowhere to go. Escalates once per run (run.json `escalated`).
    `isolated`: the failed child worked in its own worktree, so its edits are not in this tree."""
    if run.get("escalated") or run.get("no_escalate") or failed.get("variant") or \
            sum("#" not in k for k in run["members"]) != 1 or not cfg.get("rules", {}).get("auto_escalate", True):
        return None
    avoid = R.pick(cfg, "implement", run.get("hint"), [])[0] if run["role"] == "review" else None
    up = R.escalation(cfg, failed, avoid)
    if not up:
        return None
    if isolated and ade and not isolates(ade, [up[0]]) and _other_writers(root, report, cfg):
        # checked before the run changes: the next tier is a shell child in this tree, beside another
        # live writer; the failure stands and the last record below frees this run's holder
        print(f"sstack-dispatch record: not escalated to {key(up[0])}: it would edit this checkout while "
              "another run's writer holds it; re-dispatch once that run records its step", file=sys.stderr)
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
    run.update(members=[key(up[0]) if k == key(failed) else k for k in run["members"]], escalated=True, started_at=time.time(),
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
        failed = unkey(a.member)
        try:
            cfg = load(git_root(root))
            ade = next((x for x in ades(git_root(root)) if x["name"] == run.get("ade")), None)
            isolated = not run["readonly"] and isolates(ade, [failed])
            up = _escalate(root, run_dir, run, failed, report, code, cfg, isolated, ade) if A.kind(ade) == "tool" else None
        except ConfigError as e:
            print(f"sstack-dispatch record: {e}", file=sys.stderr)
            up = None
        if up:
            brief = run_dir / "brief.escalated.md"
            brief.write_text(up[1])
            run["brief"] = rel(root, brief)
            write_run(run_dir, run)
            print(json.dumps(payload(ade, run["role"], [up[0]], str(run_dir),
                                     run.get("title") or f"sstack {run['role']}", str(brief), report,
                                     int(run.get("max_agents", max_parallel(cfg))), None, cfg, root), indent=2))
            return 4
    panel = panel_index(root, run_dir, run)
    code = code if panel is None else panel
    if all(m in _latest(root, run_dir) for m in run["members"]):
        lock_release(root, lock_owner(root, report))  # the run's last record frees the checkout
    return code


# ---- main --------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cwd = Path.cwd()
    if argv[:1] == ["record"]:
        return record(argv[1:])
    if argv[:1] in (["routes"], ["ade"]):
        try:
            cfg = load(git_root(cwd))
            print(R.routes_text(cfg, variants(git_root(cwd))), end="") if argv[0] == "routes" else \
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
    ap.add_argument("--step", help="a step folder (docs/spec/workflow.md): role, default brief, max_agents")
    a = ap.parse_args(argv)
    if not a.route and not (a.brief and a.report) and not a.step:
        ap.error("--brief and --report are required unless --route or --step is given")
    gr = git_root(cwd)
    root = gr or cwd
    locked = False
    try:
        cfg = load(gr)
        step = None
        if a.step:  # the step folder supplies the role, the default brief and the cap
            specs = W.resolved(root)["steps"]
            if a.step not in specs:
                raise ConfigError(f"--step {a.step}: no steps/{a.step}/ in any layer")
            step = specs[a.step]
            a.role = step["role"] or a.role  # gate has no role of its own: the CLI's stands
            a.brief = a.brief or step["brief"]
        if not a.route and not a.report:
            ap.error("--report is required unless --route is given")
        if not a.route and not a.brief:
            raise ConfigError(f"--step {a.step}: no brief.md in its folder; pass --brief")
        title = a.title or f"sstack {a.role}"
        readonly = a.role in READONLY_ROLES
        cap = step_cap(step, cfg)
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
        vs = {}  # variant id → variant, for the ones that matched and kept a member
        if members and a.role in VARIANT_STAGES:
            members, vs = _add_variants(cfg, gr, a, members, files, rules)
        if step and step["max_agents"] == 0:  # inline: the agent does the step itself, no subagent
            members, vs = None, {}
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
                            str(Path(a.brief).resolve()) if a.brief else "<BRIEF>", report, cap, None, cfg, root)
            else:
                p = {"ade": ade and ade["name"], "role": a.role, "readonly": readonly, "run_dir": run_dir,
                     "calls": [{"member": key(m), "via": shape} for m in members or []]}
            print(json.dumps({**p, "route": route}, indent=2))
            return 0 if members else 3
        # the write lock: one writer per checkout, whatever runs it (docs/spec/dispatch.md)
        timeout_s = float(cfg.get("dispatch", {}).get("timeout_min", 30)) * 60
        if not readonly and not a.dry_run:
            report = Path(a.report).resolve()
            blocker = lock_acquire(root, lock_owner(root, report), rel(root, planned_run_dir(root, a.role, report)),
                                   a.role, files, lock_cap(step), isolates(ade, members or []), timeout_s,
                                   not members)
            if blocker:
                print(busy_line(blocker), file=sys.stderr)
                return 5
            locked = True
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
        if locked:
            lock_release(root, lock_owner(root, Path(a.report).resolve()))
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
                c = member_call(ade, cfg, root, a.role, m, title, str(Path(a.brief).resolve()),
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
                       "no_escalate": a.no_escalate, "step": a.step, "max_agents": cap})
    run = json.loads((run_dir / "run.json").read_text())
    if found or missing:  # a derived brief, like brief.escalated.md; escalation reuses run["brief"]
        for n in missing:
            print(f"sstack-dispatch: skill {n} not found", file=sys.stderr)
        brief_p = run_dir / "brief.skills.md"
        brief_p.write_text((root / run["brief"]).read_text() + S.section(found, missing))
        run.update(brief=rel(root, brief_p), skills=[n for n, _ in found], skills_missing=missing)
        write_run(run_dir, run)
    briefs = {}  # member key → a variant's own brief: the run's brief + its skills + its lens
    for vid, v in vs.items():
        vms = [m for m in members if m.get("variant") == vid]
        text = brief_p.read_text()
        if v["spec"].get("skills"):
            vf, vmiss = S.resolve(cfg, root, a.role, None, files, [m["harness"] for m in vms], v["spec"]["skills"])
            text += S.section(vf, vmiss)
        if v["lens_path"]:
            text += f"\n\n## Lens: {vid}\n\n{v['lens_path'].read_text()}"
        bp = run_dir / f"brief.variant-{v['name']}.md"
        bp.write_text(text)
        briefs.update({key(m): bp for m in vms})
    report.parent.mkdir(parents=True, exist_ok=True)  # ADE children write the report themselves
    if shape == "tool":
        print(json.dumps(payload(ade, a.role, members, str(run_dir), title, str(brief_p), report, cap, briefs, cfg, root),
                         indent=2))
        return 4

    brief = brief_p.read_text()

    def finish(code: int) -> int:
        """Headless, hook and ade-cli work ended here: nothing outlives it, so free the checkout."""
        if locked:
            lock_release(root, lock_owner(root, report))
        return code

    def member(m: dict, text: str, deadline: float, rp: Path) -> tuple[int, str | None, str]:
        """(exit, ade used, via) for one member; one deadline across delegate → run → wait → collect."""
        if shape != "hook":
            return run_member(plans[key(m)], root, text, deadline, rp), ade_name, run["via"]
        v = m.get("variant")
        state = run_dir / (f"hook.{m['harness']}-{slug(m['model'])}" + (f"-{v.partition('/')[2]}" if v else ""))
        state.mkdir(exist_ok=True)
        stdin = {"role": a.role, "readonly": readonly, "member": key(m), "brief": str(briefs.get(key(m), brief_p)),
                 "report": str(rp), "cwd": str(root), "title": title, **({"variant": v} if v else {})}
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
        rp = report_path(report, m, members)
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
            return finish(0)
        try:
            up = _escalate(root, run_dir, run, members[0], report, code, cfg)
            if up and shape in ("headless", "ade-cli"):
                plans[key(up[0])] = plan(up[0])
        except ConfigError as e:
            print(f"sstack-dispatch: {e}", file=sys.stderr)
            return finish(code)
        if not up:
            return finish(code)
        write_run(run_dir, run)
        return finish(go(up[0], up[1]))

    with ThreadPoolExecutor(cap) as ex:  # variants count against the same cap
        codes = list(ex.map(lambda m: go(m, briefs[key(m)].read_text() if key(m) in briefs else brief), members))
    defaults = [i for i, m in enumerate(members) if not m.get("variant")]
    if len(defaults) == 1 and codes[defaults[0]] != 0:  # variants alongside: the default still escalates
        i = defaults[0]
        try:
            up = _escalate(root, run_dir, run, members[i], report, codes[i], cfg)
            if up and shape in ("headless", "ade-cli"):
                plans[key(up[0])] = plan(up[0])
        except ConfigError as e:
            print(f"sstack-dispatch: {e}", file=sys.stderr)
            up = None
        if up:
            write_run(run_dir, run)
            members[i] = up[0]
            codes[i] = go(up[0], up[1])
    panel = panel_index(root, run_dir, run)
    return finish(panel if panel is not None else (0 if any(c == 0 for c in codes) else 1))


def _add_variants(cfg, root, a, members, files, rules):
    """(default members + matching variants' members, {variant id: variant}). A review's variant
    member equal to the implementer (roles/implement.toml, or the one routed for these files) is
    dropped."""
    impls = []
    if a.role == "review" and rules.get("review_not_implementer", True):
        impls = [(resolve(cfg, "implement") or [None])[0], R.pick(cfg, "implement", a.hint, files)[0]]
    vs = {}
    for v in variants(root):
        if v["stage"] == a.role and R.matches(v, files):
            vms = [m for m in R.variant_members(cfg, v) if not any(R.same(m, i) for i in impls)]
            if vms:
                members, vs[v["id"]] = members + vms, v
    return members, vs


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
