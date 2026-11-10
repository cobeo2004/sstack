"""Pick who runs a dispatch.

Order: --hint naming a config hint → a config hint whose paths match → the work kind
(--hint naming a built-in kind, or detected from the files) mapped to a tier → the role's
own config → local (this session). Built-in kinds only route implement, and only when
[tier.*] tables exist, so configs without tiers behave as before."""
import fnmatch
import subprocess
from pathlib import Path

from sstack_config import ConfigError, _member

KINDS = {  # checked by _kind(); order of the checks lives there
    "security": ["*auth*", "*crypto*", "*payment*", "*billing*", "*secret*", "*permission*",
                 "*migrations/*", "*migration/*"],
    "mobile": ["ios/*", "*/ios/*", "android/*", "*/android/*", "*.swift", "*.kt", "*.dart"],
    "frontend": ["*.tsx", "*.jsx", "*.vue", "*.svelte", "*.astro", "*.css", "*.scss", "*.html",
                 "*components/*", "*pages/*", "*/public/*"],
    "backend": ["*.go", "*.rs", "*.py", "*.java", "*.rb", "*.php", "*.cs", "*.sql",
                "api/*", "*/api/*", "server/*", "*/server/*", "db/*", "*/db/*"],
    "docs": ["*.md", "*.mdx", "*.rst", "*.txt", "docs/*"],
}
PROSE = [p for p in KINDS["docs"] if p.startswith("*.")]
PLAIN_JS = ("*.ts", "*.js", "*.mjs", "*.cjs", "*.mts", "*.cts")  # no framework in the extension
BACKEND_DIRS = {"functions", "supabase", "server", "api", "db"}
KIND_TIER = {"security": "strong", "complex": "strong", "frontend": "standard", "backend": "standard",
             "mobile": "standard", "mechanical": "cheap", "docs": "cheap"}
TIER_ORDER = ["cheap", "standard", "strong"]  # default escalation ladder (rules.tier_order)
PANEL_KINDS = {"security", "complex"}


def _match(f: str, pats: list[str]) -> bool:
    return any(fnmatch.fnmatch(f, p) for p in pats)


def _kind(f: str) -> str | None:
    """One kind per file, most specific first. A plain .ts/.js is backend under a server-ish
    directory and frontend anywhere else."""
    if _match(f, KINDS["security"]):
        return "security"
    if _match(f, KINDS["mobile"]):
        return "mobile"
    if _match(f, PLAIN_JS):
        # ponytail: a directory name, not an import graph; [role.*.hint.*] overrides.
        return "backend" if BACKEND_DIRS & set(Path(f).parts[:-1]) else "frontend"
    for k in ("frontend", "backend"):
        if _match(f, KINDS[k]):
            return k
    return "docs" if _match(f, KINDS["docs"]) else None


def classify(files: list[str]) -> str | None:
    if not files:
        return None
    # a prose-only change is not risky, even when it talks about auth; code under docs/ still is
    if all(_match(f, PROSE) or (_match(f, KINDS["docs"]) and not _match(f, KINDS["security"])) for f in files):
        return "docs"
    kinds = [_kind(f) for f in files]
    if "security" in kinds:
        return "security"
    areas = [k for k in ("frontend", "backend", "mobile") if k in kinds]
    # ponytail: "complex" = more than one area or a wide diff; a plan tag (--hint complex) covers the rest
    if len(areas) > 1 or len(files) > 20:
        return "complex"
    return areas[0] if areas else None


def changed(root: Path, base: str = "HEAD") -> tuple[list[str], int]:
    """Files changed against base (plus untracked) and the number of changed lines."""
    def git(*a):
        r = subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True)
        return r.stdout.splitlines() if r.returncode == 0 else []
    untracked = [f for f in git("ls-files", "--others", "--exclude-standard")
                 if not any(p.startswith(".") for p in Path(f).parts[:-1])]  # tool state, not work
    files = git("diff", "--name-only", base) + untracked
    lines = 0
    for row in git("diff", "--numstat", base):
        add, rm, _ = row.split("\t", 2)
        lines += int(add) + int(rm) if add != "-" else 0
    return sorted(set(files)), lines


def same(a: dict | None, b: dict | None) -> bool:
    """Same agent = same harness and model; effort doesn't make a different reviewer."""
    return bool(a and b) and (a["harness"], a["model"]) == (b["harness"], b["model"])


def tier_member(cfg: dict, tier: str | None, strict: bool = False) -> dict | None:
    spec = cfg.get("tier", {}).get(tier) if tier else None
    if tier and spec is None and strict:
        raise ConfigError(f"tier {tier!r} is not defined (add [tier.{tier}])")
    return _member(cfg, spec) if spec else None


def tier_of(cfg: dict, member: dict | None) -> str | None:
    return next((t for t in cfg.get("tier", {}) if same(tier_member(cfg, t), member)), None)


def kind_tiers(cfg: dict) -> dict[str, str]:
    """Built-in kind → tier, with [routing.kinds] remaps and new kind names on top."""
    return {**KIND_TIER, **cfg.get("routing", {}).get("kinds", {})}


def _hint_member(cfg: dict, h: dict) -> dict | None:
    return tier_member(cfg, h["tier"], strict=True) if "tier" in h else _member(cfg, h)


def variant_members(cfg: dict, v: dict) -> list[dict]:
    """A stage variant's members (its `panel`, else itself; harness/model or tier), tagged `variant`."""
    raw = v["spec"]["panel"] if "panel" in v["spec"] else [v["spec"]]
    return [{**m, "variant": v["id"]} for m in (_hint_member(cfg, x) for x in raw) if m]


def matches(v: dict, files: list[str]) -> bool:
    """A variant runs when a file matches its `paths` globs or its `kinds`; neither set → always."""
    paths, kinds = v["spec"].get("paths"), v["spec"].get("kinds")
    if not paths and not kinds:
        return True
    return any((paths and _match(f, paths)) or (kinds and _kind(f) in kinds) for f in files)


def pick(cfg: dict, role: str, hint: str | None, files: list[str]) -> tuple[dict | None, str, list[str]]:
    """(member or None for local, route label, notes)."""
    notes: list[str] = []
    if cfg.get("dispatch", {}).get("via") == "local":
        return None, "local (dispatch.via)", notes
    spec = cfg.get("role", {}).get(role) or {}
    hints = spec.get("hint", {})
    kt = kind_tiers(cfg)
    kind = hint if hint in kt else classify(files)
    # A security change goes to its tier, not to a path hint: the hint's paths (an auth
    # file, a migration) would quietly downgrade it. A named hint, or override_security, wins.
    risky = role == "implement" and kind == "security" and kt["security"] in cfg.get("tier", {})
    if hint and hint in hints:
        return _hint_member(cfg, hints[hint]), f"hint {hint}", notes
    for name, h in hints.items():
        if h.get("paths") and any(_match(f, h["paths"]) for f in files):
            if risky and not h.get("override_security"):
                notes.append(f"hint {name} skipped: security change (add override_security = true to keep it)")
                continue
            return _hint_member(cfg, h), f"hint {name} (paths)", notes
    if hint and hint not in kt:
        notes.append(f"unknown hint {hint!r}; known: {', '.join([*hints, *kt])}")
    if role == "implement" and kind and cfg.get("tier"):
        remapped = kind in cfg.get("routing", {}).get("kinds", {})
        if (m := tier_member(cfg, kt[kind], strict=remapped)):  # a built-in default tier may be absent
            return m, f"{'hint' if hint == kind else 'auto'} {kind} → tier.{kt[kind]}", notes
    if spec.get("harness"):
        return _member(cfg, spec), "role default", notes
    if "panel" in spec:
        return None, "panel", notes  # caller decides; a panel role has no single default
    return None, "local", notes  # an unlisted role stays in this session: cheapest, context is here


def escalation(cfg: dict, member: dict, avoid: dict | None = None) -> tuple[dict, str] | None:
    """The first tier above the failed member's on rules.tier_order that is a different agent and
    not `avoid` (the implementer, for a review). A member outside every tier goes to the top tier."""
    order = [t for t in cfg.get("rules", {}).get("tier_order", TIER_ORDER) if t in cfg.get("tier", {})]
    cur = tier_of(cfg, member)
    if cur is not None and cur not in order:
        return None  # a tier off the ladder doesn't escalate
    for t in (order[order.index(cur) + 1:] if cur else order[-1:]):
        m = tier_member(cfg, t)
        if m and not same(m, member) and not same(m, avoid):
            return m, t
    return None


def routes_text(cfg: dict, variants: list[dict] = ()) -> str:
    fmt = lambda m: f"{m['harness']}/{m['model'] or 'default'}" if m else "local"
    out = ["tiers:"]
    out += [f"  tier.{t} → {fmt(tier_member(cfg, t))}" for t in cfg.get("tier", {})] or ["  (none: kinds off)"]
    order = cfg.get("rules", {}).get("tier_order", TIER_ORDER)
    out.append(f"escalation: {' → '.join(order)}")
    out.append("kinds (implement; --hint <kind> or detected from --files):")
    for k, t in kind_tiers(cfg).items():
        m = tier_member(cfg, t)
        out.append(f"  {k}: tier.{t} → {fmt(m)}" if m else f"  {k}: tier.{t} (undefined)")
    out.append("hints (config):")
    for role, spec in cfg.get("role", {}).items():
        for name, h in (spec.get("hint") or {}).items():
            out.append(f"  {role}.{name}: {h.get('when', '')} → {fmt(_hint_member(cfg, h))}")
    out.append("variants (run beside the stage default; roles/<stage>/<name>.toml):")
    for v in variants:
        ms = ", ".join(map(fmt, variant_members(cfg, v))) or "local"
        out.append(f"  {v['id']}: {v['spec'].get('when', '')} → {ms} ({v['layer']})")
    return "\n".join(out) + "\n"
