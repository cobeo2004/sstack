"""sstack-dispatch: run a role's brief on its configured harness(es), capture the report."""
import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sstack_config import READONLY_ROLES, ConfigError, git_root, load, resolve

PH = re.compile(r"\{(\w+)\}")


def fill(template: list[str], values: dict[str, str | None]) -> list[str]:
    out: list[str] = []
    for el in template:
        names = PH.findall(el)
        if any(values.get(n) is None for n in names):
            if out and out[-1].startswith("-"):
                out.pop()
            continue
        out.append(PH.sub(lambda m: str(values[m.group(1)]), el))
    return out


def _t3_cli(t3: dict, env: Mapping[str, str]) -> str:
    raw = t3.get("cli", "$T3CODE_CLI_PATH")
    cli = re.sub(r"\$(\w+)", lambda m: env.get(m.group(1), ""), raw)
    return cli or str(Path.home() / ".t3" / "bin" / "t3")


def plan_member(cfg: dict, role: str, member: dict, env: Mapping[str, str], title: str) -> dict:
    tr = cfg.get("transport", {})
    mode = tr.get("mode", "auto")
    t3 = tr.get("t3", {})
    h = cfg["harness"][member["harness"]]
    readonly = role in READONLY_ROLES
    in_t3 = bool(t3.get("detect")) and t3["detect"] in env
    notes: list[str] = []
    values = {"model": member["model"], "effort": member["effort"], "title": title}

    want_thread = mode in ("auto", "thread") and in_t3 and "t3_provider" in h and "cmd" in t3
    if mode == "thread" and not (in_t3 and "t3_provider" in h and "cmd" in t3):
        raise ConfigError(f"transport.mode = thread but T3 is unavailable for harness {member['harness']!r}")
    if want_thread and readonly:
        notes.append("read-only role: headless (T3 threads can't enforce read-only)")
        want_thread = False
    if want_thread:
        if member["effort"]:
            notes.append("effort dropped in T3 thread")
        values.update(cli=_t3_cli(t3, env), provider=h["t3_provider"], effort=None)
        return {"transport": "thread", "argv": fill(t3["cmd"], values), "notes": notes}
    key = "headless_readonly" if readonly else "headless"
    if key not in h:
        raise ConfigError(f"role {role!r} is read-only but harness {member['harness']!r} has no headless_readonly")
    return {"transport": "headless", "argv": fill(h[key], values), "notes": notes}


def _status(cwd: Path) -> set[str]:
    r = subprocess.run(["git", "-C", str(cwd), "status", "--porcelain", "--untracked-files=all"],
                       capture_output=True, text=True)
    return set(r.stdout.splitlines()) if r.returncode == 0 else set()


def run_member(argv: list[str], cwd: Path, brief: str, timeout_s: float, report: Path, transport: str) -> int:
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
            p.communicate(brief, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(p.pid, sig)
                except ProcessLookupError:
                    break
                try:
                    p.wait(timeout=2)
                    break
                except subprocess.TimeoutExpired:
                    continue
            p.wait()
            return 2
    if err.stat().st_size == 0:
        err.unlink()
    if p.returncode != 0:
        return 1
    return 0 if report.stat().st_size > 0 else 1


def report_path(base: Path, member: dict, n_members: int) -> Path:
    if n_members == 1:
        return base
    slug = re.sub(r"[^A-Za-z0-9.-]", "-", member["model"] or "default")
    return base.with_name(f"{base.stem}.{member['harness']}-{slug}{base.suffix}")


def append_run(root: Path, record: dict) -> None:
    p = root / ".sstack" / "runs" / "index.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps(record) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sstack-dispatch")
    ap.add_argument("role")
    ap.add_argument("--brief", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--title")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    cwd = Path.cwd()
    root = git_root(cwd) or cwd
    title = a.title or f"sstack {a.role}"
    try:
        cfg = load(git_root(cwd))
        members = resolve(cfg, a.role)
        if members is None:
            print("local")
            return 3
        plans = [plan_member(cfg, a.role, m, os.environ, title) for m in members]
    except ConfigError as e:
        print(f"sstack-dispatch: {e}", file=sys.stderr)
        return 1

    if a.dry_run:
        for m, pl in zip(members, plans):
            print(f"{pl['transport']}: {shlex.join(pl['argv'])}")
            for n in pl["notes"]:
                print(f"  note: {n}")
        return 0

    brief = Path(a.brief).read_text()
    base = Path(a.report).resolve()
    timeout_s = float(cfg.get("transport", {}).get("timeout_min", 30)) * 60
    readonly = a.role in READONLY_ROLES
    rules = cfg.get("rules", {})

    def run(item):
        m, pl = item
        rp = report_path(base, m, len(members))
        before = _status(root) if readonly else set()
        t = time.monotonic()
        code = run_member(pl["argv"], root, brief, timeout_s, rp, pl["transport"])
        secs = round(time.monotonic() - t, 1)
        if code != 0 and len(members) > 1 and rp.exists() and rp.stat().st_size == 0:
            rp.unlink()
        if readonly and rp.exists():
            skip = [".sstack/"]
            if base.parent.is_relative_to(root) and base.parent != root:
                skip.append(f"{base.parent.relative_to(root)}/")
            elif rp.is_relative_to(root):
                skip += [str(r.relative_to(root)) for r in (rp, rp.with_name(rp.name + ".err"))]
            changed = sorted(l for l in _status(root) - before if not any(l[3:].startswith(s) for s in skip))
            if changed:
                with open(rp, "a") as f:
                    f.write("\n\nWARNING: read-only role changed the working tree:\n" + "\n".join(changed) + "\n")
        append_run(root, {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "task": title, "role": a.role,
                          "harness": m["harness"], "model": m["model"], "transport": pl["transport"],
                          "exit": code, "secs": secs, "report": str(rp)})
        return m, rp, code

    if len(members) == 1:
        return run((members[0], plans[0]))[2]
    with ThreadPoolExecutor(int(rules.get("max_parallel", 4))) as ex:
        results = list(ex.map(run, zip(members, plans)))
    lines = [f"# {a.role} panel\n"]
    for m, rp, code in results:
        lines.append(f"- {m['harness']}/{m['model']}: exit {code} → {rp if code == 0 else 'gap (no report)'}")
    base.write_text("\n".join(lines) + "\n")
    return 0 if any(c == 0 for _, _, c in results) else 1


if __name__ == "__main__":
    sys.exit(main())
