"""`sstack-config sync` / drift: the template copied into the home profile (docs/spec/config.md)."""
import contextlib
import hashlib
import io
import tempfile
import tomllib
import unittest
from pathlib import Path

from helpers import REPO  # noqa: F401  (puts lib/ on sys.path)
import sstack_config as C
import sstack_configcli as M


def tree(d: Path) -> dict[str, str]:
    return {str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(d.rglob("*")) if p.is_file()}


def run_sync(home: Path, dry_run: bool = False) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = M.sync(home, dry_run=dry_run)
    return code, out.getvalue(), err.getvalue()


class SyncTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "p"

    def tearDown(self):
        self._tmp.cleanup()

    def test_empty_home_gets_settings_not_code(self):
        code, out, _ = run_sync(self.home)
        self.assertEqual(code, 0)
        want = {str(p.relative_to(C.TEMPLATE)) for p in C.TEMPLATE.rglob("*")
                if p.is_file() and p.suffix in (".toml", ".md")}
        self.assertEqual(set(tree(self.home)), want)
        self.assertIn("copy config.toml", out)
        for p in self.home.rglob("*"):
            self.assertNotIn(p.suffix, (".sh", ".hook", ".ts"), p)
        self.assertEqual(M.drift(self.home), [])

    def test_second_sync_changes_nothing(self):
        run_sync(self.home)
        before = tree(self.home)
        code, out, _ = run_sync(self.home)
        self.assertEqual(code, 0)
        self.assertEqual(tree(self.home), before)
        self.assertIn("is in sync with", out)

    def test_edited_file_stays_byte_identical(self):
        run_sync(self.home)
        p = self.home / "roles" / "review.toml"
        p.write_text(p.read_text() + "# mine\n")
        (self.home / "harnesses" / "pi.toml").unlink()
        data = p.read_bytes()
        self.assertEqual(M.drift(self.home), ["missing harnesses/pi.toml"])
        code, out, _ = run_sync(self.home)
        self.assertEqual(code, 0)
        self.assertEqual(p.read_bytes(), data)
        self.assertIn("copy harnesses/pi.toml", out)

    def test_deleted_key_is_re_added(self):
        run_sync(self.home)
        cfg = self.home / "config.toml"
        text = cfg.read_text().replace("timeout_min = 30", "timeout_min = 99")
        cfg.write_text("".join(x for x in text.splitlines(keepends=True) if not x.startswith("stop_at")))
        self.assertEqual(M.drift(self.home), ["missing key config.toml overnight.stop_at"])
        code, out, _ = run_sync(self.home, dry_run=True)
        self.assertIn("would add config.toml overnight.stop_at", out)
        self.assertNotIn("stop_at", cfg.read_text())
        code, out, _ = run_sync(self.home)
        self.assertEqual(code, 0)
        d = tomllib.loads(cfg.read_text())
        self.assertEqual(d["overnight"]["stop_at"], "")
        self.assertEqual(d["dispatch"]["timeout_min"], 99)
        want = tomllib.loads((C.TEMPLATE / "config.toml").read_text())
        want["dispatch"]["timeout_min"] = 99
        self.assertEqual(d, want)

    def test_symlinked_config_is_written_through(self):
        run_sync(self.home)
        cfg, real = self.home / "config.toml", Path(self._tmp.name) / "dotfiles" / "config.toml"
        real.parent.mkdir()
        real.write_text("".join(x for x in cfg.read_text().splitlines(keepends=True)
                                if not x.startswith("stop_at")))
        cfg.unlink()
        cfg.symlink_to(real)
        code, _, _ = run_sync(self.home)
        self.assertEqual(code, 0)
        self.assertTrue(cfg.is_symlink())
        self.assertEqual(tomllib.loads(real.read_text())["overnight"]["stop_at"], "")

    def test_unwritable_symlink_target_fails_cleanly(self):
        run_sync(self.home)
        ro = Path(self._tmp.name) / "ro"
        ro.mkdir()
        (ro / "config.toml").write_text("".join(x for x in (self.home / "config.toml").read_text()
                                                .splitlines(keepends=True) if not x.startswith("stop_at")))
        (self.home / "config.toml").unlink()
        (self.home / "config.toml").symlink_to("../ro/config.toml")
        ro.chmod(0o555)
        try:
            code, _, err = run_sync(self.home)
        finally:
            ro.chmod(0o755)
        self.assertEqual(code, 1)
        self.assertIn("cannot write", err)
        self.assertTrue((self.home / "config.toml").is_symlink())

    def test_missing_root_key_and_table(self):
        self.home.mkdir(parents=True)
        (self.home / "config.toml").write_text("[dispatch]\nvia = \"local\"\n")
        code, _, err = run_sync(self.home)
        self.assertEqual(code, 0, err)
        d = tomllib.loads((self.home / "config.toml").read_text())
        want = tomllib.loads((C.TEMPLATE / "config.toml").read_text())
        want["dispatch"]["via"] = "local"
        self.assertEqual(d, want)

    def test_inline_table_is_refused(self):
        self.home.mkdir(parents=True)
        cfg = self.home / "config.toml"
        cfg.write_text('dispatch = {via = "x"}\n')
        code, _, err = run_sync(self.home)
        self.assertEqual(code, 1)
        self.assertEqual(cfg.read_text(), 'dispatch = {via = "x"}\n')
        self.assertIn("cannot add", err)
        self.assertIn("dispatch.timeout_min", err)
        self.assertTrue((self.home / "roles" / "review.toml").is_file())  # files still copied

    def test_legacy_home_is_refused(self):
        self.home.mkdir(parents=True)
        cfg = self.home / "config.toml"
        cfg.write_text('[role.review]\nharness = "codex"\n')
        code, _, err = run_sync(self.home)
        self.assertEqual(code, 1)
        self.assertIn("sstack-config migrate", err)
        self.assertEqual([p.name for p in self.home.iterdir()], ["config.toml"])


if __name__ == "__main__":
    unittest.main()
