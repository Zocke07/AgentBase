import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  localStorage.clear();
  vi.resetModules();
});

async function loadTheme() {
  vi.resetModules();
  return import("./theme");
}

describe("the browser theme", () => {
  it("migrates an AgentSpace choice and clears both names when reset", async () => {
    localStorage.setItem("agentspace.theme", "dark");
    const { useThemeStore } = await loadTheme();

    expect(useThemeStore.getState().theme).toBe("dark");
    expect(localStorage.getItem("agentbase.theme")).toBe("dark");

    useThemeStore.getState().setTheme("system");
    expect(localStorage.getItem("agentbase.theme")).toBeNull();
    expect(localStorage.getItem("agentspace.theme")).toBeNull();
  });

  it("prefers the AgentBase choice when both names are present", async () => {
    localStorage.setItem("agentbase.theme", "light");
    localStorage.setItem("agentspace.theme", "dark");
    const { useThemeStore } = await loadTheme();

    expect(useThemeStore.getState().theme).toBe("light");
  });
});
