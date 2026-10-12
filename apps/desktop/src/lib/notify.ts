import { insideTauri } from "./tauri";

/**
 * Raise a desktop notification for a market alert (Phase 18). In the app the
 * shell shows it through its own command, so the window holds no notification
 * permission; a browser tab uses the Notification API once permitted.
 */
export async function notifyDesktop(title: string, body: string): Promise<void> {
  if (insideTauri()) {
    const core = await import("@tauri-apps/api/core");
    await core.invoke("notify_alert", { title, body });
    return;
  }
  if (typeof Notification === "undefined") return;
  if (Notification.permission === "default") await Notification.requestPermission();
  if (Notification.permission === "granted") new Notification(title, { body });
}
