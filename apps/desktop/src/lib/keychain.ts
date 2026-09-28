/**
 * Settings writes secrets to the OS keychain (§1 constraint 4). Shell supplies
 * the service and sidecar supplies account names, so no local list exists. The
 * webview only writes or deletes; Rust reads at spawn, requiring restart.
 */

export { insideTauri as keychainAvailable } from "./tauri";

async function invoke<T = unknown>(command: string, args?: Record<string, unknown>): Promise<T> {
  const core = await import("@tauri-apps/api/core");
  return core.invoke<T>(command, args);
}

/** Store `value` as the secret called `name`. Overwrites an existing one. */
export async function setSecret(name: string, value: string): Promise<void> {
  const service = await invoke<string>("keychain_service");
  await invoke("plugin:keyring|set_password", { service, user: name, password: value });
}

/** Remove the secret called `name`. A missing entry is not an error. */
export async function clearSecret(name: string): Promise<void> {
  const [service, legacyService] = await Promise.all([
    invoke<string>("keychain_service"),
    invoke<string>("legacy_keychain_service"),
  ]);
  for (const target of new Set([service, legacyService])) {
    try {
      await invoke("plugin:keyring|delete_password", { service: target, user: name });
    } catch (failure) {
      // Missing entries are errors, but clearing them is successful. Remove the
      // predecessor so a renamed credential cannot return after restart.
      if (!/no entry|not found|NoEntry/iu.test(String(failure))) throw failure;
    }
  }
}
