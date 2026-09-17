/**
 * Opening a space's folder in the file manager. The webview never opens paths
 * itself: it asks the shell's `reveal_folder`, which refuses any path outside
 * the data directory. Outside Tauri the button is not offered.
 */

export { insideTauri as revealAvailable } from "./tauri";

/** Show `path` in the OS file manager. Rejects if the shell refuses. */
export async function revealFolder(path: string): Promise<void> {
  const core = await import("@tauri-apps/api/core");
  await core.invoke("reveal_folder", { path });
}

/** Ask the shell to open the validated space folder as an Obsidian vault. */
export async function openInObsidian(path: string): Promise<void> {
  const core = await import("@tauri-apps/api/core");
  await core.invoke("open_obsidian_vault", { path });
}
