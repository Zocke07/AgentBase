/**
 * Relaunch after settings write: the sidecar reads keychain keys only at spawn.
 * The shell stops it, then execs a new copy. Do not offer this outside Tauri.
 */

export { insideTauri as restartAvailable } from "./tauri";

/** Quit and reopen AgentBase. Resolves once the shell has accepted the request. */
export async function restartApp(): Promise<void> {
  const core = await import("@tauri-apps/api/core");
  await core.invoke("restart_app");
}
