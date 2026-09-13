/**
 * Whether we are running inside the Tauri webview rather than a browser tab.
 * What only the shell can do (keychain writes, opening a folder) is offered
 * only when it is there to ask.
 */
export function insideTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}
