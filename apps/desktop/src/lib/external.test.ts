import { beforeEach, describe, expect, it, vi } from "vitest";

import { openChatGPTAuthUrl } from "./external";
import * as tauri from "./tauri";

vi.mock("./tauri", () => ({ insideTauri: vi.fn(() => false) }));

describe("ChatGPT OAuth URL opening", () => {
  let opened: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.mocked(tauri.insideTauri).mockReturnValue(false);
    opened = vi.spyOn(window, "open").mockReturnValue(window);
  });

  it("opens an OpenAI authentication URL", async () => {
    await openChatGPTAuthUrl("https://auth.openai.com/oauth/authorize?id=1");

    expect(opened).toHaveBeenCalledWith(
      "https://auth.openai.com/oauth/authorize?id=1",
      "_blank",
      "noopener,noreferrer",
    );
  });

  it("refuses a non-OpenAI URL before opening it", async () => {
    await expect(openChatGPTAuthUrl("https://example.com/phish")).rejects.toThrow(
      "unexpected ChatGPT sign-in URL",
    );

    expect(opened).not.toHaveBeenCalled();
  });
});
