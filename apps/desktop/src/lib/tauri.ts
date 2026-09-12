/**
 * Whether we are running inside the Tauri webview rather than a browser tab.
 *
 * The two things only the shell can do — write a key to the OS keychain,
 * open a folder — are offered only when it is there to ask. A plain browser
 * tab against the dev server has no shell, and a button that invoked a
 * command nobody handles would fail with a message about internals.
 */
export function insideTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}
