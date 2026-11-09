"""Stand-in harness. argv[1] = mode: echo | empty | fail | sleep | touch <file> | canary[-wrong|-dirty|-nofile|-stray]."""
import re, subprocess, sys, os, time
from pathlib import Path

mode = sys.argv[1]
brief = sys.stdin.read()
if mode == "echo":
    print("REPORT\n" + brief)
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
# empty: print nothing
