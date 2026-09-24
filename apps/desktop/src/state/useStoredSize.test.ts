import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useStoredSize } from "./useStoredSize";

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("useStoredSize", () => {
  it("starts from what this browser stored, and writes what is chosen back", () => {
    localStorage.setItem("agentbase.size.runs.list", "280");
    const { result } = renderHook(() => useStoredSize("runs.list"));
    expect(result.current[0]).toBe(280);

    act(() => {
      result.current[1](320);
    });
    expect(result.current[0]).toBe(320);
    expect(localStorage.getItem("agentbase.size.runs.list")).toBe("320");

    act(() => {
      result.current[1](null);
    });
    expect(localStorage.getItem("agentbase.size.runs.list")).toBeNull();
  });

  it("migrates a saved AgentSpace size when AgentBase has not stored one yet", () => {
    localStorage.setItem("agentspace.size.runs.list", "280");

    const { result } = renderHook(() => useStoredSize("runs.list"));

    expect(result.current[0]).toBe(280);
    expect(localStorage.getItem("agentbase.size.runs.list")).toBe("280");
  });

  it("treats a stored value that is not a size as unset", () => {
    localStorage.setItem("agentbase.size.runs.canvas", "wide");
    localStorage.setItem("agentspace.size.runs.canvas", "320");
    expect(renderHook(() => useStoredSize("runs.canvas")).result.current[0]).toBeNull();
  });

  it("works when storage refuses", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const { result } = renderHook(() => useStoredSize("runs.detail"));
    expect(result.current[0]).toBeNull();
    act(() => {
      result.current[1](400);
    });
    expect(result.current[0]).toBe(400);
  });
});
