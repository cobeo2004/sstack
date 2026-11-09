const ui = window.SSTACK.ui;
const { el, api, state, setStatus, showDoctor, sourceChip } = ui;

const GROUP_ORDER = ["config", "project", "harnesses", "roles", "tiers", "ades"];
const GROUP_LABEL = {
  config: "Config",
  project: "Project",
  harnesses: "Harnesses",
  roles: "Roles",
  tiers: "Tiers",
  ades: "ADEs",
};

let selected = { kind: "config", name: "" };
let editorLayer = null;
let nextLayer = null;
let requestSeq = 0;
let inspector = null;
let unsaved = null;  // the label of the thing whose editor holds unsaved TOML, or null

function thingKey(thing) {
  return `${thing.kind}:${thing.name}`;
}

function findThing(kind, name) {
  return (state.config?.things || []).find((t) => t.kind === kind && t.name === name);
}

function route(thing, layer) {
  const parts = ["/api/config", encodeURIComponent(layer), encodeURIComponent(thing.kind)];
  if (thing.name) parts.push(encodeURIComponent(thing.name));
  return parts.join("/");
}

function summary(thing) {
  const value = thing.value || {};
  if (thing.kind === "config") {
    const via = value.dispatch?.via || "auto";
    return `ade ${value.ade || "auto"} / via ${via}`;
  }
  if (thing.kind === "project") {
    const bits = [value.name, value.language, value.commands ? "commands set" : null].filter(Boolean);
    return bits.join(" / ") || "repository identity";
  }
  if (thing.kind === "roles") {
    if (Array.isArray(value.panel)) return `panel of ${value.panel.length}`;
    if (!value.harness || value.harness === "local") return "local session";
    return `${value.harness} / ${value.model || "default model"}`;
  }
  if (thing.kind === "harnesses") {
    const argv = value.headless || [];
    return argv.length ? argv.join(" ") : "no headless command";
  }
  if (thing.kind === "tiers") {
    return [value.harness, value.model, value.effort].filter(Boolean).join(" / ") || "empty tier";
  }
  if (thing.kind === "ades") {
    const detect = value.detect?.env || [];
    return `${value.auto === false ? "manual" : "auto"} / ${detect.length ? detect.join(", ") : "no env marker"}`;
  }
  return "";
}

function shortPath(path, layer) {
  // The layer is already named in the select and the chip, so the path only needs the part inside it.
  const root = (state.config?.layers || []).find((l) => l.name === layer)?.path;
  return root && path.startsWith(`${root}/`) ? path.slice(root.length + 1) : path;
}

function isDirty() {
  return Boolean(unsaved);
}

function confirmDiscard() {
  if (!isDirty()) return true;
  return window.confirm(`Discard the unsaved changes to ${unsaved}?`);
}

function pageHead() {
  return el("header", { class: "page-head" },
    el("h1", { text: "Config" }),
    el("p", { text: "Every effective setting, the layer whose file wins, and a safe editor for that file." }),
  );
}

function rowName(thing) {
  // The group heading already names the kind, so the row only carries the part that varies.
  return thing.name || thing.label;
}

function ledger(host) {
  const panel = el("div", { class: "ledger-panel" });
  for (const kind of GROUP_ORDER) {
    const things = (state.config.things || []).filter((t) => t.kind === kind);
    if (!things.length) continue;
    const group = el("section", { class: "kind-group" },
      el("div", { class: "kind-label" },
        el("span", { text: GROUP_LABEL[kind] }),
        el("span", { class: "mono", text: String(things.length) }),
      ));
    for (const thing of things) {
      group.append(el("button", {
        type: "button",
        class: "ledger-row",
        dataset: { thing: thingKey(thing) },
        "aria-current": thingKey(thing) === thingKey(selected) ? "true" : null,
        onclick: () => openThing(thing, null, { reveal: true }),
      },
        el("span", { class: "thing-name", text: rowName(thing) }),
        el("span", { class: "thing-detail", text: summary(thing) }),
        sourceChip(thing.source),
      ));
    }
    panel.append(group);
  }
  host.append(panel);
}

function updateRowSelection() {
  for (const row of document.querySelectorAll("#page-config .ledger-row")) {
    if (row.dataset.thing === thingKey(selected)) row.setAttribute("aria-current", "true");
    else row.removeAttribute("aria-current");
  }
}

async function openThing(thing, layer = null, options = {}) {
  if (!options.force && !confirmDiscard()) return false;
  selected = thing;
  editorLayer = layer || ui.defaultLayer(thing.source);
  unsaved = null;
  state.preferredLayer = editorLayer;
  ui.renderSpine(editorLayer);
  updateRowSelection();
  const seq = ++requestSeq;
  inspector.replaceChildren(el("p", { class: "loading", text: `Reading ${thing.label}…` }));
  try {
    const data = await api(route(thing, editorLayer));
    if (seq !== requestSeq) return false;
    renderEditor(thing, data, options);
  } catch (err) {
    if (seq !== requestSeq) return false;
    inspector.replaceChildren(
      el("h2", { text: thing.label }),
      el("p", { class: "error-text", text: err.message }),
    );
  }
  return true;
}

function revealInspector() {
  if (!matchMedia("(max-width: 760px)").matches) return;
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  inspector.scrollIntoView({ block: "start", behavior: reduce ? "auto" : "smooth" });
}

function renderEditor(thing, data, options = {}) {
  const winning = Boolean(thing.source) && thing.source === data.layer;
  const area = el("textarea", {
    id: "editor-text",
    spellcheck: "false",
    "aria-label": `TOML for ${thing.label} in the ${data.layer} layer`,
    placeholder: data.exists ? "" : "This layer has no override yet. Paste a TOML file here.",
  });
  area.value = data.text;
  unsaved = null;

  const layerSelect = el("select", { id: "editor-layer", "aria-label": "Edit layer" });
  for (const name of ui.editableLayers()) {
    layerSelect.append(el("option", { value: name, text: name, selected: name === data.layer }));
  }
  layerSelect.value = data.layer;
  layerSelect.addEventListener("change", async () => {
    const moved = await openThing(thing, layerSelect.value);
    if (!moved) layerSelect.value = editorLayer;
  });

  const save = el("button", { type: "button", class: "primary", text: `Save to ${data.layer}` });
  const reset = el("button", {
    type: "button",
    class: "danger",
    text: "Reset to inherited",
    disabled: !data.exists,
  });
  const error = el("p", { class: "hint error-text", hidden: true });

  area.addEventListener("input", () => {
    unsaved = area.value === data.text ? null : thing.label;
  });

  save.addEventListener("click", async () => {
    save.disabled = true;
    reset.disabled = true;
    error.hidden = true;
    try {
      await api(route(thing, data.layer), { method: "PUT", body: { text: area.value } });
      setStatus(`Saved ${thing.label} to ${data.layer}`, "ok");
      unsaved = null;
      showDoctor();
      nextLayer = data.layer;
      await ui.refresh();
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
      setStatus("Save refused", "bad");
      save.disabled = false;
      reset.disabled = !data.exists;
    }
  });

  reset.addEventListener("click", async () => {
    const ok = window.confirm(
      `Reset ${thing.label} to inherited? The ${data.layer} override will be deleted.`);
    if (!ok) return;
    save.disabled = true;
    reset.disabled = true;
    error.hidden = true;
    try {
      await api(route(thing, data.layer), { method: "DELETE" });
      setStatus(`Reset ${thing.label} to inherited`, "ok");
      unsaved = null;
      showDoctor();
      nextLayer = data.layer;
      await ui.refresh();
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
      setStatus("Reset refused", "bad");
      save.disabled = false;
      reset.disabled = !data.exists;
    }
  });

  inspector.replaceChildren(
    el("h2", { text: thing.label }),
    el("p", { class: "path mono", title: data.path, text: shortPath(data.path, data.layer) }),
    el("div", { class: "inspector-meta" },
      sourceChip(thing.source),
      el("span", { text: winning ? "this file wins" : `wins; you are editing ${data.layer}` }),
    ),
    el("div", { class: "field" },
      el("label", { for: "editor-layer", text: "Edit layer" }),
      layerSelect,
    ),
    el("div", { class: "field" },
      el("label", { for: "editor-text", text: data.exists ? `${data.layer} override` : `${data.layer} has no override` }),
      area,
    ),
    error,
    el("div", { class: "actions" }, reset, save),
    el("p", { class: "hint", text: "A save is checked against a copy of the whole layered tree. An invalid file is refused and nothing is written." }),
  );
  if (!winning) showWinningFile(thing);
  if (options.reveal) revealInspector();
}

async function showWinningFile(thing) {
  const seq = requestSeq;
  const host = el("div", { class: "field" }, el("p", { class: "field-label", text: "Loading the winning file…" }));
  inspector.append(host);
  if (!ui.editableLayers().includes(thing.source)) {
    host.replaceChildren(el("p", { class: "field-label" },
      el("span", { text: `The winning file is the built-in ${thing.source} default, which this page never edits.` })));
    return;
  }
  try {
    const win = await api(route(thing, thing.source));
    if (seq !== requestSeq) return;
    host.replaceChildren(
      el("p", { class: "field-label", text: `Winning file in the ${thing.source} layer` }),
      el("div", { class: "winning" }, el("pre", { text: win.text || "empty file" })),
    );
  } catch (err) {
    host.replaceChildren(
      el("p", { class: "field-label", text: `Winning file in the ${thing.source} layer` }),
      el("p", { class: "error-text", text: err.message }),
    );
  }
}

export async function render(host) {
  if (!state.config) await ui.loadConfig();
  const fresh = findThing(selected.kind, selected.name);
  if (fresh) selected = fresh;
  unsaved = null;
  state.guard = confirmDiscard;
  host.append(pageHead());
  const workspace = el("div", { class: "config-workspace" });
  ledger(workspace);
  inspector = el("aside", { class: "inspector", "aria-label": "Selected config file" });
  workspace.append(inspector);
  host.append(workspace);
  await openThing(selected, nextLayer || ui.defaultLayer(selected.source), { force: true });
  nextLayer = null;
}
