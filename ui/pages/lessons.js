const ui = window.SSTACK.ui;
const { el, api, state, setStatus } = ui;

function pageHead() {
  return el("header", { class: "page-head" },
    el("h1", { text: "Lessons" }),
    el("p", { text: "Small corrections captured after work sessions. Accept one to keep it, or forget it to remove it." }),
  );
}

function lessonRow(lesson, host) {
  const accept = el("button", {
    type: "button",
    class: "panel-button",
    text: "Accept",
    disabled: lesson.status !== "pending",
  });
  const forget = el("button", { type: "button", class: "danger", text: "Forget" });

  const act = async (action) => {
    if (action === "forget" && !window.confirm(`Forget lesson ${lesson.id}? It will be deleted from the lessons file.`)) {
      return;
    }
    accept.disabled = true;
    forget.disabled = true;
    try {
      await api(`/api/lessons/${action}`, {
        method: "POST",
        body: { repo: state.repo, scope: lesson.scope, id: lesson.id },
      });
      setStatus(`${action === "accept" ? "Accepted" : "Forgot"} lesson ${lesson.id}`, "ok");
      host.replaceChildren();
      await render(host);
    } catch (err) {
      setStatus("Lesson action failed", "bad");
      accept.disabled = lesson.status !== "pending";
      forget.disabled = false;
    }
  };
  accept.addEventListener("click", () => act("accept"));
  forget.addEventListener("click", () => act("forget"));

  return el("article", { class: "lesson" },
    el("div", {},
      el("p", { class: "lesson-text", text: lesson.text }),
      el("div", { class: "lesson-meta" },
        el("span", { class: "mono", text: `id ${lesson.id}` }),
        el("span", { class: "tag", text: lesson.scope }),
        el("span", { class: "tag", dataset: { tone: lesson.status === "accepted" ? "ok" : "warn" }, text: lesson.status }),
        el("span", { text: `seen ${lesson.seen}` }),
      ),
    ),
    el("div", { class: "lesson-actions" }, accept, forget),
  );
}

export async function render(host) {
  host.append(pageHead());
  try {
    const data = await api("/api/lessons");
    if (!data.lessons.length) {
      host.append(el("div", { class: "empty" },
        el("h2", { text: "No lessons recorded" }),
        el("p", { text: "Lessons arrive after work sessions. Pending ones ask for a decision here." }),
      ));
      return;
    }
    const list = el("div", { class: "lesson-list" });
    for (const lesson of data.lessons) list.append(lessonRow(lesson, host));
    host.append(list);
  } catch (err) {
    host.append(el("div", { class: "empty" },
      el("h2", { text: "Lessons could not load" }),
      el("p", { class: "error-text", text: err.message }),
    ));
  }
}
