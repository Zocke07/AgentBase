/**
 * Detect the Tauri webview. Offer shell-only operations, such as keychain
 * writes and folder opening, only there.
 */
export function insideTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}
