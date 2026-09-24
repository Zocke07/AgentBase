import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { useStoredFlag } from "./useStoredFlag";

afterEach(() => {
  localStorage.clear();
});

describe("useStoredFlag", () => {
  it("migrates an AgentSpace flag and writes later choices under AgentBase", () => {
    localStorage.setItem("agentspace.flag.rail.collapsed", "1");
    const { result } = renderHook(() => useStoredFlag("rail.collapsed"));

    expect(result.current[0]).toBe(true);
    expect(localStorage.getItem("agentbase.flag.rail.collapsed")).toBe("1");

    act(() => {
      result.current[1](false);
    });
    expect(localStorage.getItem("agentbase.flag.rail.collapsed")).toBe("0");
  });

  it("uses an AgentBase flag when both names are present", () => {
    localStorage.setItem("agentbase.flag.rail.collapsed", "0");
    localStorage.setItem("agentspace.flag.rail.collapsed", "1");

    expect(renderHook(() => useStoredFlag("rail.collapsed")).result.current[0]).toBe(false);
  });
});
