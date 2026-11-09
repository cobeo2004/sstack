// sstack hooks for pi (docs/spec/hooks.md). pi has no shell hooks, so this extension hands
// sstack-hook the payload itself. Install: symlink into ~/.pi/agent/extensions/ (sstack-install
// prints the line); the realpath below finds sstack's bin/ through the symlink.
import { spawnSync } from "node:child_process";
import { realpathSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HOOK = join(dirname(realpathSync(fileURLToPath(import.meta.url))), "..", "..", "bin", "sstack-hook");

function hook(event: string, payload: object) {
  return spawnSync("python3", [HOOK, event, "--harness", "pi"], { input: JSON.stringify(payload), encoding: "utf8", timeout: 150_000 });
}

export default function (pi: any) {
  pi.on("tool_result", async (event: any, ctx: any) => {
    if (event.toolName !== "edit" && event.toolName !== "write") return undefined;
    const r = hook("post-edit", {
      cwd: ctx.cwd, tool_name: event.toolName, input: event.input,
      session_file: ctx.sessionManager?.getSessionFile?.(),
    });
    if (r.status === 0) return undefined;
    return { content: [...(event.content ?? []), { type: "text", text: r.stderr }], isError: true };
  });
  pi.on("session_shutdown", async (event: any, ctx: any) => {
    if (event.reason === "reload") return;
    hook("session-end", { cwd: ctx.cwd, reason: event.reason, session_file: ctx.sessionManager?.getSessionFile?.() });
  });
}
