"""Stand-in harness. argv[1] = mode: echo | empty | fail | sleep | touch <file> | canary[-wrong|-dirty|-nofile|-stray];
any other mode echoes like `echo` (a model name such as p1 or other is just another echoing agent).
argv echoes the args after the model; codex[-noid|-badid] acts like `codex exec --json -o <file>`: JSONL events on
stdout, the final message in the -o file."""
import json, re, subprocess, sys, os, time
from pathlib import Path

mode = sys.argv[1]
brief = sys.stdin.read()
if mode == "empty":
    pass
elif mode == "fail":
    sys.exit(1)
elif mode == "sleep":
    print(f"PID {os.getpid()}", flush=True)
    subprocess.Popen(["sleep", "60"])
    time.sleep(60)
elif mode == "touch":
    Path(sys.argv[2]).write_text("hi\n")
    print(f"REPORT touched {sys.argv[2]}\nPASS")
elif mode == "dirty":  # read-only role that edits anyway
    Path("dirty.txt").write_text("x\n")
    print("REPORT")
elif mode == "lesson":  # a reflect pass that found lessons
    print("Some notes\nLESSON: repo | run pnpm, not npm | user said so at turn 4\n"
          "LESSON: global | <text> | <evidence>\nLESSON: bogus | x | y\nPASS")
elif mode == "env":  # what the child sees
    print(f"SSTACK_REFLECT={os.environ.get('SSTACK_REFLECT')}")
elif mode.startswith("canary"):  # sstack-doctor smoke brief: write the canary file if asked, reply the token
    tok = re.search(r"CANARY (\w+)", brief)[1]
    if (m := re.search(r"Write (\S+) containing", brief)) and mode != "canary-nofile":
        Path(m[1]).write_text(tok + "\n")
    if mode == "canary-dirty":
        Path("dirty.txt").write_text("x\n")
    if mode == "canary-stray":  # a stray file under .sstack/runs/, outside every run dir
        Path(".sstack/runs/stray.txt").write_text("x\n")
    print(f"CANARY {'wrong' if mode == 'canary-wrong' else tok}")
elif mode == "argv":  # what sstack added after the model
    print("REPORT\nARGV " + json.dumps(sys.argv[2:]))
elif mode.startswith("codex"):
    out = sys.argv[sys.argv.index("-o") + 1] if "-o" in sys.argv else None
    tid = "bad id!" if mode == "codex-badid" else "019a-thread:one"
    print("Reading prompt from stdin...")  # not JSON
    if mode != "codex-noid":
        print(json.dumps({"type": "thread.started", "thread_id": tid}))
    print(json.dumps({"type": "item.completed", "item": {"text": "FINAL " + brief}}))
    if out:
        Path(out).write_text("FINAL MESSAGE\n" + brief)
else:  # echo, and any model name without a mode of its own
    print("REPORT\n" + brief)
