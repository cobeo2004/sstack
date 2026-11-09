const ui = window.SSTACK.ui;
const { el, api, state, setStatus } = ui;

function pageHead() {
  return el("header", { class: "page-head" },
    el("h1", { text: "Graph" }),
    el("p", { text: "The code-review graph for this repository. Building it writes only inside the selected repo." }),
  );
}

function actionButton(label, host, output) {
  const button = el("button", { type: "button", class: "primary", text: label });
  button.addEventListener("click", async () => {
    button.disabled = true;
    output.hidden = true;
    try {
      const result = await api("/api/graph/rebuild", { method: "POST", body: { repo: state.repo } });
      output.textContent = result.output || result.error || (result.ok ? "Graph rebuilt." : "Graph build failed.");
      output.hidden = false;
      setStatus(result.ok ? "Graph rebuilt" : "Graph build failed", result.ok ? "ok" : "bad");
    } catch (err) {
      output.textContent = err.message;
      output.hidden = false;
      setStatus("Graph build failed", "bad");
    } finally {
      button.disabled = false;
    }
  });
  return button;
}

export async function render(host) {
  host.append(pageHead());
  if (state.repo === "global") {
    host.append(el("div", { class: "empty" },
      el("h2", { text: "Choose a repository" }),
      el("p", { text: "The graph belongs to a checkout, so global has none." }),
    ));
    return;
  }
  try {
    const data = await api("/api/graph");
    if (!data.available) {
      host.append(el("div", { class: "empty" },
        el("h2", { text: "code-review-graph is not installed" }),
        el("p", { text: "Install the CLI, then return here to build the repository graph." }),
      ));
      return;
    }
    if (!data.built) {
      host.append(el("div", { class: "empty" },
        el("h2", { text: "No graph yet" }),
        el("p", { text: "Build a graph to inspect calls, files, and the impact of a change." }),
      ));
    }
    const output = el("pre", { hidden: true });
    host.append(el("div", { class: "graph-status" },
      data.built ? el("p", { class: "mono", text: data.status }) : null,
      el("div", { class: "actions" }, actionButton(data.built ? "Rebuild graph" : "Build graph", host, output)),
      output,
    ));
  } catch (err) {
    host.append(el("div", { class: "empty" },
      el("h2", { text: "Graph state could not load" }),
      el("p", { class: "error-text", text: err.message }),
    ));
  }
}
