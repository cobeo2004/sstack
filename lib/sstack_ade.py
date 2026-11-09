"""The ADE layer (docs/spec/ade.md): which adapter is active, the agent-tool payload for a member,
and the hook lifecycle (detect / delegate / wait / collect / cancel)."""
import json
import os
import re
import signal
import subprocess
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path

from sstack_config import ConfigError, ades

PH = re.compile(r"\{(\w+)\}")
WAIT_RUNNING = 10  # `hook wait` exit code: still running
KINDS = ("tool", "hook", "none")
TASK = ("Read the brief at {brief} and do exactly what it says. Write your report to {report}. "
        "If you cannot write files, return the full report as your final message.")


class HookTimeout(Exception):
    """The dispatch deadline passed while a hook ran (its process group is killed)."""


def kill_group(p: subprocess.Popen) -> None:
    """SIGTERM then SIGKILL the child's whole process group (it was started with start_new_session)."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(p.pid, sig)
        except (ProcessLookupError, PermissionError):  # macOS: EPERM when only zombies are left
            break
        try:
            p.wait(timeout=2)
            break
        except subprocess.TimeoutExpired:
            continue
    try:  # ponytail: the leader exiting on TERM doesn't mean a TERM-ignoring grandchild did
        os.killpg(p.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    p.wait()


def left(deadline: float) -> float:
    """Seconds until `deadline` (time.monotonic); HookTimeout once it has passed."""
    s = deadline - time.monotonic()
    if s <= 0:
        raise HookTimeout
    return s


def _hook(path: Path | None, cap: str, stdin: dict, state: Path | None, env: Mapping[str, str],
          timeout: float) -> subprocess.CompletedProcess | None:
    """Run `<hook> <cap>` in its own session; None when the hook is missing or not executable;
    HookTimeout (group killed) when it runs past `timeout`."""
    if not path or not os.access(path, os.X_OK):
        return None
    e = {**env, **({"SSTACK_HOOK_STATE": str(state)} if state else {})}
    try:
        p = subprocess.Popen([str(path), cap], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, env=e, start_new_session=True)
    except OSError:
        return None
    try:
        out, err = p.communicate(json.dumps(stdin), timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_group(p)
        for f in (p.stdin, p.stdout, p.stderr):
            f.close()
        raise HookTimeout from None
    return subprocess.CompletedProcess(p.args, p.returncode, out, err)


def _detects(a: dict, env: Mapping[str, str]) -> str | None:
    det = a["toml"].get("detect", {})
    if var := next((v for v in det.get("env", []) if v in env), None):
        return f"env {var}"
    if det.get("hook"):
        with tempfile.TemporaryDirectory() as state:  # no run dir yet; hooks may require the var
            try:
                r = _hook(a["hook_path"], "detect", {}, Path(state), env, timeout=10)
            except HookTimeout:
                r = None
        if r is not None and r.returncode == 0:
            return "hook detect"
    return None


def active(root: Path | None, cfg: dict, env: Mapping[str, str]) -> tuple[dict | None, str]:
    """(adapter or None, why): SSTACK_ADE > config `ade` > auto-detect (first match, auto = true only)."""
    all_ = ades(root)
    by_name = {a["name"]: a for a in all_}
    for forced, why in ((env.get("SSTACK_ADE"), "SSTACK_ADE={}"), (cfg.get("ade", "auto"), "ade = {}")):
        if not forced or forced == "auto":
            continue
        if forced == "none":
            return None, why.format("none")
        if forced not in by_name:
            raise ConfigError(f"{why.format(forced)}: no ades/{forced}.toml in any layer")
        return by_name[forced], why.format(forced)
    for a in all_:
        if a["auto"] and (why := _detects(a, env)):
            return a, why
    return None, "no adapter detected"


def describe(a: dict | None, why: str) -> dict:
    """The `sstack-dispatch ade` JSON."""
    if a is None:
        return {"name": None, "why": why, **dict.fromkeys(
            ("layer", "delegate", "readonly", "browser", "device", "capture", "note"))}
    t, d = a["toml"], a["toml"].get("delegate", {})
    k = kind(a)
    cap = lambda c: (f"{t[c]['kind']}: {t[c].get('summary', '')}"
                     if t.get(c, {}).get("kind", "none") != "none" else "none")
    return {"name": a["name"], "why": why, "layer": a["layer"],
            "delegate": f"tool {d.get('name')}" if k == "tool" else k,
            "readonly": d.get("readonly"), "browser": cap("browser"), "device": cap("device"),
            "capture": cap("capture"), "note": str(a["note_path"]) if a["note_path"] else None}


def kind(a: dict | None) -> str:
    """The adapter's delegate.kind: tool | hook | none (ConfigError for anything else)."""
    k = a["toml"].get("delegate", {}).get("kind", "none") if a else "none"
    if k not in KINDS:
        raise ConfigError(f"ades/{a['name']}.toml: delegate.kind = {k!r}; expected one of {', '.join(KINDS)}")
    if k == "tool" and not a["toml"]["delegate"].get("name"):
        raise ConfigError(f"ades/{a['name']}.toml: delegate.kind = 'tool' needs delegate.name")
    return k


def key(m: dict) -> str:
    """`<harness>/<model>`; no model → `default` (index, record and run.json use the same)."""
    return f"{m['harness']}/{m['model'] or 'default'}"


def fill(v, values: dict):
    """The one templater. A string whose placeholder is unset (missing or None) is None: dropped from
    dicts, and from lists together with the `-flag` before it. A string that is exactly one
    placeholder takes the value as is (e.g. `{options}` → a dict)."""
    if isinstance(v, dict):
        return {k: f for k, x in v.items() if (f := fill(x, values)) is not None}
    if isinstance(v, list):
        out = []
        for x in v:
            f = fill(x, values)
            if f is None:
                if out and isinstance(out[-1], str) and out[-1].startswith("-"):
                    out.pop()
                continue
            out.append(f)
        return out
    if not isinstance(v, str):
        return v
    names = PH.findall(v)
    if any(values.get(n) is None for n in names):
        return None
    if (m := PH.fullmatch(v)):
        return values[m.group(1)]
    return PH.sub(lambda m: str(values[m.group(1)]), v)


def ids(a: dict, member: dict) -> tuple[str, str, dict, str | None]:
    """(provider id, ADE model id, effort options, note) for one member."""
    t, h, model = a["toml"], member["harness"], member["model"]
    provider = t.get("providers", {}).get(h, h)
    mapped = t.get("models", {}).get(h, {}).get(model)
    note = None if mapped or model is None else f"model {model} not in [models.{h}]; passed through"
    opt = t.get("effort_option", {}).get(provider)
    return provider, mapped or model, ({opt: member["effort"]} if opt and member["effort"] else {}), note


def tool_call(a: dict, role: str, readonly: bool, member: dict, title: str, brief: str, report: str,
              record: str) -> dict:
    d = a["toml"]["delegate"]
    provider, model, options, note = ids(a, member)
    values = {"title": title, "brief": brief, "report": report, "role": role,
              "ade_role": d.get("roles", {}).get(role, role), "provider": provider, "model": model,
              "options": options}
    values["task"] = fill(TASK, values)
    args = {**d.get("args", {}), **d.get("readonly_args" if readonly else "write_args", {})}
    call = {"member": key(member), "tool": d["name"], "load_hint": d.get("load_hint"), "args": fill(args, values)}
    if note:
        call["note"] = note
    call["record"] = record
    return call


def cli_argv(a: dict | None, member: dict, title: str, env: Mapping[str, str]) -> list[str]:
    """`[dispatch] via = "ade-cli"`: the adapter's [cli] cmd (T3: `t3 thread start`)."""
    cli = (a or {}).get("toml", {}).get("cli", {})
    if "cmd" not in cli:
        raise ConfigError(f"dispatch.via = ade-cli but the active ADE ({a and a['name']}) has no [cli] cmd")
    path = re.sub(r"\$(\w+)", lambda m: env.get(m.group(1), ""), cli.get("path", ""))
    provider, model, _, _ = ids(a, member)
    values = {"cli": path or str(Path.home() / ".t3" / "bin" / "t3"), "provider": provider,
              "model": model, "title": title}
    return fill(cli["cmd"], values)


def delegate(a: dict, stdin: dict, state: Path, env: Mapping[str, str], deadline: float) -> tuple[dict | None, str | None]:
    """`hook delegate` → (action dict, None), or (None, note) when the member must run headless.
    HookTimeout when the deadline passes first."""
    r = _hook(a["hook_path"], "delegate", stdin, state, env, timeout=left(deadline))
    if r is None:
        return None, f"ADE {a['name']}: hook missing or not executable; running headless"
    if r.returncode != 0:
        return None, f"ADE {a['name']}: hook delegate exit {r.returncode}; running headless"
    try:
        act = json.loads(r.stdout)
    except ValueError:
        act = None
    if not isinstance(act, dict) or act.get("action") not in ("run", "async", "none"):
        return None, f"ADE {a['name']}: hook delegate printed no valid action; running headless"
    if act["action"] == "none":
        return None, act.get("note") or f"ADE {a['name']}: hook chose none; running headless"
    argv, job = act.get("argv"), act.get("id")
    if act["action"] == "run" and not (isinstance(argv, list) and argv and all(isinstance(x, str) for x in argv)):
        return None, f"ADE {a['name']}: hook action run needs argv = a non-empty list of strings; running headless"
    if act["action"] == "async" and (isinstance(job, bool) or not isinstance(job, (str, int)) or job == ""):
        return None, f"ADE {a['name']}: hook action async needs id = a string or int; running headless"
    return act, None


def run_async(a: dict, job: str, state: Path, env: Mapping[str, str], deadline: float, report: Path) -> int:
    """wait (re-polled every poll_s, never past `deadline`) → collect into `report`.
    0 ok, 1 failed/empty/hook missing, 2 timeout (cancel called)."""
    poll = float(a["toml"].get("delegate", {}).get("poll_s", 15))
    try:
        while True:
            r = _hook(a["hook_path"], "wait", {"id": job}, state, env, timeout=left(deadline))
            if r is None or (r.returncode != 0 and r.returncode != WAIT_RUNNING):
                return 1
            if r.returncode == 0:
                break
            time.sleep(min(poll, left(deadline)))
        r = _hook(a["hook_path"], "collect", {"id": job}, state, env, timeout=left(deadline))
    except HookTimeout:
        try:
            _hook(a["hook_path"], "cancel", {"id": job}, state, env, timeout=30)
        except HookTimeout:
            pass
        return 2
    if r is None or r.returncode != 0 or not r.stdout:
        return 1
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(r.stdout)
    return 0
