#!/usr/bin/env python3
"""Stand-in for external CLIs, symlinked by name: t3 claude codex pi cursor-agent orca conductor.
Every call appends `<name> <args>` to $FAKE_CALLS_LOG (default: calls.log beside the link).
Harness CLIs and t3 print `REPORT <name>`. orca/conductor: the create call writes `REPORT <name>`
to the report path named in the prompt (the child "finishes" at once); FAKE_ORCA_CHECK sets
`check --wait`'s exit, FAKE_CONDUCTOR_STATUS the workspace status (default idle)."""
import json, os, re, shlex, sys
from pathlib import Path

name, args = Path(sys.argv[0]).name, sys.argv[1:]
log = os.environ.get("FAKE_CALLS_LOG") or str(Path(sys.argv[0]).absolute().parent / "calls.log")
with open(log, "a") as f:
    f.write(shlex.join([name, *args]) + "\n")


def child_report(prompt: str) -> None:
    m = re.search(r"Write your report to (.+?)\.(?:\s|$)", prompt)
    if m:
        Path(m.group(1)).write_text(f"REPORT {name}\n")


def opt(flag: str) -> str:
    return args[args.index(flag) + 1]


if name == "orca":
    sub = args[1] if len(args) > 1 else ""
    if sub == "task-create":
        child_report(opt("--prompt"))
        print(json.dumps({"id": "task-1"}))
    elif sub == "check":
        sys.exit(int(os.environ.get("FAKE_ORCA_CHECK", "0")))
elif name == "conductor":
    sub = " ".join(args[:2])
    if sub == "workspace create":
        print(json.dumps({"id": "ws-1"}))
    elif sub == "message create":
        child_report(opt("--message"))
    elif sub == "workspace status":
        print(json.dumps({"status": os.environ.get("FAKE_CONDUCTOR_STATUS", "idle")}))
else:
    sys.stdin.read()
    print(f"REPORT {name}")
