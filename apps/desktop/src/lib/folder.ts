/**
 * Opening a space's folder in the file manager, from the space settings page.
 *
 * The webview never opens paths itself. It asks the Rust shell to, through
 * one command (`reveal_folder`) which checks the path is inside the data
 * directory the shell itself resolved before handing it to the opener
 * plugin. That check is what makes the button safe: a page that could open
 * any path it named would be a page that could be tricked into opening one,
 * and the plugin's own JavaScript scopes cannot express "under the data
 * directory" when a dev run keeps its data in the repository.
 *
 * Outside the Tauri webview (a plain browser tab against the dev server)
 * there is no shell to ask, and the button is not offered.
 */

export { insideTauri as revealAvailable } from "./tauri";

/** Show `path` in the OS file manager. Rejects if the shell refuses. */
export async function revealFolder(path: string): Promise<void> {
  const core = await import("@tauri-apps/api/core");
  await core.invoke("reveal_folder", { path });
}
