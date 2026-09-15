import { insideTauri } from "./tauri";

/** Open only an OpenAI-owned HTTPS OAuth page, never an arbitrary sidecar URL. */
export async function openChatGPTAuthUrl(url: string): Promise<void> {
  const parsed = new URL(url);
  const allowedHost = parsed.hostname === "auth.openai.com" || parsed.hostname === "chatgpt.com";
  if (parsed.protocol !== "https:" || !allowedHost) {
    throw new Error("The sidecar returned an unexpected ChatGPT sign-in URL.");
  }

  if (insideTauri()) {
    const core = await import("@tauri-apps/api/core");
    await core.invoke("open_auth_url", { url });
    return;
  }

  const opened = window.open(url, "_blank", "noopener,noreferrer");
  if (opened === null) throw new Error("The browser blocked the ChatGPT sign-in window.");
}
