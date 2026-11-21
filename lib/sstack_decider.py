"""The decider (docs/spec/dispatch.md § Decider): picks a catalogue entry for a dispatch, or proposes a
workflow reshape, from `[decider] via = "jev" | "openrouter" | "llm"`. `decide()` and `propose()` are the only
functions that call Jev (OpenRouter's Decisions API) or a model; route.pick() and its callers never call them. Off by default
(`via = "heuristic"`), bounded by `timeout`, and any error falls back to the heuristic route."""
import json
import os
import subprocess
import sys
import urllib.request

import sstack_config as C

MAX_TEXT = 8000  # task and plan are cut to this many characters each
# Jev 1.14 switches to a slower long-context mode above ~32,000 bytes: the whole request is kept under
# this (the longer of task and plan cut down to JEV_MIN_TASK chars each, then files), else it is not sent.
JEV_MAX_BYTES = 30000
JEV_MIN_TASK = 1000
REPLY = 'one JSON line: {"choice": "<tier>/<id>", "confidence": <0..1>}'
PROPOSAL_REPLY = ('one JSON line: {"skip": [step], "repeat": {step: n}, "panel_size": n}; '
                  'only unlocked steps, never pr or gate')


def choices(cfg: dict, tiers: list[str] | None = None) -> list[dict]:
    """Every tier's entries (ladder tiers first, then the rest), or only `tiers`; entries whose harness
    is not installed are dropped."""
    have = cfg.get("tier", {})
    order = cfg.get("rules", {}).get("tier_order", ["cheap", "standard", "strong"])
    names = [t for t in order if t in have] + [t for t in have if t not in order]
    return [e for t in names if tiers is None or t in tiers
            for e in C.tier_entries(cfg, t) if C.harness_installed(cfg, e["harness"])]


def _desc(e: dict) -> str:
    return (e["when"].strip() + (f" ({e['tier']}: {e['tier_when']})" if e["tier_when"] else "")).strip()


def lines(cs: list[dict]) -> list[str]:
    return [f"{e['tier']}/{e['id']}: {_desc(e)}".rstrip() for e in cs]


def _key(name: str) -> str | None:
    """$name, else a `name=value` line in $SSTACK_HOME/.env (the profile, never the repo), so agent
    shells that lack the variable still reach the decider."""
    if os.environ.get(name):
        return os.environ[name]
    try:
        text = (C.home_dir() / ".env").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        k, _, v = line.strip().removeprefix("export ").partition("=")
        if k.strip() == name and v.strip():
            return v.strip().strip("'\"")
    return None


def _jev(url: str, model: str, payload: dict, timeout: float, cs: list[dict]) -> dict:
    """One OpenRouter Decisions API call (alpha; wire shape verified live 2026-11-19 with typesafe/jev-1.14).
    One `choice` question whose criteria are the `<tier>/<id>` choices and their `when` lines; the answer is
    answers.tier.choice, its confidence else probabilities[choice]. All of the API's shape lives here."""
    if "choices" not in payload:
        raise RuntimeError("jev answers the tier question only")
    key = _key("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    files = list(payload["files"])
    state = {"task": payload["task"], "step": payload["step"], "files": files, "plan": payload["plan"]}
    criteria = {f"{e['tier']}/{e['id']}": _desc(e) for e in cs}
    body = {"model": model, "state": state, "questions": {"tier": {
        "type": "choice", "instructions": "Which model tier should do this task?", "criteria": criteria}}}
    shown = len(files)
    while (over := len(json.dumps(body).encode()) - JEV_MAX_BYTES) > 0:
        cut = max(1, over // 6)  # a char is 1-6 JSON bytes
        k = max(("plan", "task"), key=lambda k: len(state[k]))
        if len(state[k]) > JEV_MIN_TASK:
            state[k] = state[k][:max(JEV_MIN_TASK, len(state[k]) - cut)]
        elif shown:
            shown -= 1
            state["files"] = files[:shown] + [f"... {len(files) - shown} more files"]
        else:
            raise RuntimeError(f"request over {JEV_MAX_BYTES} bytes even with no files; not sent")
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        reply = json.loads(r.read().decode())
    if "error" in reply:
        raise RuntimeError(f"error {reply['error']}")
    a = reply.get("answers", {}).get("tier")
    if not a or a.get("type") != "choice" or "choice" not in a:
        raise RuntimeError(f"no tier answer ({(a or {}).get('type', 'missing')})")
    conf = a.get("confidence", (a.get("probabilities") or {}).get(a["choice"]))
    return {"choice": a["choice"], "confidence": conf}


def _prompt(payload: dict) -> str:
    return ("You route coding work for sstack. Read the JSON below and reply with "
            f"{payload['reply']}, and nothing else.\n\n{json.dumps(payload, indent=1)}\n")


def _last_json(text: str) -> dict:
    """The whole text as JSON, else its last line that is a `{...}` object (a fenced or chatty reply)."""
    try:
        return json.loads(text)
    except ValueError:
        pass
    for line in reversed(text.splitlines()):
        if line.strip().startswith("{") and line.strip().endswith("}"):
            return json.loads(line)
    raise ValueError("no JSON line in the reply")


def _openrouter(url: str, model: str, payload: dict, timeout: float) -> dict:
    """One OpenRouter chat completion (OpenAI-compatible, documented): `model` is any OpenRouter id,
    e.g. typesafe/jev-1.14; the reply is choices[0].message.content."""
    key = _key("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    body = {"model": model, "messages": [{"role": "user", "content": _prompt(payload)}],
            "response_format": {"type": "json_object"}}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return _last_json(json.loads(r.read().decode())["choices"][0]["message"]["content"])


def _llm(cfg: dict, member: dict, payload: dict, timeout: float) -> dict:
    """One read-only headless run of the `[decider]` harness; the reply is stdout's last `{...}` line."""
    import sstack_ade as A  # lazy: only the llm decider needs the templater
    argv = A.fill(cfg["harness"][member["harness"]]["headless_readonly"],
                  {"model": member["model"], "effort": member["effort"], "title": "sstack decider"})
    r = subprocess.run(argv, input=_prompt(payload), capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"{argv[0]} exit {r.returncode}")
    return _last_json(r.stdout)


def _ask(cfg: dict, s: dict, payload: dict, cs: list[dict] | None = None) -> dict:
    if s["via"] == "jev":
        return _jev(s["url"], s["model"], payload, s["timeout"], cs or [])
    if s["via"] == "openrouter":
        return _openrouter(s["url"], s["model"], payload, s["timeout"])
    return _llm(cfg, s["member"], payload, s["timeout"])


def _fallback(via: str, why) -> None:
    print(f"sstack-dispatch: decider {via}: {why}; heuristic route", file=sys.stderr)


def decide(cfg: dict, task: str, step: str | None, plan: str, files: list[str],
           tiers: list[str] | None = None) -> dict | None:
    """The entry the decider picks, with its `confidence`; None for heuristic, no choices, a reply that
    names no listed entry, low confidence, or any error."""
    s = C.decider(cfg)
    if s["via"] == "heuristic" or not (cs := choices(cfg, tiers)):
        return None
    try:
        payload = {"task": (task or "")[:MAX_TEXT], "step": step, "plan": (plan or "")[:MAX_TEXT],
                   "files": list(files), "choices": lines(cs), "reply": REPLY}
        reply = _ask(cfg, s, payload, cs=cs)
        hit = {f"{e['tier']}/{e['id']}": e for e in cs}.get(reply.get("choice"))
        conf = float(reply.get("confidence") or 0)
    except Exception as e:  # noqa: BLE001 - any decider failure falls back, by design (R14)
        _fallback(s["via"], e)
        return None
    if hit is None:
        _fallback(s["via"], f"{reply.get('choice')!r} is not a listed entry")
        return None
    if not 0 <= conf <= 1:  # NaN fails this too
        _fallback(s["via"], f"{reply.get('choice')} confidence {conf!r} is not from 0 to 1")
        return None
    if conf < s["min_confidence"]:
        _fallback(s["via"], f"{reply.get('choice')} confidence {conf:g} < {s['min_confidence']:g}")
        return None
    return {**hit, "confidence": conf}


def propose(cfg: dict, plan: str, chain: list[str]) -> dict | None:
    """A workflow reshape proposal (skip, repeat, panel_size) for sstack-workflow's bounds check;
    None for heuristic or on any error."""
    s = C.decider(cfg)
    if s["via"] == "heuristic":
        return None
    try:
        reply = _ask(cfg, s, {"plan": (plan or "")[:MAX_TEXT], "chain": chain, "reply": PROPOSAL_REPLY})
    except Exception as e:  # noqa: BLE001
        print(f"sstack-workflow: decider {s['via']}: {e}; nothing proposed", file=sys.stderr)
        return None
    return reply if isinstance(reply, dict) else None
