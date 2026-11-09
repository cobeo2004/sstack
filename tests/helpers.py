import os, re, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures"
EXAMPLE = FIXTURES / "config" / "example-equivalent" / "home"  # the old single-file example, split
sys.path.insert(0, str(REPO / "lib"))

_HEADER = re.compile(r"^\[([A-Za-z0-9_.-]+)\]\s*(#.*)?$")
_SPLIT = {"harness": "harnesses", "role": "roles", "tier": "tiers"}
_LAYOUT = ("config.toml", "project.toml", "harnesses", "roles", "tiers", "ades")


def split_toml(text: str) -> dict[str, str]:
    """Single-file TOML text → {relative path: text} in the split layout. Textual on purpose:
    [harness.X], [role.X], [tier.X] (and their sub-tables) and [project] move to their own file;
    everything else stays in config.toml, so bad TOML still lands somewhere and still errors."""
    out: dict[str, str] = {}
    cur = "config.toml"
    for line in text.splitlines(keepends=True):
        m = _HEADER.match(line.strip())
        if m:
            parts = m[1].split(".")
            if parts[0] in _SPLIT and len(parts) > 1:
                cur, rest = f"{_SPLIT[parts[0]]}/{parts[1]}.toml", parts[2:]
            elif parts[0] == "project":
                cur, rest = "project.toml", parts[1:]
            else:
                cur, rest = "config.toml", None
            if rest is not None:
                line = f"[{'.'.join(rest)}]\n" if rest else ""
        out[cur] = out.get(cur, "") + line
    return out


class TempEnv(unittest.TestCase):
    """Temp HOME + temp git repo; restores HOME (and SSTACK_HOME) afterwards."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name).resolve()
        self.home = base / "home"
        self.root = base / "repo"
        self.home.mkdir()
        self.root.mkdir()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self._old = {k: os.environ.get(k) for k in ("HOME", "SSTACK_HOME")}
        os.environ["HOME"] = str(self.home)
        os.environ.pop("SSTACK_HOME", None)

    def tearDown(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def write(self, rel_base: Path, rel: str, text: str) -> Path:
        p = rel_base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def layer_cfg(self, layer: Path, text: str) -> Path:
        """Replace one layer's config with `text` (single-file TOML), written in the split layout."""
        for name in _LAYOUT:
            p = layer / name
            shutil.rmtree(p) if p.is_dir() else p.unlink(missing_ok=True)
        files = split_toml(text)
        written = [self.write(layer, rel, body) for rel, body in files.items()]
        return layer / "config.toml" if "config.toml" in files else written[0]

    def glob_cfg(self, text):
        return self.layer_cfg(self.home / ".sstack", text)

    def repo_cfg(self, text):
        return self.layer_cfg(self.root / ".sstack", text)

    def local_cfg(self, text):
        return self.layer_cfg(self.root / ".sstack" / "local", text)

    def example(self):
        """The home layer equivalent to the old single-file example config."""
        shutil.copytree(EXAMPLE, self.home / ".sstack", dirs_exist_ok=True)
