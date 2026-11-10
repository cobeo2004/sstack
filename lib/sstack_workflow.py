"""sstack-workflow (docs/spec/workflow.md): resolve the step chain from `steps/<name>/` folders,
track a run's place in it (`status`, `done`) and run a command step (`run`). It never launches an
agent: the agent follows the chain the tool prints."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import sstack_config as C

REPO = Path(__file__).resolve().parent.parent
GATE = "GATE: wait for the user's yes"
STOP = "STOP: ask user"
IMPORTANT = "important"


def kind(s: dict) -> str:
    """The file present decides the kind: run.sh → command, brief.md → role. A built-in role step
    carries no brief.md (the orchestrator writes the task brief), so a role with no files is a role
    step too; a built-in with neither is inline (the orchestrator runs it itself)."""
    return "command" if s["run"] else ("role" if s["brief"] or s["spec"].get("role") else "inline")


def enabled(specs: dict) -> set[str]:
    return {n for n, s in specs.items() if s["spec"].get("enabled", True) is not False}


def _kids(specs: dict) -> dict[str, list[str]]:
    """{after: [step]}, each `after` resolved past disabled steps; a target's inserted steps come
    first, by name, then its declared successor."""
    on = enabled(specs)
    kids: dict[str, list[str]] = {}
    for n in on:
        a = specs[n]["spec"].get("after") or ""
        seen = set()
        while a and a in specs and a not in on and a not in seen:
            seen.add(a)
            a = specs[a]["spec"].get("after") or ""
        kids.setdefault(a, []).append(n)
    for v in kids.values():
        v.sort(key=lambda n: (specs[n]["builtin"], n))
    return kids


def order(specs: dict) -> list[str]:
    """The chain from the one first step (`after = ""`): each step sits immediately after its target.
    Steps a cycle leaves out are not listed; doctor FAILs that config."""
    kids, out, seen = _kids(specs), [], set()

    def walk(parent: str) -> None:
        for n in kids.get(parent, []):
            if n not in seen:
                seen.add(n)
                out.append(n)
                walk(n)

    walk("")
    return out


def resolved(root: Path | None) -> dict:
    """{"chain": [name], "steps": {name: {role, gate, on_fail, max_loops, max_agents, min_score,
    kind, brief, run, source}}} — the workflow this repo's layers describe, with `rules.loop_guard`
    as the default max_loops."""
    specs = C.steps(root)
    loop_guard = int(C.load(root).get("rules", {}).get("loop_guard", 2))
    steps = {}
    for name, s in specs.items():
        spec = s["spec"]
        steps[name] = {
            "role": spec.get("role"),
            "gate": True if name == "pr" else bool(spec.get("gate", False)),
            "on_fail": spec.get("on_fail") or None,
            "max_loops": int(loop_guard if spec.get("max_loops") is None else spec["max_loops"]),
            "max_agents": int(spec.get("max_agents", 1)),
            "min_score": spec.get("min_score"),
            "kind": kind(s),
            "brief": str(s["brief"]) if s["brief"] else None,
            "run": str(s["run"]) if s["run"] else None,
            "source": s["source"],
        }
    chain = order(specs)
    chain += [n for n in sorted(specs) if n in enabled(specs) and n not in chain]
    return {"chain": chain, "steps": steps}


def score(rows: list[dict]) -> tuple[int | None, int, list[str]]:
    """Each reviewer's score recomputed after verification: a verified Important caps it at 6; a
    reviewer whose Importants were all dropped is raised to 7, or to 10 when nothing it found was
    verified. Final = the lowest of them; `important` = verified Importants."""
    scores, important, shown = [], 0, []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        found = r.get("findings") or []
        verified = [f for f in found if f.get("verified")]
        vimp = [f for f in verified if str(f.get("severity", "")).lower() == IMPORTANT]
        uimp = [f for f in found if not f.get("verified") and str(f.get("severity", "")).lower() == IMPORTANT]
        n = int(r.get("score") or 0)
        if vimp:
            n, important = min(n, 6), important + len(vimp)
        elif uimp:
            n = max(n, 7 if verified else 10)
        scores.append(n)
        shown.append(f"{r.get('reviewer') or '?'}={n}")
    return (min(scores) if scores else None), important, shown


def _write_json(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, p)


def read_state(run_dir: Path, chain: list[str]) -> dict:
    """<run>/workflow.json, or a fresh one at the first step. A run's place survives a re-read; a
    missing or corrupt file starts fresh rather than failing the step."""
    try:
        st = json.loads((run_dir / "workflow.json").read_text())
    except (OSError, ValueError):
        st = {}
    if not isinstance(st, dict) or not isinstance(st.get("steps"), dict):
        st = {}
    st.setdefault("current", chain[0] if chain else "done")
    st.setdefault("steps", {})
    return st


def write_state(run_dir: Path, st: dict) -> None:
    _write_json(run_dir / "workflow.json", st)


def progress(run_dir: Path, line: str) -> None:
    p = run_dir / "progress.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(line + "\n")


def release(root: Path, run_dir: Path) -> None:
    """Drop the write-lock holders this run owns, so the next dispatch into this checkout starts.
    The lock is dispatch's; this is its lock_release() keyed by the run folder."""
    import sstack_dispatch as D  # lazy: dispatch imports this module
    try:
        owner = run_dir.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return
    D.lock_release(root, owner)


def advance(root: Path, run_dir: Path, wf: dict, step: str, failed: bool = False,
            findings: str | None = None) -> int:
    """Record one step's result, print what the agent does next, and exit 0, or 2 at the loop cap."""
    chain, steps = wf["chain"], wf["steps"]
    if step not in chain:
        print(f"sstack-workflow: no step {step!r} in the chain ({' → '.join(chain) or 'no steps'})",
              file=sys.stderr)
        return 1
    spec = steps[step]
    st, at = read_state(run_dir, chain), chain.index(step)
    entry = st["steps"].setdefault(step, {"status": None, "loops": 0, "score": None})
    entry.setdefault("loops", 0)
    entry.setdefault("score", None)
    ok = not failed
    if findings:
        try:
            rows = json.loads(Path(findings).read_text())
        except (OSError, ValueError) as e:
            print(f"sstack-workflow: --findings {findings}: {e}", file=sys.stderr)
            return 1
        final, important, shown = score(rows)
        entry["score"] = final
        ok = ok and important == 0 and (final is None or final >= int(spec["min_score"] or 0))
        print(f"score: {final if final is not None else '-'} (min of {', '.join(shown) or 'no reviewers'}; "
              f"verified Important {important})")
    if ok:
        entry["status"] = "pass"
        nxt = chain[at + 1] if at + 1 < len(chain) else None
        st["current"] = nxt or "done"
        write_state(run_dir, st)
        progress(run_dir, f"{step}: pass" + (f" score {entry['score']}" if entry["score"] is not None else ""))
        if spec["gate"]:
            print(GATE)
        print(f"next: {nxt or 'done'}")
        release(root, run_dir)
        return 0
    entry["status"] = "fail"
    entry["loops"] = int(entry["loops"] or 0) + 1
    progress(run_dir, f"{step}: fail (loop {entry['loops']}/{spec['max_loops']})")
    if entry["loops"] >= spec["max_loops"] or not spec["on_fail"]:
        st["current"] = step
        write_state(run_dir, st)
        print(STOP)
        release(root, run_dir)
        return 2
    st["current"] = spec["on_fail"]
    write_state(run_dir, st)
    print(f"next: {spec['on_fail']}")
    release(root, run_dir)
    return 0


def show(root: Path, as_json: bool = False) -> int:
    wf = resolved(root)
    if as_json:
        print(json.dumps({"chain": wf["chain"], "steps": {n: wf["steps"][n] for n in wf["chain"]}}, indent=2))
        return 0
    for n in wf["chain"]:
        s = wf["steps"][n]
        print(f"{n}  {s['kind']}{' ' + s['role'] if s['role'] else ''}  gate {'on' if s['gate'] else 'off'}  "
              f"on_fail {s['on_fail'] or '-'}  max_loops {s['max_loops']}  max_agents {s['max_agents']}  "
              f"min_score {s['min_score'] if s['min_score'] is not None else '-'}")
        print(f"    source: {', '.join(f'{k}={v}' for k, v in s['source'].items()) or '-'}")
        if s["brief"]:
            print(f"    brief: {s['brief']}")
        if s["run"]:
            print(f"    run: {s['run']}")
    if off := [n for n in sorted(wf["steps"]) if n not in wf["chain"]]:
        print(f"disabled: {', '.join(off)}")
    return 0


def status(root: Path, run_dir: Path) -> int:
    wf = resolved(root)
    if not wf["chain"]:
        print("sstack-workflow: no steps: add steps/<name>/ (docs/spec/workflow.md)", file=sys.stderr)
        return 1
    st = read_state(run_dir, wf["chain"])
    print(f"at: {st['current']}")
    for n in wf["chain"]:
        e = st["steps"].get(n) or {}
        bits = [e.get("status") or "todo", f"loops {e.get('loops') or 0}/{wf['steps'][n]['max_loops']}"]
        if e.get("score") is not None:
            bits.append(f"score {e['score']}")
        print(f"{n}: {' '.join(bits)}")
    return 0


def cmd_run(root: Path, run_dir: Path, step: str) -> int:
    """Exec the nearest run.sh with the repo root as cwd and SSTACK_RUN / SSTACK_ROOT /
    SSTACK_HOME_DIR in the environment; exit 0 passes, like `done`."""
    wf = resolved(root)
    if step not in wf["steps"]:
        print(f"sstack-workflow: no step {step!r} ({', '.join(sorted(wf['steps']))})", file=sys.stderr)
        return 1
    path = wf["steps"][step]["run"]
    if not path:
        print(f"sstack-workflow: {step} has no run.sh (kind: {wf['steps'][step]['kind']}); only a "
              "command step can be run", file=sys.stderr)
        return 1
    if step not in wf["chain"]:
        print(f"sstack-workflow: {step} is disabled (sstack-workflow show)", file=sys.stderr)
        return 1
    env = {**os.environ, "SSTACK_RUN": str(run_dir), "SSTACK_ROOT": str(root), "SSTACK_HOME_DIR": str(REPO)}
    try:
        code = subprocess.run([path], cwd=root, env=env).returncode
    except PermissionError:
        code = subprocess.run(["sh", path], cwd=root, env=env).returncode
    except OSError as e:
        print(f"sstack-workflow: {path}: {e}", file=sys.stderr)
        return 1
    return advance(root, run_dir, wf, step, failed=code != 0)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="sstack-workflow",
        description="Resolve the step chain from steps/<name>/ folders and track a run's place in it "
                    "(docs/spec/workflow.md). Never launches an agent; the step's gate is printed for "
                    "the agent to wait on.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("show", help="the resolved chain: order, kind, gate, caps, and each key's layer")
    p.add_argument("--json", action="store_true", help="machine-readable")
    p = sub.add_parser("status", help="where a run is: the current step and every step's state")
    p.add_argument("--run", required=True, metavar="RUN", help="run folder")
    p = sub.add_parser("done", help="record a step's result and print the next step (or STOP)")
    p.add_argument("step")
    p.add_argument("--fail", action="store_true", help="the step failed: on_fail, or STOP")
    p.add_argument("--findings", metavar="JSON", help="a review step's findings.json; the score is recomputed")
    p.add_argument("--run", required=True, metavar="RUN", help="run folder")
    p = sub.add_parser("run", help="run a command step's run.sh and record its exit")
    p.add_argument("step")
    p.add_argument("--run", required=True, metavar="RUN", help="run folder")
    a = ap.parse_args(argv)
    root = C.git_root(Path.cwd())
    if root is None:
        print("sstack-workflow: not in a git repo", file=sys.stderr)
        return 1
    try:
        if a.cmd == "show":
            return show(root, a.json)
        run_dir = Path(a.run).resolve()
        if a.cmd == "status":
            return status(root, run_dir)
        if a.cmd == "run":
            return cmd_run(root, run_dir, a.step)
        return advance(root, run_dir, resolved(root), a.step, a.fail, a.findings)
    except C.ConfigError as e:
        print(f"sstack-workflow: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
