/**
 * Opening a space's folder in the file manager. The webview never opens paths
 * itself: it asks the shell's `reveal_folder`, which refuses any path outside
 * the data directory. Outside Tauri the button is not offered.
 */

import { insideTauri } from "./tauri";

export { insideTauri as revealAvailable } from "./tauri";

/** Show `path` in the OS file manager. Rejects if the shell refuses. */
export async function revealFolder(path: string): Promise<void> {
  const core = await import("@tauri-apps/api/core");
  await core.invoke("reveal_folder", { path });
}

/**
 * Whether the shell found Obsidian where its installer puts it. The vault
 * button is offered only then: without Obsidian the link has no handler.
 */
export async function obsidianAvailable(): Promise<boolean> {
  if (!insideTauri()) return false;
  const core = await import("@tauri-apps/api/core");
  return core.invoke<boolean>("obsidian_available");
}

/** Ask the shell to open the validated space folder as an Obsidian vault. */
export async function openInObsidian(path: string): Promise<void> {
  const core = await import("@tauri-apps/api/core");
  await core.invoke("open_obsidian_vault", { path });
}
