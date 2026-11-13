const { el, api, setStatus } = window.SSTACK.ui;

const SVG_NS = "http://www.w3.org/2000/svg";

function svg(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  return node;
}

// Deterministic force layout: circle seed in name order, fixed iteration count, no randomness.
export function layout(names, edges, iters = 300) {
  const n = names.length, at = new Map(names.map((x, i) => [x, i]));
  const R = 60 + 40 * Math.sqrt(n);
  const p = names.map((_, i) => ({ x: R * Math.cos(2 * Math.PI * i / n), y: R * Math.sin(2 * Math.PI * i / n) }));
  const E = edges.map(([a, b]) => [at.get(a), at.get(b)]);
  for (let it = 0; it < iters; it++) {
    const t = 30 * (1 - it / iters) + 1;            // temperature: largest step this round
    const f = p.map(() => ({ x: 0, y: 0 }));
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
      let dx = p[i].x - p[j].x, dy = p[i].y - p[j].y;
      if (!dx && !dy) { dx = 0.01 * (j - i); dy = 0.01; }   // deterministic nudge, never random
      const d2 = dx * dx + dy * dy, d = Math.sqrt(d2), k = 4000 / d2;
      f[i].x += k * dx / d; f[i].y += k * dy / d; f[j].x -= k * dx / d; f[j].y -= k * dy / d;
    }
    for (const [a, b] of E) {
      const dx = p[b].x - p[a].x, dy = p[b].y - p[a].y, d = Math.hypot(dx, dy) || 0.01, k = 0.05 * (d - 90);
      f[a].x += k * dx / d; f[a].y += k * dy / d; f[b].x -= k * dx / d; f[b].y -= k * dy / d;
    }
    for (let i = 0; i < n; i++) {
      f[i].x -= 0.01 * p[i].x; f[i].y -= 0.01 * p[i].y;   // gravity to the centre
      const m = Math.hypot(f[i].x, f[i].y);
      if (m > t) { f[i].x *= t / m; f[i].y *= t / m; }
      p[i].x += f[i].x; p[i].y += f[i].y;
    }
  }
  return p;   // ponytail: O(n²)/iteration, fine to ~300 pages; Barnes-Hut if a wiki outgrows it
}

function pageHead() {
  return el("header", { class: "page-head" },
    el("h1", { text: "Wiki" }),
    el("p", { text: "Pages of the sstack wiki and how they link. Read-only: change pages in your editor, then run sstack-wiki index." }),
  );
}

function empty(title, body, cls = "") {
  return el("div", { class: "empty" }, el("h2", { text: title }), el("p", { class: cls, text: body }));
}

function lintBlock(lint) {
  const errors = lint.errors || [], warnings = lint.warnings || [];
  if (!errors.length && !warnings.length) return null;
  const items = (list, tone) => list.map((m) => el("li", { class: tone, text: m }));
  return el("details", { class: "wiki-lint", open: errors.length > 0 },
    el("summary", { text: `Lint: ${errors.length} errors, ${warnings.length} warnings` }),
    el("ul", {}, items(errors, "bad"), items(warnings, "warn")),
  );
}

export async function render(host) {
  host.append(pageHead());
  try {
    const data = await api("/api/wiki");
    const pages = data.pages || [];
    if (!pages.length) {
      host.append(empty("No sstack wiki yet", "Run setup to seed .sstack/wiki/, then sstack-wiki index."));
      return;
    }
    const lint = data.lint || { errors: [], warnings: [] };
    const e = lint.errors.length, w = lint.warnings.length;
    setStatus(`Wiki: ${e} errors, ${w} warnings`, e ? "bad" : w ? "warn" : "ok");

    const byName = new Map(pages.map((pg) => [pg.name, pg]));
    const names = pages.map((pg) => pg.name);
    const seen = new Set(), edges = [];
    for (const pg of pages) {
      for (const l of pg.links) {
        if (!byName.has(l) || l === pg.name) continue;   // broken links are lint's job, not edges
        const key = pg.name < l ? `${pg.name}\u0000${l}` : `${l}\u0000${pg.name}`;
        if (seen.has(key)) continue;
        seen.add(key);
        edges.push(pg.name < l ? [pg.name, l] : [l, pg.name]);
      }
    }
    const pos = layout(names, edges);
    const xs = pos.map((q) => q.x), ys = pos.map((q) => q.y);
    const x0 = Math.min(...xs) - 40, y0 = Math.min(...ys) - 40;
    const vw = Math.max(...xs) + 40 - x0, vh = Math.max(...ys) + 40 - y0;

    const canvas = svg("svg", {
      class: "wiki-svg", role: "img", viewBox: `${x0} ${y0} ${vw} ${vh}`,
      "aria-label": `Wiki link graph: ${pages.length} pages, ${edges.length} links`,
    });
    const idx = new Map(names.map((nm, i) => [nm, i]));
    const edgeEls = edges.map(([a, b]) => {
      const line = svg("line", {
        class: "wiki-edge", x1: pos[idx.get(a)].x, y1: pos[idx.get(a)].y, x2: pos[idx.get(b)].x, y2: pos[idx.get(b)].y,
      });
      canvas.append(line);
      return line;
    });
    const nodeEls = new Map();
    for (const pg of pages) {
      const q = pos[idx.get(pg.name)];
      const g = svg("g", { class: `wiki-node${pg.stale ? " stale" : ""}${pg.orphan ? " orphan" : ""}` });
      g.append(svg("circle", { r: 7, cx: q.x, cy: q.y }));
      const label = svg("text", { x: q.x, y: q.y + 20 });
      label.textContent = pg.name;
      g.append(label);
      g.addEventListener("click", () => select(pg.name));
      canvas.append(g);
      nodeEls.set(pg.name, g);
    }

    const buttons = new Map();
    const list = el("ul", { class: "wiki-list", "aria-label": "Wiki pages" });
    for (const pg of pages) {
      const b = el("button", { type: "button" },
        el("span", { text: pg.name }),
        pg.stale ? el("span", { class: "tag", dataset: { tone: "warn" }, text: "stale" }) : null,
        pg.orphan ? el("span", { class: "tag", text: "orphan" }) : null,
      );
      b.addEventListener("click", () => select(pg.name));
      buttons.set(pg.name, b);
      list.append(el("li", {}, b));
    }

    const panel = el("aside", { class: "wiki-panel", "aria-label": "Page details" });
    let current = null;

    function linkList(title, items) {
      return [
        el("h3", { text: title }),
        items.length
          ? el("ul", { class: "wiki-links" }, items.map((nm) => {
              const b = el("button", { type: "button", text: nm });
              b.addEventListener("click", () => select(nm));
              return el("li", {}, b);
            }))
          : el("p", { class: "hint", text: "none" }),
      ];
    }

    async function select(name, focus = true) {
      const pg = byName.get(name);
      if (!pg) return;
      current = name;
      for (const [nm, g] of nodeEls) g.classList.toggle("selected", nm === name);
      for (const [nm, b] of buttons) {
        if (nm === name) b.setAttribute("aria-current", "true");
        else b.removeAttribute("aria-current");
      }
      edges.forEach(([a, b], i) => edgeEls[i].classList.toggle("hot", a === name || b === name));
      const heading = el("h2", { tabindex: "-1", text: pg.name });
      const raw = el("pre", { class: "wiki-raw", text: "Loading…" });
      panel.replaceChildren(
        heading,
        el("p", { text: pg.summary || "(no summary)" }),
        el("dl", {},
          el("dt", { text: "paths" }), el("dd", { text: (pg.paths || []).join(", ") || "none" }),
          el("dt", { text: "updated" }), el("dd", { text: pg.updated || "unknown" }),
          pg.stale ? el("dt", { text: "stale" }) : null,
          pg.stale ? el("dd", {}, el("span", { class: "tag", dataset: { tone: "warn" }, text: "stale" })) : null,
        ),
        ...linkList("Links", pg.links),
        ...linkList("Backlinks", pg.backlinks),
        el("h3", { text: "Raw page" }),
        raw,
      );
      if (focus) heading.focus({ preventScroll: true });
      try {
        const page = await api(`/api/wiki/page?name=${encodeURIComponent(name)}`);
        if (current === name) raw.textContent = page.text;   // textContent only: page text is never HTML
      } catch (err) {
        if (current === name) raw.textContent = `Could not load page: ${err.message}`;
      }
    }

    const lb = lintBlock(lint);
    if (lb) host.append(lb);
    host.append(el("div", { class: "wiki-layout" }, list, canvas, panel));
    await select(pages[0].name, false);
  } catch (err) {
    host.append(empty("Wiki could not load", err.message, "error-text"));
  }
}
