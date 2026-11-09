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

import sstack_route as R
from sstack_config import READONLY_ROLES, ConfigError, ades, git_root, load, resolve

PH = re.compile(r"\{(\w+)\}")
# The option id a T3/provider child takes effort as (recon, 2026-11-09: they differ per provider).
EFFORT_OPTION = {"codex": "reasoningEffort", "claudeAgent": "effort", "cursor": "reasoning_effort",
                 "pi": "thinking"}
T3_NO_PROJECT = "No T3 Code project matches"  # t3 thread start: cwd isn't a registered project


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
    raw = t3.get("path", "$T3CODE_CLI_PATH")
    cli = re.sub(r"\$(\w+)", lambda m: env.get(m.group(1), ""), raw)
    return cli or str(Path.home() / ".t3" / "bin" / "t3")


def t3_adapter(root: Path | None) -> dict:
    """The t3 ADE file (docs/spec/ade.md). ponytail: only its [cli] thread start is wired here;
    B2 replaces this with the generic ADE layer (exit-4 payloads)."""
    return next((a["toml"] for a in ades(root) if a["name"] == "t3"), {})


def plan_member(cfg: dict, role: str, member: dict, env: Mapping[str, str], title: str,
                t3: dict | None = None) -> dict:
    t3 = t3 or {}
    mode = {"ade-cli": "thread", "auto": "auto"}.get(cfg.get("dispatch", {}).get("via", "auto"), "headless")
    cli, provider = t3.get("cli", {}), t3.get("providers", {}).get(member["harness"])
    h = cfg["harness"][member["harness"]]
    readonly = role in READONLY_ROLES
    in_t3 = any(v in env for v in t3.get("detect", {}).get("env", []))
    notes: list[str] = []
    values = {"model": member["model"], "effort": member["effort"], "title": title}

    want_thread = mode in ("auto", "thread") and in_t3 and provider and "cmd" in cli
    if mode == "thread" and not (in_t3 and provider and "cmd" in cli):
        raise ConfigError(f"dispatch.via = ade-cli but T3 is unavailable for harness {member['harness']!r}")
    if want_thread and readonly:
        notes.append("read-only role: headless (T3 threads can't enforce read-only)")
        want_thread = False
    if want_thread:
        if member["effort"]:
            notes.append("effort dropped in T3 thread")
        values.update(cli=_t3_cli(cli, env), provider=provider, effort=None)
        return {"transport": "thread", "argv": fill(cli["cmd"], values), "notes": notes}
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


def route_json(cfg: dict, role: str, route: str, members: list[dict] | None, t3: dict) -> str:
    """The route as an orchestrator (T3 delegate_task) needs it: who runs it, and effort under
    the provider's own option id."""
    out = []
    for m in members or []:
        provider = t3.get("providers", {}).get(m["harness"], m["harness"])
        opt = EFFORT_OPTION.get(provider)
        out.append({"harness": m["harness"], "provider": provider, "model": m["model"],
                    "effort": m["effort"], "options": {opt: m["effort"]} if opt and m["effort"] else {}})
    return json.dumps({"role": role, "route": route, "readonly": role in READONLY_ROLES, "members": out},
                      indent=2)


def append_run(root: Path, record: dict) -> None:
    p = root / ".sstack" / "runs" / "index.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps(record) + "\n")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cwd = Path.cwd()
    root = git_root(cwd) or cwd
    if argv[:1] == ["routes"]:
        try:
            print(R.routes_text(load(git_root(cwd))), end="")
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
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--route", action="store_true", help="print the resolved route as JSON; runs nothing")
    a = ap.parse_args(argv)
    if not a.route and not (a.brief and a.report):
        ap.error("--brief and --report are required unless --route is given")
    title = a.title or f"sstack {a.role}"
    try:
        cfg = load(git_root(cwd))
        rules = cfg.get("rules", {})
        files, lines = list(a.files or []), 0
        if a.role == "review":  # the diff size gates the panel even when --files names the scope
            detected, lines = R.changed(root, a.base)
            files = files if a.files is not None else detected
        member, route, notes = R.pick(cfg, a.role, a.hint, files)
        t3 = t3_adapter(git_root(cwd))
        if a.role == "review" and cfg.get("dispatch", {}).get("via") != "local":
            members, route = _review_members(cfg, a, member, files, lines, rules)
        elif route == "panel":
            if a.role not in READONLY_ROLES:
                raise ConfigError(f"panel is only for read-only roles ({', '.join(sorted(READONLY_ROLES))}); "
                                  f"route {a.role} with [role.{a.role}.hint.*] or [tier.*]")
            members = resolve(cfg, a.role)
        else:
            members = [member] if member else None
        if a.route:  # before plan_member: --route runs nothing, and needs no headless command
            print(route_json(cfg, a.role, route, members, t3))
            return 0 if members else 3
        if not members:
            print("local")
            return 3
        plans = [plan_member(cfg, a.role, m, os.environ, title, t3) for m in members]
    except ConfigError as e:
        print(f"sstack-dispatch: {e}", file=sys.stderr)
        return 1

    if a.dry_run:
        print(f"route: {route}")
        for n in notes:
            print(f"  note: {n}")
        for m, pl in zip(members, plans):
            print(f"{pl['transport']}: {shlex.join(pl['argv'])}")
            for n in pl["notes"]:
                print(f"  note: {n}")
        return 0

    brief = Path(a.brief).read_text()
    base = Path(a.report).resolve()
    timeout_s = float(cfg.get("dispatch", {}).get("timeout_min", 30)) * 60
    readonly = a.role in READONLY_ROLES

    def run(m, pl, rp, text, how):
        code = _run(m, pl, rp, text, how)
        err = rp.with_name(rp.name + ".err")
        if (code == 1 and pl["transport"] == "thread" and err.exists()
                and T3_NO_PROJECT in err.read_text()):
            # a linked worktree isn't a T3 project; a thread in the primary checkout would edit
            # the wrong tree, so run headless here instead. mode = "thread" set explicitly is honoured:
            # plan_member raises and the original failure stands.
            try:
                pl2 = plan_member(cfg, a.role, m, {}, title, t3)
            except ConfigError:
                return code
            print(f"sstack-dispatch: T3 can't resolve {root} as a project; "
                  f"falling back to headless ({m['harness']}/{m['model']})", file=sys.stderr)
            code = _run(m, pl2, rp, text, how)
        return code

    def _run(m, pl, rp, text, how):
        before = _status(root) if readonly else set()
        t = time.monotonic()
        code = run_member(pl["argv"], root, text, timeout_s, rp, pl["transport"])
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
                          "route": how, "exit": code, "secs": secs, "report": str(rp)})
        return code

    if len(members) == 1:
        code = run(members[0], plans[0], base, brief, route)
        avoid = R.pick(cfg, "implement", a.hint, files)[0] if a.role == "review" else None
        up = R.escalation(cfg, members[0], avoid) if code != 0 and rules.get("auto_escalate", True) else None
        if not up:
            return code
        m2, tier = up
        failed = base.with_name(f"{base.stem}.failed{base.suffix}")
        for src, dst in ((base, failed), (base.with_name(base.name + ".err"), failed.with_name(failed.name + ".err"))):
            if src.exists():
                src.replace(dst)
        print(f"sstack-dispatch: {members[0]['harness']}/{members[0]['model']} exit {code}; "
              f"escalating once to tier.{tier} ({m2['harness']}/{m2['model']})", file=sys.stderr)
        note = (f"\n\n---\nNote: a previous attempt on a cheaper model failed (exit {code}); its report is "
                f"{failed}. The working tree may hold its partial edits: read `git diff` first and keep "
                f"only what is right.\n")
        try:
            pl2 = plan_member(cfg, a.role, m2, os.environ, title, t3)
        except ConfigError as e:
            print(f"sstack-dispatch: {e}", file=sys.stderr)
            return code
        return run(m2, pl2, base, brief + note, f"escalated from {route} → tier.{tier}")

    with ThreadPoolExecutor(int(rules.get("max_parallel", 4))) as ex:
        codes = list(ex.map(lambda mp: run(*mp, report_path(base, mp[0], len(members)), brief, route),
                            zip(members, plans)))
    lines_out = [f"# {a.role} panel\n"]
    for m, code in zip(members, codes):
        rp = report_path(base, m, len(members))
        lines_out.append(f"- {m['harness']}/{m['model']}: exit {code} → {rp if code == 0 else 'gap (no report)'}")
    base.write_text("\n".join(lines_out) + "\n")
    return 0 if any(c == 0 for c in codes) else 1


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
