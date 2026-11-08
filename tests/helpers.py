import os, subprocess, sys, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "lib"))


class TempEnv(unittest.TestCase):
    """Temp HOME + temp git repo; restores HOME afterwards."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name).resolve()
        self.home = base / "home"
        self.root = base / "repo"
        self.home.mkdir()
        self.root.mkdir()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = str(self.home)

    def tearDown(self):
        if self._old_home is not None:
            os.environ["HOME"] = self._old_home
        self._tmp.cleanup()

    def write(self, rel_base: Path, rel: str, text: str) -> Path:
        p = rel_base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def glob_cfg(self, text):
        return self.write(self.home, ".sstack/config.toml", text)

    def repo_cfg(self, text):
        return self.write(self.root, ".sstack/config.toml", text)

    def local_cfg(self, text):
        return self.write(self.root, ".sstack/config.local.toml", text)
