import ast
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import REPO, TempEnv

DATA = REPO / "tests" / "configcli_data"
CLI = REPO / "bin" / "sstack-config"


def _call_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    if isinstance(call.func, ast.Name):
        return call.func.id
    return ""


def _keyword(call: ast.Call, name: str) -> ast.keyword | None:
    return next((k for k in call.keywords if k.arg == name), None)


def _text_mode(call: ast.Call) -> bool:
    mode = "r"
    # Path.open's first argument is the mode; open()/os.fdopen() take the path/fd first.
    at = 0 if _call_name(call) == "open" and isinstance(call.func, ast.Attribute) else 1
    if len(call.args) > at and isinstance(call.args[at], ast.Constant):
        mode = call.args[at].value
    kw = _keyword(call, "mode")
    if kw is not None and isinstance(kw.value, ast.Constant):
        mode = kw.value.value
    return "b" not in str(mode)


class EncodingTests(TempEnv):
    def test_lib_and_bin_text_io_is_explicit_utf8(self):
        failures = []
        files = [*sorted((REPO / "lib").glob("*.py")),
                 *sorted(p for p in (REPO / "bin").iterdir() if p.is_file())]
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = _call_name(node)
                if name in ("read_text", "write_text"):
                    if _keyword(node, "encoding") is None:
                        failures.append(f"{path.relative_to(REPO)}:{node.lineno}: {name} needs encoding")
                elif name in ("open", "fdopen"):
                    if _text_mode(node) and _keyword(node, "encoding") is None:
                        failures.append(f"{path.relative_to(REPO)}:{node.lineno}: open needs encoding")
                elif name in ("run", "Popen", "check_output"):
                    text = _keyword(node, "text") or _keyword(node, "universal_newlines")
                    if (text is not None and isinstance(text.value, ast.Constant)
                            and text.value.value is True
                            and _keyword(node, "encoding") is None):
                        failures.append(f"{path.relative_to(REPO)}:{node.lineno}: {name} needs encoding")
        self.assertFalse(failures, "text I/O without encoding:\n" + "\n".join(failures))

    @unittest.skipUnless(shutil.which("python3.11"), "python3.11 not on PATH")
    def test_lib_and_bin_compile_on_python_3_11(self):
        # ast.parse(feature_version=(3, 11)) still accepts 3.12-only f-string quote reuse.
        files = [*(REPO / "lib").glob("*.py"),
                 *(p for p in (REPO / "bin").iterdir() if p.is_file() and not p.suffix)]
        src = "import sys\nfor f in sys.argv[1:]: compile(open(f, encoding='utf-8').read(), f, 'exec')"
        r = subprocess.run(["python3.11", "-c", src, *map(str, files)],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_migrate_prints_arrow_as_utf8_on_a_cp1252_console(self):
        shutil.rmtree(self.home / ".sstack")
        cfg = self.home / ".sstack" / "config.toml"
        cfg.parent.mkdir(parents=True)
        shutil.copy(DATA / "global.toml", cfg)
        env = dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home),
                   PYTHONIOENCODING="cp1252", PYTHONUTF8="0")
        env.pop("SSTACK_HOME", None)
        r = subprocess.run([sys.executable, str(CLI), "migrate", "--global", "--dry-run"],
                           cwd=str(self.root), env=env, capture_output=True)
        out = r.stdout.decode("utf-8")
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
        self.assertIn("→", out)
