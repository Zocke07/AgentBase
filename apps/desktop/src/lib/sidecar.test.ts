import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { connectWithRetry, fetchHealth, type SidecarStatus } from "./sidecar";

// The shell's two answers, for the tests that stand inside Tauri.
vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn((command: string) =>
    Promise.resolve(command === "sidecar_instance" ? "launch-1" : "http://127.0.0.1:8787"),
  ),
}));

/**
 * The startup loop. Its comment always said the retry policy was "testable
 * on its own"; now it is tested.
 */

let fetchStub: ReturnType<typeof vi.fn<typeof fetch>>;

beforeEach(() => {
  fetchStub = vi.fn<typeof fetch>();
  vi.stubGlobal("fetch", fetchStub);
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const ok = (instance: string | null = null) =>
  new Response(JSON.stringify({ ok: true, instance }), { status: 200 });

/** Stand inside the Tauri webview for one test: the shell can be asked. */
function insideTauri() {
  (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
  return () => {
    delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
  };
}

describe("connectWithRetry", () => {
  it("reports each attempt, then ready, once the sidecar answers", async () => {
    /* The webview is reliably up before the frozen sidecar has bound its port,
       so the first request failing is the ordinary case, not an error. */
    fetchStub
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(ok());
    const seen: SidecarStatus[] = [];

    const loop = connectWithRetry((status) => seen.push(status));
    await vi.runAllTimersAsync();
    await loop;

    expect(seen.map((status) => status.kind)).toEqual(["connecting", "connecting", "connecting", "ready"]);
    expect(seen.at(-1)).toMatchObject({ kind: "ready", baseUrl: "http://127.0.0.1:8787" });
  });

  it("gives up with the last error after its attempts run out", async () => {
    fetchStub.mockRejectedValue(new TypeError("Failed to fetch"));
    const seen: SidecarStatus[] = [];

    const loop = connectWithRetry((status) => seen.push(status));
    await vi.runAllTimersAsync();
    await loop;

    const last = seen.at(-1);
    expect(last).toMatchObject({ kind: "failed", message: "Failed to fetch" });
    expect(seen.filter((status) => status.kind === "connecting")).toHaveLength(40);
  });

  it("keeps retrying while the port answers as something else, and says so when it gives up", async () => {
    /* The port is fixed. The packaged app once started while a dev sidecar
       held 8787: its own sidecar could not bind and exited, the webview got
       a healthy `/health` from the stranger, and the window showed the dev
       data directory's runs with nothing anywhere saying so. Retrying, not
       failing at once: a copy of this app closed a second ago answers for a
       moment more, and then the new sidecar binds. */
    const leave = insideTauri();
    try {
      // A `Response` body can be read once; each attempt gets its own.
      fetchStub.mockImplementation(() => Promise.resolve(ok(null)));
      const seen: SidecarStatus[] = [];

      const loop = connectWithRetry((status) => seen.push(status));
      await vi.runAllTimersAsync();
      await loop;

      const last = seen.at(-1);
      expect(last?.kind).toBe("failed");
      expect(last?.kind === "failed" ? last.message : "").toMatch(/something else is listening/i);
      expect(seen.filter((status) => status.kind === "connecting")).toHaveLength(40);
    } finally {
      leave();
    }
  });

  it("is ready the moment the sidecar answering is the one the shell launched", async () => {
    const leave = insideTauri();
    try {
      fetchStub.mockResolvedValueOnce(ok("someone-else")).mockResolvedValueOnce(ok("launch-1"));
      const seen: SidecarStatus[] = [];

      const loop = connectWithRetry((status) => seen.push(status));
      await vi.runAllTimersAsync();
      await loop;

      expect(seen.map((status) => status.kind)).toEqual(["connecting", "connecting", "ready"]);
    } finally {
      leave();
    }
  });

  it("does not care about the instance in a plain browser, where no shell launched anything", async () => {
    fetchStub.mockImplementation(() => Promise.resolve(ok("whatever")));
    const seen: SidecarStatus[] = [];

    const loop = connectWithRetry((status) => seen.push(status));
    await vi.runAllTimersAsync();
    await loop;

    expect(seen.at(-1)?.kind).toBe("ready");
  });

  it("stops quietly when aborted", async () => {
    fetchStub.mockRejectedValue(new TypeError("Failed to fetch"));
    const controller = new AbortController();
    const seen: SidecarStatus[] = [];

    const loop = connectWithRetry((status) => seen.push(status), controller.signal);
    await vi.advanceTimersByTimeAsync(600);
    controller.abort();
    await vi.runAllTimersAsync();
    await loop;

    expect(seen.some((status) => status.kind === "failed")).toBe(false);
    expect(seen.length).toBeLessThan(40);
  });
});

describe("fetchHealth", () => {
  it("rejects a response that is not a well-formed 200", async () => {
    fetchStub.mockResolvedValueOnce(new Response("nope", { status: 503 }));
    await expect(fetchHealth("http://x")).rejects.toThrow("HTTP 503");

    fetchStub.mockResolvedValueOnce(new Response(JSON.stringify({ hello: 1 }), { status: 200 }));
    await expect(fetchHealth("http://x")).rejects.toThrow("unrecognised");
  });

  it("refuses a healthy answer from a sidecar the shell did not launch", async () => {
    fetchStub.mockResolvedValueOnce(ok(null));
    await expect(fetchHealth("http://x", undefined, "launch-1")).rejects.toThrow(/not started by this app/);

    fetchStub.mockResolvedValueOnce(ok("launch-2"));
    await expect(fetchHealth("http://x", undefined, "launch-1")).rejects.toThrow(/another AgentSpace/);

    fetchStub.mockResolvedValueOnce(ok("launch-1"));
    await expect(fetchHealth("http://x", undefined, "launch-1")).resolves.toMatchObject({ instance: "launch-1" });
  });

  it("gives up on a request that hangs, rather than waiting on the browser", async () => {
    /* A sidecar that accepts the connection and never answers used to hold an
       attempt for the browser's own timeout (minutes) and "connecting
       (attempt 1)" with it. */
    fetchStub.mockImplementation(
      (_url, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("aborted", "TimeoutError"));
          });
        }),
    );

    const attempt = fetchHealth("http://x");
    await vi.advanceTimersByTimeAsync(2_500);

    await expect(attempt).rejects.toThrow();
  });
});
