import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, cancelRun, deleteAgent, listRuns, onTransportFailure, resetBaseUrl, updateSettings } from "./api";

/**
 * The typed calls to the sidecar. `fetch` is stubbed; what is under test is
 * how a response — and the three shapes a FastAPI error body takes — becomes
 * a value or an `ApiError` that still knows which field was blamed.
 */

type Stub = ReturnType<typeof vi.fn<typeof fetch>>;

function respond(status: number, body: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

let fetchStub: Stub;

beforeEach(() => {
  resetBaseUrl();
  fetchStub = vi.fn<typeof fetch>();
  vi.stubGlobal("fetch", fetchStub);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("requests", () => {
  it("talks to the sidecar's origin, once resolved, for every call", async () => {
    // A `Response` body can be read once; each call gets its own.
    fetchStub.mockImplementation(() => Promise.resolve(respond(200, [])));

    await listRuns(10);
    await listRuns(20);

    // `fetch` takes a string, a URL or a Request; the API layer passes strings.
    expect(fetchStub.mock.calls.map(([url]) => (typeof url === "string" ? url : "not a string"))).toEqual([
      "http://127.0.0.1:8787/runs?limit=10",
      "http://127.0.0.1:8787/runs?limit=20",
    ]);
  });

  it("sends a JSON body with its content type, and nothing when there is no body", async () => {
    fetchStub.mockResolvedValue(respond(200, { settings: {} }));

    await updateSettings({ model: "m" });

    const [, init] = fetchStub.mock.calls[0] ?? [];
    expect(init?.method).toBe("PATCH");
    expect(init?.body).toBe('{"model":"m"}');
    expect((init?.headers as Record<string, string>)["Content-Type"]).toBe("application/json");

    fetchStub.mockResolvedValue(respond(202, { id: "r" }));
    await cancelRun("r");
    const [, cancelInit] = fetchStub.mock.calls[1] ?? [];
    expect((cancelInit?.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
  });

  it("treats a 204 as done, with nothing to parse", async () => {
    fetchStub.mockResolvedValue(new Response(null, { status: 204 }));

    await expect(deleteAgent("def-1")).resolves.toBeUndefined();
  });
});

describe("errors", () => {
  it("keeps the field from a {message, field} refusal", async () => {
    /* §5 Phase 5 made validation failures carry the field so §5 Phase 7 could
       put the message on the offending input. Losing it here would waste that. */
    fetchStub.mockResolvedValue(respond(400, { detail: { message: "unknown provider", field: "provider" } }));

    const failure = await updateSettings({ provider: "x" }).catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    expect(failure).toMatchObject({ status: 400, message: "unknown provider", field: "provider" });
  });

  it("takes the field from a pydantic 422's location", async () => {
    fetchStub.mockResolvedValue(
      respond(422, { detail: [{ loc: ["body", "monthly_cap_micros"], msg: "must be >= 0" }] }),
    );

    const failure = await updateSettings({ monthly_cap_micros: -1 }).catch((error: unknown) => error);

    expect(failure).toMatchObject({ status: 422, message: "must be >= 0", field: "monthly_cap_micros" });
  });

  it("keeps a plain-string detail as the message, with no field", async () => {
    fetchStub.mockResolvedValue(respond(409, { detail: "run r is already completed" }));

    const failure = await cancelRun("r").catch((error: unknown) => error);

    expect(failure).toMatchObject({ status: 409, message: "run r is already completed", field: null });
  });

  it("does not lose the status when the body is not JSON", async () => {
    fetchStub.mockResolvedValue(new Response("<html>bad gateway</html>", { status: 502 }));

    const failure = await listRuns().catch((error: unknown) => error);

    expect(failure).toMatchObject({ status: 502, message: "HTTP 502" });
  });
});

describe("losing the sidecar", () => {
  it("tells listeners when a request could not connect at all, and not on a 5xx", async () => {
    /* A 5xx is the sidecar answering. A rejected fetch is the sidecar gone,
       which is the shell's cue to go back to its reconnect loop. */
    const listener = vi.fn();
    const stop = onTransportFailure(listener);

    fetchStub.mockResolvedValue(respond(500, { detail: "boom" }));
    await listRuns().catch(() => undefined);
    expect(listener).not.toHaveBeenCalled();

    fetchStub.mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(listRuns()).rejects.toThrow("Failed to fetch");
    expect(listener).toHaveBeenCalledTimes(1);

    stop();
    await listRuns().catch(() => undefined);
    expect(listener).toHaveBeenCalledTimes(1);
  });
});
