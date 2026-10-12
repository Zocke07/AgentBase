/**
 * Open space folders through shell `reveal_folder`, which rejects paths outside
 * data storage. Do not offer the button outside Tauri.
 */

import { insideTauri } from "./tauri";

export { insideTauri as revealAvailable } from "./tauri";

/** Show `path` in the OS file manager. Rejects if the shell refuses. */
export async function revealFolder(path: string): Promise<void> {
  const core = await import("@tauri-apps/api/core");
  await core.invoke("reveal_folder", { path });
}

/**
 * Report whether Obsidian is in a standard install location; otherwise the
 * vault URI lacks a handler and the button stays hidden.
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

/** Open a generated Excel workbook in the default spreadsheet app. The shell
    refuses anything but a visible `.xlsx` inside AgentBase's data folder. */
export async function openWorkbook(path: string): Promise<void> {
  const core = await import("@tauri-apps/api/core");
  await core.invoke("open_workbook", { path });
}
