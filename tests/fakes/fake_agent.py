"""Stand-in harness. argv[1] = mode: echo | empty | fail | sleep | touch <file>."""
import subprocess, sys, os, time
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
# empty: print nothing
