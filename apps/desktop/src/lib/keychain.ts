/**
 * Writing secrets to the OS keychain, from the settings screen (§1 constraint
 * 4). The service name comes from the shell and the account names from the
 * sidecar, so this module holds no list of its own. The webview may set and
 * delete only; reading back is done in Rust at spawn, so every caller says
 * "restart to apply".
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
  const service = await invoke<string>("keychain_service");
  try {
    await invoke("plugin:keyring|delete_password", { service, user: name });
  } catch (failure) {
    // The keyring crate reports a missing entry as an error; clearing what is
    // already clear is what the user asked for.
    if (!/no entry|not found|NoEntry/iu.test(String(failure))) throw failure;
  }
}
