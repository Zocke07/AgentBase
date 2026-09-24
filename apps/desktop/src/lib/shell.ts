/**
 * Relaunching the app. Keys are read from the keychain once, at spawn, so a
 * key written from the settings screen reaches the sidecar only after a
 * restart. The shell owns process lifetime: it stops the sidecar, then execs
 * a fresh copy of itself. Outside Tauri there is nothing to relaunch, so the
 * button is not offered.
 */

export { insideTauri as restartAvailable } from "./tauri";

/** Quit and reopen AgentBase. Resolves once the shell has accepted the request. */
export async function restartApp(): Promise<void> {
  const core = await import("@tauri-apps/api/core");
  await core.invoke("restart_app");
}
