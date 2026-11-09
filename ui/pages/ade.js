const ui = window.SSTACK.ui;
const { el, api, state, sourceChip } = ui;

function pageHead() {
  return el("header", { class: "page-head" },
    el("h1", { text: "ADE" }),
    el("p", { text: "The active adapter decides how delegated work leaves this session, and what browser or device tools it may use." }),
  );
}

function capabilityTable(active) {
  const rows = [
    ["Delegation", active.delegate],
    ["Read-only", active.readonly],
    ["Browser", active.browser],
    ["Device", active.device],
    ["Capture", active.capture],
  ];
  const table = el("table", { class: "cap-table" });
  for (const [label, value] of rows) {
    table.append(el("tr", {},
      el("th", { text: label }),
      el("td", { class: value ? "mono" : "hint", text: value || "not declared" }),
    ));
  }
  return table;
}

function adapterList(config) {
  const adapters = (config.things || []).filter((t) => t.kind === "ades");
  if (!adapters.length) return el("p", { class: "hint", text: "No adapter files are configured." });
  const list = el("div", { class: "adapter-list" });
  for (const adapter of adapters) {
    list.append(el("div", { class: "adapter-row" },
      el("span", { class: "mono", text: adapter.name }),
      sourceChip(adapter.source),
      el("span", { class: "hint", text: adapter.value?.auto === false ? "manual only" : "detected automatically" }),
    ));
  }
  return list;
}

export async function render(host) {
  host.append(pageHead());
  try {
    if (!state.config) await ui.loadConfig();
    const active = await api("/api/ade");
    if (!active.name) {
      host.append(el("div", { class: "empty" },
        el("h2", { text: "No ADE detected" }),
        el("p", { text: `${active.why}. Delegation runs headless until an adapter matches.` }),
      ));
    } else {
      host.append(el("section", { class: "ade-head" },
        el("h2", { class: "ade-name", text: active.name }),
        el("p", { text: `Active because ${active.why}. Adapter file from the ${active.layer} layer.` }),
      ));
      host.append(capabilityTable(active));
      host.append(el("div", { class: "section-head" },
        el("h3", { text: "Adapter note" }),
        el("p", { class: "mono", text: active.note || "no note file" }),
      ));
      if (active.note_text) {
        host.append(el("div", { class: "note-block" }, el("pre", { text: active.note_text })));
      } else {
        host.append(el("p", { class: "hint", text: "No adapter note file is available." }));
      }
    }
    host.append(el("div", { class: "section-head" }, el("h3", { text: "Configured adapters" })));
    host.append(adapterList(state.config));
  } catch (err) {
    host.append(el("div", { class: "empty" },
      el("h2", { text: "ADE state could not load" }),
      el("p", { class: "error-text", text: err.message }),
    ));
  }
}
