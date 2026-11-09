const ui = window.SSTACK.ui;
const { el, api, state } = ui;

function pageHead() {
  return el("header", { class: "page-head" },
    el("h1", { text: "Runs" }),
    el("p", { text: "The repository index, grouped by run directory. Failures and read-only warnings stay visible." }),
  );
}

function runTitle(group) {
  return group.run_dir || "Unknown run";
}

function runMeta(group) {
  const run = group.run || {};
  const meta = [];
  if (run.role) meta.push(`role ${run.role}`);
  if (Array.isArray(run.members) && run.members.length) meta.push(run.members.join(" / "));
  if (run.readonly === true) meta.push("read-only");
  if (run.started_at) meta.push(new Date(run.started_at * 1000).toISOString().slice(0, 16).replace("T", " "));
  return el("div", { class: "run-meta" }, ...meta.map((text) => el("span", { text })));
}

function warningList(warnings) {
  return el("div", { class: "readonly-alert" },
    el("strong", { text: "Read-only run changed files" }),
    el("ul", { class: "warning-list" }, ...warnings.map((w) => el("li", { class: "mono", text: w }))),
  );
}

function lineRow(line) {
  const exit = Number(line.exit);
  const exitTone = exit === 0 ? "ok" : "bad";
  const transport = [
    line.ade ? `ADE ${line.ade}` : "Headless",
    line.via && line.via !== "headless" ? line.via : null,
    [line.harness, line.model].filter(Boolean).join("/") || "local",
  ].filter(Boolean).join(" / ");
  return el("div", { class: "timeline-row" },
    el("span", { class: "when mono", text: ui.fmtTime(line.ts) }),
    el("div", {},
      el("div", { class: "role", text: line.task || line.role || "run" }),
      el("div", { class: "transport", text: line.route ? `Route: ${line.route}` : "Route not recorded" }),
      line.secs === undefined || line.secs === null
        ? null
        : el("div", { class: "transport", text: `Ran ${Math.round(line.secs)}s` }),
    ),
    el("div", { class: "transport", text: transport }),
    el("span", { class: "exit tag", dataset: { tone: exitTone }, text: `exit ${line.exit ?? "?"}` }),
    line.report ? el("span", { class: "report mono", text: line.report }) : null,
    line.readonly_warning && line.readonly_warning.length
      ? el("div", { class: "report" }, warningList(line.readonly_warning))
      : null,
  );
}

function runGroup(group) {
  const aside = el("section", { class: "run-group" },
    el("div", { class: "run-head" },
      el("h2", { text: runTitle(group) }),
      el("span", { class: "mono", text: `${group.lines.length} line${group.lines.length === 1 ? "" : "s"}` }),
    ),
    runMeta(group),
  );
  const timeline = el("div", { class: "timeline" });
  for (const line of group.lines) timeline.append(lineRow(line));
  aside.append(timeline);
  return aside;
}

export async function render(host) {
  host.append(pageHead());
  try {
    const data = await api("/api/runs");
    if (!data.runs.length) {
      host.append(el("div", { class: "empty" },
        el("h2", { text: "No runs here yet" }),
        el("p", { text: state.repo === "global"
          ? "Choose a repository to read its run index."
          : "Run an agent from this repository and its timeline will appear here." }),
      ));
      return;
    }
    const runs = el("div", { class: "runs" });
    for (const group of data.runs) runs.append(runGroup(group));
    host.append(runs);
  } catch (err) {
    host.append(el("div", { class: "empty" },
      el("h2", { text: "Runs could not load" }),
      el("p", { class: "error-text", text: err.message }),
    ));
  }
}
