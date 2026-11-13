const token = window.SSTACK.token;

const state = {
  repo: window.SSTACK.repo || "global",
  page: (location.hash || "#config").slice(1) || "config",
  config: null,
  preferredLayer: null,
  // Set by the Config page: returns false when unsaved edits should keep the selection put.
  guard: null,
};

const pageModules = new Map();
const schemeQuery = matchMedia("(prefers-color-scheme: dark)");

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = String(value);
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2), value);
    } else if (key === "dataset") {
      Object.assign(node.dataset, value);
    } else if (key === "value") {
      node.value = value;
    } else if (value === true) {
      node.setAttribute(key, "");
    } else {
      node.setAttribute(key, String(value));
    }
  }
  append(node, children);
  return node;
}

function append(node, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

async function api(path, options = {}) {
  const url = new URL(path, location.origin);
  url.searchParams.set("t", token);
  if (path.startsWith("/api/") && !path.startsWith("/api/repos") && !url.searchParams.has("repo")) {
    url.searchParams.set("repo", state.repo);
  }
  const method = options.method || "GET";
  const init = { method, headers: { Accept: "application/json" } };
  if (method !== "GET" && method !== "HEAD") init.headers["Content-Type"] = "application/json";
  if (options.body !== undefined) init.body = JSON.stringify(options.body);
  const response = await fetch(url, init);
  const raw = await response.text();
  let data = null;
  try {
    data = raw ? JSON.parse(raw) : null;
  } catch {
    data = { error: raw || `HTTP ${response.status}` };
  }
  if (!response.ok) {
    const err = new Error(data && data.error ? data.error : `HTTP ${response.status}`);
    err.status = response.status;
    throw err;
  }
  return data;
}

function setStatus(text, tone = "") {
  const node = document.getElementById("bench-status");
  node.textContent = text;
  node.className = `bench-status ${tone}`.trim();
}

function showDoctor() {
  const banner = document.getElementById("doctor-banner");
  banner.hidden = false;
  banner.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function hideDoctor() {
  document.getElementById("doctor-banner").hidden = true;
}

function sourceChip(layer) {
  return el("span", {
    class: "source-chip",
    dataset: { layer: layer || "none" },
    text: layer || "unset",
  });
}

function layerNames() {
  return state.config ? state.config.layers.map((l) => l.name) : ["defaults", "home"];
}

function editableLayers() {
  return layerNames().filter((name) => name !== "defaults");
}

function defaultLayer(sourceName) {
  const names = editableLayers();
  // Inside a repository an override belongs in .sstack/local/ unless it already lives elsewhere.
  if (state.repo !== "global" && names.includes("local")) return "local";
  if (names.includes(sourceName)) return sourceName;
  return names.includes("local") ? "local" : (names[0] || "home");
}

function renderSpine(activeLayer = null) {
  const list = document.getElementById("layer-spine");
  if (!state.config) return;
  clear(list);
  for (const layer of state.config.layers) {
    list.append(el("li", {
      class: `layer-item${layer.name === activeLayer ? " active" : ""}`,
      dataset: { layer: layer.name },
      title: layer.path,
    },
      el("span", { class: "layer-mark" }),
      el("span", { class: "layer-name", text: layer.name }),
      el("span", { class: "layer-count", text: String(layer.count) }),
    ));
  }
  document.getElementById("spine-note").textContent = activeLayer
    ? `You are editing ${activeLayer}. The marked layer is the one that wins for the selected setting.`
    : "Lowest layer first. The marked layer wins for the selected setting.";
}

async function loadConfig() {
  state.config = await api("/api/config");
  renderSpine(state.preferredLayer);
  return state.config;
}

async function loadRepos() {
  const select = document.getElementById("repo-select");
  let repos = [];
  try {
    repos = (await api("/api/repos")).repos;
  } catch {
    repos = [];
  }
  clear(select);
  const options = [{ value: "global", label: "global" }];
  for (const path of repos) {
    options.push({ value: path, label: path.split("/").filter(Boolean).pop() || path });
  }
  if (state.repo !== "global" && !options.some((o) => o.value === state.repo)) {
    options.push({ value: state.repo, label: state.repo.split("/").filter(Boolean).pop() || state.repo });
  }
  for (const option of options) {
    select.append(el("option", { value: option.value, text: option.label, title: option.value }));
  }
  select.value = state.repo;
  select.addEventListener("change", async () => {
    if (state.guard && !state.guard()) {
      select.value = state.repo;
      return;
    }
    state.repo = select.value;
    state.config = null;
    state.preferredLayer = null;
    localStorage.setItem("sstack.repo", state.repo);
    setStatus("Loading repository");
    try {
      await refresh();
      setStatus("127.0.0.1 only");
    } catch (err) {
      setStatus(err.message, "bad");
    }
  });
}

function currentDark() {
  const chosen = localStorage.getItem("sstack.theme");
  return chosen ? chosen === "dark" : schemeQuery.matches;
}

function applyTheme(chosen) {
  if (chosen) document.documentElement.dataset.theme = chosen;
  else delete document.documentElement.dataset.theme;
  const dark = currentDark();
  // The label names what the button switches *to*, so it is never stale after a system change.
  document.getElementById("theme-toggle").textContent = dark ? "Light theme" : "Dark theme";
}

function fmtTime(value) {
  if (!value) return "no timestamp";
  return String(value).replace("T", " ").replace("Z", "");
}

async function mountPage(name, { focusMain = true } = {}) {
  const known = ["config", "ade", "runs", "lessons", "wiki", "graph"];
  if (!known.includes(name)) name = "config";
  state.page = name;
  document.body.dataset.page = name;
  state.guard = null;  // a page arms its own discard guard, if it has one
  history.replaceState(null, "", `#${name}`);
  for (const button of document.querySelectorAll(".pages button")) {
    if (button.dataset.page === name) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  for (const section of document.querySelectorAll(".page")) {
    section.classList.toggle("active", section.id === `page-${name}`);
  }
  const host = document.getElementById(`page-${name}`);
  clear(host);
  host.append(el("p", { class: "loading", text: "Loading…" }));
  try {
    let module = pageModules.get(name);
    if (!module) {
      module = await import(`/ui/pages/${name}.js?t=${encodeURIComponent(token)}`);
      pageModules.set(name, module);
    }
    clear(host);
    await module.render(host);
    // Only a deliberate navigation moves focus; a page load leaves the caret where it was.
    if (focusMain) document.getElementById("main").focus({ preventScroll: true });
  } catch (err) {
    clear(host);
    host.append(el("div", { class: "empty" },
      el("h2", { text: "This page could not load" }),
      el("p", { class: "error-text", text: err.message }),
      el("p", { text: "Check the repository selection, then try again." }),
    ));
  }
}

async function refresh() {
  await loadConfig();
  await mountPage(state.page);
}

async function start() {
  applyTheme(localStorage.getItem("sstack.theme") || "");
  schemeQuery.addEventListener("change", () => {
    if (!localStorage.getItem("sstack.theme")) applyTheme("");
  });
  document.getElementById("theme-toggle").addEventListener("click", () => {
    const next = currentDark() ? "light" : "dark";
    localStorage.setItem("sstack.theme", next);
    applyTheme(next);
  });
  document.getElementById("doctor-dismiss").addEventListener("click", hideDoctor);
  for (const button of document.querySelectorAll(".pages button")) {
    button.addEventListener("click", () => {
      if (state.guard && !state.guard()) return;
      mountPage(button.dataset.page);
    });
  }
  window.addEventListener("hashchange", () => {
    const name = (location.hash || "#config").slice(1);
    if (name === state.page) return;
    if (state.guard && !state.guard()) {
      history.replaceState(null, "", `#${state.page}`);
      return;
    }
    mountPage(name);
  });
  await loadRepos();
  try {
    await loadConfig();
  } catch (err) {
    setStatus(err.message, "bad");
    const host = document.getElementById("page-config");
    host.classList.add("active");
    host.append(el("div", { class: "empty" },
      el("h2", { text: "Config could not load" }),
      el("p", { class: "error-text", text: err.message }),
    ));
    return;
  }
  await mountPage(state.page, { focusMain: false });
}

window.SSTACK.ui = {
  state, api, el, clear, setStatus, showDoctor, hideDoctor, sourceChip, renderSpine,
  loadConfig, refresh, layerNames, editableLayers, defaultLayer, fmtTime,
};

export { start };
