import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  ConnectionError,
  cancelChatGPTLogin,
  cancelRun,
  deleteAgent,
  deleteRun,
  downloadFile,
  failureMessage,
  isMissing,
  getChatGPTAuth,
  getPortfolio,
  getPortfolioValuation,
  savePortfolio,
  listRuns,
  listTools,
  logoutChatGPT,
  onTransportFailure,
  resetBaseUrl,
  startChatGPTLogin,
  updateSettings,
} from "./api";

/**
 * The typed calls to the sidecar. `fetch` is stubbed; what is under test is
 * how a response (and the three shapes a FastAPI error body takes) becomes
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
  it("reads and saves personal data with its original revision", async () => {
    const response = { portfolio: { currency: "USD", cash: "100.125", holdings: [], watchlist: [], limits: { max_position_pct: "10", max_sector_pct: "70", max_daily_loss_pct: "3" } }, revision: "before" };
    fetchStub.mockImplementation(() => Promise.resolve(respond(200, response)));
    expect(await getPortfolio("space-main")).toEqual(response);
    await savePortfolio("space-main", response);
    expect(fetchStub.mock.calls[1]?.[0]).toBe("http://127.0.0.1:8787/spaces/space-main/portfolio");
    expect(fetchStub.mock.calls[1]?.[1]?.method).toBe("PUT");
    expect(fetchStub.mock.calls[1]?.[1]?.body).toBe(JSON.stringify(response));
  });
  it("reads the newest valuation, which is null before a run has made one", async () => {
    fetchStub.mockImplementation(() => Promise.resolve(respond(200, null)));
    expect(await getPortfolioValuation("space-main")).toBeNull();
    expect(fetchStub.mock.calls[0]?.[0]).toBe("http://127.0.0.1:8787/spaces/space-main/portfolio/valuation");
  });
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

  it("asks for every tool, or for the ones a space's agents may use", async () => {
    fetchStub.mockImplementation(() => Promise.resolve(respond(200, [])));

    await listTools();
    await listTools("space-lab");

    expect(fetchStub.mock.calls.map(([url]) => (typeof url === "string" ? url : "not a string"))).toEqual([
      "http://127.0.0.1:8787/tools",
      "http://127.0.0.1:8787/tools?space_id=space-lab",
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

  it("fetches workbook bytes without decoding them as JSON", async () => {
    const bytes = new Uint8Array([80, 75, 3, 4, 0, 255]);
    fetchStub.mockResolvedValue(new Response(bytes, {
      headers: { "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" },
    }));

    const blob = await downloadFile("space-lab", "predictions/2026-10.xlsx");

    expect(fetchStub.mock.calls[0]?.[0]).toBe("http://127.0.0.1:8787/spaces/space-lab/knowledge/download?path=predictions%2F2026-10.xlsx");
    expect(new Uint8Array(await blob.arrayBuffer())).toEqual(bytes);
  });

  it("uses the ChatGPT auth lifecycle routes without sending credential data", async () => {
    fetchStub.mockResolvedValueOnce(respond(200, { state: "disconnected" }));
    await getChatGPTAuth();

    fetchStub.mockResolvedValueOnce(
      respond(200, { login_id: "login_1", auth_url: "https://auth.openai.com/oauth/authorize" }),
    );
    await startChatGPTLogin();

    fetchStub.mockResolvedValue(new Response(null, { status: 204 }));
    await cancelChatGPTLogin();
    await logoutChatGPT();

    expect(
      fetchStub.mock.calls.map(([url, init]) => [url, init?.method ?? "GET", init?.body]),
    ).toEqual([
      ["http://127.0.0.1:8787/auth/chatgpt", "GET", undefined],
      ["http://127.0.0.1:8787/auth/chatgpt/login", "POST", undefined],
      ["http://127.0.0.1:8787/auth/chatgpt/login/cancel", "POST", undefined],
      ["http://127.0.0.1:8787/auth/chatgpt/logout", "POST", undefined],
    ]);
  });

  it("deletes a run with DELETE on its own route, and surfaces the 409 for one still running", async () => {
    fetchStub.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(deleteRun("run-1")).resolves.toBeUndefined();
    const [url, init] = fetchStub.mock.calls[0] ?? [];
    expect(url).toBe("http://127.0.0.1:8787/runs/run-1");
    expect(init?.method).toBe("DELETE");

    fetchStub.mockResolvedValue(respond(409, { detail: "run run-1 is still running; cancel it first" }));
    await expect(deleteRun("run-1")).rejects.toMatchObject({ status: 409, message: /cancel it first/ });
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
    // Said in words, with the browser's own error kept as its cause.
    const failure: unknown = await listRuns().catch((caught: unknown) => caught);
    expect(failure).toBeInstanceOf(ConnectionError);
    expect((failure as ConnectionError).message).toBe(
      "AgentBase's engine did not answer. It may be starting or restarting; try again in a moment.",
    );
    expect((failure as ConnectionError).cause).toBeInstanceOf(TypeError);
    expect(listener).toHaveBeenCalledTimes(1);

    stop();
    await listRuns().catch(() => undefined);
    expect(listener).toHaveBeenCalledTimes(1);
  });
});

describe("saying why an action failed", () => {
  it("keeps the engine's words and explains a bare status", () => {
    expect(failureMessage(new ApiError(409, "There is already a note at knowledge/untitled.md."))).toBe(
      "There is already a note at knowledge/untitled.md.",
    );
    expect(failureMessage(new ApiError(500, "HTTP 500"))).toBe(
      "AgentBase could not finish this (error 500). Try again; if it keeps happening, restart AgentBase.",
    );
    expect(failureMessage(new ApiError(413, "HTTP 413"))).toBe("AgentBase did not accept this (error 413).");
    expect(failureMessage("plain")).toBe("plain");
    expect(isMissing(new ApiError(404, "There is no file at a.json."))).toBe(true);
    expect(isMissing(new ApiError(409, "taken"))).toBe(false);
  });
});
