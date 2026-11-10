"""docs/guide lint + runner (docs/guide/contributing.md#how-the-docs-are-tested). Every ```sh block runs
in a scratch HOME and git repo with fake harness CLIs first on PATH, SSTACK_HOME and TMPDIR unset, and
sstack's bin/ on PATH only if the page's setup block puts it there. A line holding `# needs:` is not
run; a trailing `# exit N` sets the expected exit code (default 0); a ```text block that follows and
starts with `# expect` lists stdout lines that must appear, in order."""
import os, re, subprocess, tempfile, unittest
from pathlib import Path

from helpers import REPO
from test_skills import strip_code

GUIDE = REPO / "docs" / "guide"
README = REPO / "README.md"
FENCE = re.compile(r"^```(\w*)\n(.*?)^```", re.S | re.M)
SETUP = re.compile(r"^## (Install|Before you start)\n", re.M)
ADE_ENV = ("T3CODE_THREAD_ID", "ORCA_AGENT_SESSION_ID", "CONDUCTOR_SESSION_ID", "SSTACK_ADE")
# Flags in prose and tables belong to the page's main command.
PAGE_CMD = {"getting-started.md": "sstack-install", "configuration.md": "sstack-config",
            "gate.md": "sstack-gate", "ades.md": "sstack-dispatch",
            "writing-an-ade.md": "sstack-dispatch", "dispatch.md": "sstack-dispatch",
            "doctor.md": "sstack-doctor", "dashboard.md": "sstack-ui", "contributing.md": None}
SPEC_OF = {"sstack-dispatch": "dispatch.md", "sstack-doctor": "doctor.md", "sstack-config": "config.md",
           "sstack-gate": "gate.md", "sstack-ui": "ui.md"}
# Subcommands handled before argparse, so not in the usage line; None = takes no flags.
SUBS = {"sstack-dispatch": {"record": "record", "routes": None, "ade": None}}
# Stand-in for every harness CLI: echoes the brief, or answers a doctor smoke canary.
FAKE = r'''#!/usr/bin/env python3
import re, sys
from pathlib import Path
b = sys.stdin.read()
m = re.search(r"CANARY (\w+)", b)
if not m:
    print("REPORT\n" + b)
    sys.exit()
if (w := re.search(r"Write (\S+) containing", b)):
    Path(w[1]).write_text(m[1] + "\n")
print("CANARY " + m[1])
'''


def pages():
    return sorted(GUIDE.glob("*.md"))


def slug(heading: str) -> str:
    """GitHub's anchor for a heading."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def anchors(f: Path) -> set[str]:
    return {slug(h) for h in re.findall(r"^#+ (.+)$", re.sub(r"```.*?```", "", f.read_text(), flags=re.S), re.M)}


def commands(block: str):
    """Logical commands of a sh block: (line no, text, expected exit). Joins `\\` continuations and
    heredoc bodies; drops comment-only lines and lines marked `# needs:`."""
    lines, i, out = block.split("\n"), 0, []
    while i < len(lines):
        start, cmd = i, lines[i]
        while cmd.endswith("\\") and i + 1 < len(lines):
            i += 1
            cmd += "\n" + lines[i]
        if (h := re.search(r"<<-?\s*'?(\w+)'?", cmd)):
            while i + 1 < len(lines):
                i += 1
                cmd += "\n" + lines[i]
                if lines[i].strip() == h[1]:
                    break
        i += 1
        first = cmd.split("\n", 1)[0]
        if not first.strip() or first.lstrip().startswith("#") or "# needs:" in first:
            continue
        m = re.search(r"#\s*exit (\d+)\s*$", first)
        out.append((start + 1, cmd, int(m[1]) if m else 0))
    return out


def sh_blocks(text: str):
    """[(index, block, expected stdout lines or None)]; the expectation is the next fence when it is
    a ```text block whose first line is `# expect`."""
    fences, out = list(FENCE.finditer(text)), []
    for n, f in enumerate(fences):
        if f[1] != "sh":
            continue
        nxt = fences[n + 1] if n + 1 < len(fences) else None
        want = None
        if nxt and nxt[1] == "text" and nxt[2].startswith("# expect\n"):
            want = [l for l in nxt[2].split("\n")[1:] if l.strip()]
        out.append((len(out), f[2], want))
    return out


def setup_block(text: str) -> str:
    """The page's setup: the first sh block under `## Install` or `## Before you start`."""
    if not (m := SETUP.search(text)):
        return ""
    end = re.compile(r"^## ", re.M).search(text, m.end())
    f = FENCE.search(text[m.end():end.start() if end else len(text)])
    return f[2] if f and f[1] == "sh" else ""


def expect_errors(want: list[str], stdout: str) -> list[str]:
    """Each expected line (`…` matches anything) must equal a stdout line, in order."""
    lines, i = [l.strip() for l in stdout.splitlines()], 0
    for w in want:
        rx = re.compile(".*".join(re.escape(p) for p in w.strip().split("…")))
        while i < len(lines) and not rx.fullmatch(lines[i]):
            i += 1
        if i == len(lines):
            return [f"expected line not found (in order): {w}"]
        i += 1
    return []


_HELP: dict[tuple, str] = {}


def help_text(cmd: str, sub: str | None) -> str:
    """--help of cmd (sub given: that subcommand's; sub "*": top level plus every subcommand)."""
    key = (cmd, sub)
    if key not in _HELP:
        with tempfile.TemporaryDirectory() as h:  # never read the real ~/.sstack
            env = {**os.environ, "HOME": h, "SSTACK_HOME": h}
            run = lambda *a: subprocess.run([str(REPO / "bin" / cmd), *a, "--help"], capture_output=True,
                                            text=True, timeout=30, env=env, stdin=subprocess.DEVNULL).stdout
            if sub == "*":
                _HELP[key] = help_text(cmd, None) + "".join(help_text(cmd, s) for s in subcommands(cmd))
            elif sub is None:
                _HELP[key] = run()
            else:
                real = SUBS.get(cmd, {}).get(sub, sub)
                _HELP[key] = run(real) if real else ""
    return _HELP[key]


def subcommands(cmd: str) -> list[str]:
    m = re.search(r"\{([a-z,-]+)\}", help_text(cmd, None).split("\n\n", 1)[0])
    return (m[1].split(",") if m else []) + list(SUBS.get(cmd, {}))


FLAG = re.compile(r"(?<![\w-])--[a-z][a-z-]*")
CMD = re.compile(r"(?<![\w-])(sstack-[a-z-]+)\b")


def explicit_uses(s: str) -> list[tuple[str, str | None, str]]:
    """(cmd, subcommand, flag) for each --flag after an sstack-* command in s, up to the end of that
    shell command (`;`, `|`, `&&`, `>`, `#`, a backtick)."""
    parts, uses = CMD.split(s), []  # [before, cmd, rest, cmd, rest, ...]
    for cmd, rest in zip(parts[1::2], parts[2::2]):
        seg = re.split(r";|\s\||&&|\s>|\s#|`|\$\(", rest)[0]
        words = seg.split()
        sub = words[0] if words and (REPO / "bin" / cmd).exists() and words[0] in subcommands(cmd) else None
        uses.extend((cmd, sub, f) for f in FLAG.findall(seg))
    return uses


def flag_errors(page: str, text: str) -> list[str]:
    """Every --flag must belong to its command: the sstack-* command before it on the same line or
    backticked span, else (prose and tables) the page's main command. Valid = in that command's (or
    subcommand's) --help, or written after that command in its own spec file; whole flags only."""
    uses: list[tuple[str | None, str | None, str]] = []
    main = PAGE_CMD.get(page)
    for f in FENCE.finditer(text):
        for line in f[2].replace("\\\n", " ").splitlines():  # one logical command per line
            uses += explicit_uses(line)
    for line in FENCE.sub("", text).splitlines():
        for span in re.findall(r"`([^`\n]+)`", line):
            if CMD.search(span):
                uses += explicit_uses(span)
            elif span.startswith("-"):
                uses += [(main, "*", fl) for fl in FLAG.findall(span)]
        uses += [(main, "*", fl) for fl in FLAG.findall(re.sub(r"`[^`\n]*`", "", line))]

    errs = []
    for cmd, sub, flag in uses:
        if cmd is None:
            errs.append(f"{page}: {flag} with no command (add one to PAGE_CMD)")
            continue
        if not (REPO / "bin" / cmd).exists():
            continue
        spec = REPO / "docs" / "spec" / SPEC_OF[cmd] if cmd in SPEC_OF else None
        spec_flags = {f for line in (spec.read_text().splitlines() if spec else [])
                      for c, _, f in explicit_uses(line) if c == cmd}
        if flag not in spec_flags and not re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", help_text(cmd, sub)):
            errs.append(f"{page}: {cmd}{' ' + sub if sub and sub != '*' else ''} {flag}")
    return errs


class Sandbox:
    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = base = Path(self._tmp.name).resolve()
        self.home, self.repo, fakes = base / "home", base / "repo", base / "fakebin"
        for d in (self.home, self.repo, fakes):
            d.mkdir()
        (self.home / "sstack").symlink_to(REPO)  # stands in for the `git clone` line (# needs: network)
        for name in ("pi", "claude", "codex", "cursor-agent"):
            (fakes / name).write_text(FAKE)
            (fakes / name).chmod(0o755)
        drop = ADE_ENV + ("SSTACK_HOME", "TMPDIR")
        self.env = {k: v for k, v in os.environ.items() if k not in drop and not k.startswith("T3CODE_")}
        path = [p for p in os.environ["PATH"].split(os.pathsep) if p and not (Path(p) / "sstack-dispatch").exists()]
        self.env.update(HOME=str(self.home), T3CODE_CLI_PATH=str(base / "no-t3"),
                        GIT_CONFIG_GLOBAL=str(base / "gitconfig"), PATH=os.pathsep.join([str(fakes)] + path))
        g = ["git", "-C", str(self.repo)]
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(g + ["-c", "user.name=d", "-c", "user.email=d@d", "commit", "-q", "--allow-empty",
                            "-m", "init"], check=True, env=self.env)

    def run(self, block: str) -> subprocess.CompletedProcess:
        script = ["set -o pipefail"]
        for n, cmd, want in commands(block):
            script += [cmd, f'__rc=$?; [ "$__rc" -eq {want} ] || '
                            f'{{ echo "block line {n}: exit $__rc, doc says {want}" >&2; exit 97; }}']
        return subprocess.run(["bash", "-c", "\n".join(script)], cwd=self.repo, env=self.env,
                              capture_output=True, text=True, timeout=120)

    def normalise(self, out: str) -> str:
        """Sandbox paths → <sstack>, <repo>, <home>; run-dir stamps → YYYYMMDD-HHMM, nested dispatch
        run dirs → HHMM."""
        for path, name in ((REPO.resolve(), "<sstack>"), (self.home / "sstack", "<sstack>"),
                           (self.repo, "<repo>"), (self.home, "<home>")):
            out = out.replace(str(path), name)
        out = re.sub(r"\b\d{8}-\d{4}\b", "YYYYMMDD-HHMM", out)
        return re.sub(r"(?<=dispatch/)\d{4}-", "HHMM-", out)

    def close(self):
        self._tmp.cleanup()


class DocsLint(unittest.TestCase):
    def test_pages_exist_and_linked(self):
        names = {p.name for p in pages()}
        self.assertTrue({"getting-started.md", "configuration.md", "ades.md", "writing-an-ade.md",
                         "dispatch.md", "doctor.md", "dashboard.md", "contributing.md"} <= names, names)
        readme = README.read_text()
        for p in pages():
            self.assertIn(f"docs/guide/{p.name}", readme, p)
            self.assertIn(p.name, PAGE_CMD, f"{p.name}: add its main command to PAGE_CMD")
        self.assertIn("docs/guide/", (REPO / "AGENTS.md").read_text())

    def test_page_shape(self):
        for p in pages():
            t = p.read_text()
            self.assertIn("\n## What this is\n", t, p)
            self.assertIn("\n## How to change this\n", t, p)
            self.assertRegex(t, r"\n```sh\n", p)
            self.assertNotRegex(strip_code(t), r"<(div|img|br|details|table|a )", f"{p}: HTML")
            self.assertNotIn("see the code", t.lower(), p)
            if any(commands(b) for _, b, _ in sh_blocks(t)):
                self.assertIn("$HOME/sstack/bin", setup_block(t), f"{p.name}: no setup block puts sstack on PATH")

    def test_links_resolve(self):
        for f in pages() + [README]:
            for target in re.findall(r"\]\(([^)\s]+)\)", strip_code(f.read_text())):
                if re.match(r"[a-z]+:", target):
                    continue
                path, _, frag = target.partition("#")
                dest = (f.parent / path) if path else f
                self.assertTrue(dest.exists(), f"{f.name}: broken link {target}")
                if frag and dest.suffix == ".md" and dest.parent == GUIDE:
                    self.assertIn(frag, anchors(dest), f"{f.name}: no anchor {target}")

    def test_flags_documented(self):
        for p in pages():
            self.assertEqual(flag_errors(p.name, p.read_text()), [])

    def test_flag_check_catches(self):
        self.assertEqual(flag_errors("dispatch.md", "Use `--no-escalate` or `--panel`."), [])
        self.assertTrue(flag_errors("dispatch.md", "Use `--bogus-flag`."), "bogus backticked flag")
        self.assertTrue(flag_errors("dispatch.md", "Use `--smoke`."), "doctor's flag on the dispatch page")
        self.assertTrue(flag_errors("doctor.md", "`sstack-config show --smoke`"), "flag of another command")
        self.assertTrue(flag_errors("dispatch.md", "Pass `--no`."), "prefix of --no-escalate")
        self.assertTrue(flag_errors("configuration.md", "```sh\nsstack-dispatch scout \\\n  --bogus-flag\n```\n"),
                        "flag on a continuation line")


class DocsRun(unittest.TestCase):
    def test_sh_blocks_run(self):
        for p in pages():
            text = p.read_text()
            setup = setup_block(text)
            for i, block, want in sh_blocks(text):
                if not commands(block):
                    continue
                with self.subTest(page=p.name, block=i):
                    box = Sandbox()
                    try:
                        r = box.run(block if block == setup else setup + block)
                        out = box.normalise(r.stdout)
                    finally:
                        box.close()
                    msg = f"{p.name} sh block {i}:\n{block}\n--- stderr\n{r.stderr[-2000:]}\n--- stdout\n{out[-3000:]}"
                    self.assertEqual(r.returncode, 0, msg)
                    if want:
                        self.assertEqual(expect_errors(want, out), [], msg)

    def test_sandbox_is_bare(self):
        """No sstack on PATH, SSTACK_HOME or TMPDIR unless the block sets them up."""
        box = Sandbox()
        try:
            self.assertNotEqual(box.run("sstack-doctor\n").returncode, 0)
            self.assertEqual(box.run('test -z "${SSTACK_HOME-}${TMPDIR-}"\n').returncode, 0)
            self.assertEqual(box.run('export PATH="$HOME/sstack/bin:$PATH"\ncommand -v sstack-doctor\n').returncode, 0)
        finally:
            box.close()

    def test_expect_catches(self):
        out = "a\nPASS x: 1\nb\n"
        self.assertEqual(expect_errors(["PASS x: …", "b"], out), [])
        self.assertTrue(expect_errors(["PASS y: 1"], out), "wrong expected line")
        self.assertTrue(expect_errors(["b", "a"], out), "out of order")


if __name__ == "__main__":
    unittest.main()
