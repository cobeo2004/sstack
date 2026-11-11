"""Plugin manifests (docs/guide/getting-started.md#install-as-a-plugin): one repo, one skills/ tree,
one manifest per harness. Each must parse, be named sstack, share one version, and point at real paths."""
import json, re, unittest

from helpers import REPO

# path -> carries a version. The version's home is .claude-plugin/plugin.json; the rest must match it.
MANIFESTS = {
    ".claude-plugin/plugin.json": True,       # Claude Code
    ".claude-plugin/marketplace.json": False,  # Claude Code: the repo is its own marketplace
    "plugin.json": True,                       # Agent Plugins: Codex and Cursor
    ".agents/plugins/marketplace.json": False, # Codex marketplace
    "package.json": True,                      # pi package
    "gemini-extension.json": True,             # Gemini CLI
}
SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
REPO_URL = "https://github.com/cobeo2004/sstack.git"
DOC = REPO / "docs" / "guide" / "getting-started.md"


def load(rel):
    return json.loads((REPO / rel).read_text())


def at_root(rel):
    return ".." not in rel and (REPO / rel).resolve() == REPO.resolve()


class PluginManifests(unittest.TestCase):
    def test_every_manifest_parses_and_is_named_sstack(self):
        for rel in MANIFESTS:
            with self.subTest(rel):
                self.assertTrue((REPO / rel).is_file(), f"missing {rel}")
                self.assertEqual(load(rel).get("name"), "sstack")

    def test_one_version(self):
        want = load(".claude-plugin/plugin.json").get("version", "")
        self.assertRegex(want, r"^\d+\.\d+\.\d+$")
        for rel, has in MANIFESTS.items():
            with self.subTest(rel):
                if has:
                    self.assertEqual(load(rel).get("version"), want)
                else:  # a second copy in a marketplace entry would drift
                    self.assertNotIn("version", json.dumps(load(rel)))

    def test_claude_marketplace_source_is_the_repo_root(self):
        m = load(".claude-plugin/marketplace.json")
        self.assertTrue(m.get("owner", {}).get("name"))
        [entry] = m["plugins"]
        self.assertEqual(entry["name"], load(".claude-plugin/plugin.json")["name"])
        self.assertIsInstance(entry["source"], str)
        self.assertTrue(at_root(entry["source"]), entry["source"])  # resolves from the dir holding .claude-plugin/

    def test_agent_plugin_manifest(self):
        p = load("plugin.json")
        self.assertEqual(p.get("$schema"), SCHEMA)
        self.assertRegex(p["name"], r"^[a-z0-9][a-z0-9.-]{0,63}$")
        self.assertTrue((REPO / "skills").is_dir())
        for d in (".codex-plugin", ".cursor-plugin"):
            self.assertFalse((REPO / d).exists(), f"{d}/ duplicates root plugin.json")

    def test_codex_marketplace_points_at_this_repo(self):
        [entry] = load(".agents/plugins/marketplace.json")["plugins"]
        self.assertEqual(entry["name"], "sstack")
        src = entry["source"]
        if src.get("source") == "local":
            self.assertTrue(at_root(src.get("path", "")), src)
        else:
            self.assertEqual(src, {"source": "url", "url": REPO_URL})
        self.assertEqual(entry.get("policy", {}).get("installation"), "AVAILABLE")

    def test_pi_package_paths_exist(self):
        p = load("package.json")
        self.assertIs(p.get("private"), True, "never npm-published")
        for key in ("dependencies", "devDependencies", "scripts"):
            self.assertNotIn(key, p, "stdlib only; nothing runs on install")
        pi = p.get("pi", {})
        self.assertTrue(pi.get("skills") and pi.get("extensions"), pi)
        for rel in pi["skills"] + pi["extensions"]:
            with self.subTest(rel):
                self.assertTrue(rel.startswith("./") and ".." not in rel, rel)
                self.assertTrue((REPO / rel).exists(), rel)
        self.assertIn("./defaults/hooks/pi-sstack.ts", pi["extensions"])
        self.assertTrue((REPO / "skills" / "sstack" / "SKILL.md").is_file())

    def test_skill_frontmatter_is_portable(self):
        files = sorted((REPO / "skills").glob("*/SKILL.md"))
        self.assertTrue(files)
        for f in files:
            with self.subTest(f.parent.name):
                lines = f.read_text().split("\n")
                self.assertEqual(lines[0], "---")
                end = lines.index("---", 1)
                keys = {m[1] for l in lines[1:end] if (m := re.match(r"([A-Za-z_][\w-]*)\s*:", l))}
                self.assertEqual(keys, {"name", "description"})

    def test_docs_give_one_command_per_harness(self):
        text = DOC.read_text()
        self.assertIn("\n## Install as a plugin\n", text)
        sec = text.split("\n## Install as a plugin\n", 1)[1].split("\n## ", 1)[0]
        for s in ("claude plugin marketplace add cobeo2004/sstack", "claude plugin install sstack@sstack",
                  "codex plugin marketplace add cobeo2004/sstack", "pi install git:github.com/cobeo2004/sstack",
                  "gemini extensions install https://github.com/cobeo2004/sstack", "Cursor",
                  "sstack-config sync", "\n### Not yet verified\n"):
            self.assertIn(s, sec)
        layout = (REPO / "docs" / "guide" / "contributing.md").read_text()
        for rel in list(MANIFESTS) + ["test_plugins.py"]:
            self.assertIn(rel.split("/")[-1] if rel.startswith(".claude") else rel, layout)


if __name__ == "__main__":
    unittest.main()
