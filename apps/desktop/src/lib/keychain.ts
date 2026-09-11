/**
 * Writing secrets to the OS keychain, from the settings screen.
 *
 * §1 constraint 4: API keys live in the OS keychain and reach the sidecar over
 * stdin at spawn — never a file, never SQLite, never a request body. So the
 * settings screen cannot hand a key to the sidecar; it hands it to the OS,
 * through the Tauri keyring plugin, under the exact service and account names
 * the Rust shell reads at the next launch. The service name comes from the
 * shell (`keychain_service`) rather than being copied here, and the account
 * names come from the sidecar (`known_secrets`), so this module holds no list
 * of its own.
 *
 * The webview is granted set and delete only. Reading a secret back is done in
 * Rust at spawn time and deliberately not offered to JavaScript.
 *
 * A key written here is not seen by the running sidecar: keys are read once,
 * at startup. Every caller says "restart to apply" for that reason.
 */

/** Whether we are running inside the Tauri webview rather than a browser tab. */
export function keychainAvailable(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

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
