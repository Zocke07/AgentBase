/**
 * Talking to the FastAPI sidecar.
 *
 * The base URL comes from the Rust shell rather than being hardcoded here, so
 * there is exactly one place that decides which port the sidecar listens on.
 * When the page is opened in a plain browser (`just dev-desktop` with no Tauri
 * around it), there is no shell to ask, so it falls back to the documented
 * default. The host is never configurable: BUILD_SPEC §1 constraint 3 pins
 * everything to 127.0.0.1.
 *
 * The connection loop lives here rather than in the component so that the
 * retry policy is testable on its own, and so the component's effect does
 * nothing but start and cancel it.
 */

import type { HealthResponse } from "@agentspace/schemas";

/** Matches `agentspace.config.DEFAULT_BIND_PORT` and the Rust `SIDECAR_PORT`. */
const DEFAULT_BASE_URL = "http://127.0.0.1:8787";

/** How long to keep retrying before calling it a failure. */
const STARTUP_ATTEMPTS = 40;
const RETRY_DELAY_MS = 250;
/**
 * How long one `/health` request may take. A sidecar that accepts the
 * connection and never answers would otherwise hold an attempt for the
 * browser's own timeout (minutes) and "connecting (attempt 1)" with it.
 */
const HEALTH_TIMEOUT_MS = 2_000;

/**
 * What `/health` says. `instance` is the shell's tag for the launch that
 * started the sidecar answering, or null for one run by hand. The port is
 * fixed, so whatever holds it answers `/health`; the tag is how the webview
 * tells the shell's own sidecar from a stranger: see `fetchHealth`.
 */
export type Health = HealthResponse;

/** Where the sidecar should be, and which launch it should say it is. */
export interface SidecarIdentity {
  baseUrl: string;
  /** Null in a plain browser tab: no shell launched anything to compare with. */
  instance: string | null;
}

export type SidecarStatus =
  | { kind: "connecting"; attempt: number }
  | { kind: "ready"; health: Health; baseUrl: string }
  | { kind: "failed"; message: string; baseUrl: string };

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** Whether we are running inside the Tauri webview rather than a browser tab. */
function insideTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/**
 * Ask the Rust shell where the sidecar is, falling back to the default.
 *
 * The import is dynamic so that a plain `vite dev` page never loads the Tauri
 * API at all.
 */
export async function resolveSidecarBaseUrl(): Promise<string> {
  if (!insideTauri()) {
    return DEFAULT_BASE_URL;
  }

  try {
    const { invoke } = await import("@tauri-apps/api/core");
    return await invoke<string>("sidecar_base_url");
  } catch {
    return DEFAULT_BASE_URL;
  }
}

/**
 * Ask the shell where the sidecar is and which launch it should answer as.
 *
 * Both come from the shell, so there is one place that decides the port and
 * one that mints the tag. A plain browser tab gets the default origin and no
 * tag, and `fetchHealth` then accepts whoever answers: there is nothing to
 * compare with.
 */
export async function resolveSidecarIdentity(): Promise<SidecarIdentity> {
  if (!insideTauri()) {
    return { baseUrl: DEFAULT_BASE_URL, instance: null };
  }

  try {
    const { invoke } = await import("@tauri-apps/api/core");
    const [baseUrl, instance] = await Promise.all([
      invoke<string>("sidecar_base_url"),
      invoke<string>("sidecar_instance"),
    ]);
    return { baseUrl, instance };
  } catch {
    return { baseUrl: DEFAULT_BASE_URL, instance: null };
  }
}

/**
 * Fetch `/health`, rejecting on anything that is not a well-formed 200, or,
 * when `expected` is given, on a healthy answer from the wrong process.
 *
 * The port is fixed. When something else already holds it, the sidecar this
 * shell spawned cannot bind and exits, and `/health` still answers: from the
 * stranger. The packaged app once did exactly this against a dev sidecar left
 * in a terminal: it rendered the dev data directory's runs, its "Open folder"
 * sent the dev path, and nothing anywhere said the process on the other end
 * was not its own. The tag is what says so.
 */
export async function fetchHealth(
  baseUrl: string,
  signal?: AbortSignal,
  expected: string | null = null,
): Promise<Health> {
  const signals = [AbortSignal.timeout(HEALTH_TIMEOUT_MS), ...(signal ? [signal] : [])];
  const response = await fetch(`${baseUrl}/health`, { signal: AbortSignal.any(signals) });

  if (!response.ok) {
    throw new Error(`sidecar returned HTTP ${String(response.status)}`);
  }

  const body: unknown = await response.json();

  if (typeof body !== "object" || body === null || typeof (body as Health).ok !== "boolean") {
    throw new Error("sidecar returned an unrecognised payload");
  }

  const health = body as Health;
  if (expected !== null && health.instance !== expected) {
    const who =
      health.instance === null
        ? "a sidecar not started by this app: a dev sidecar in a terminal, most likely"
        : "another AgentSpace, still running or still shutting down";
    throw new Error(
      `Something else is listening on ${baseUrl}: ${who}. Close it and relaunch; this app's own sidecar could not take the port.`,
    );
  }

  return health;
}

/**
 * Poll `/health` until it answers as the sidecar the shell launched, reporting
 * progress through `onStatus`.
 *
 * Retrying is not defensiveness: the webview is reliably ready before the
 * frozen sidecar has finished unpacking itself and binding its port, so the
 * first request legitimately fails on almost every cold start.
 */
export async function connectWithRetry(
  onStatus: (status: SidecarStatus) => void,
  signal?: AbortSignal,
): Promise<void> {
  const { baseUrl, instance } = await resolveSidecarIdentity();

  // Read through a function: `signal.aborted` changes underneath us, and a
  // direct comparison lets TypeScript narrow it to a constant after the first
  // check.
  const aborted = () => signal?.aborted ?? false;

  // A wrong instance is retried like a refused connection rather than failed
  // at once: a copy of this app closed a second ago answers for a moment
  // more, and then the new sidecar binds. A stranger that stays is reported
  // when the attempts run out, by name.
  for (let attempt = 1; attempt <= STARTUP_ATTEMPTS; attempt += 1) {
    if (aborted()) {
      return;
    }

    onStatus({ kind: "connecting", attempt });

    try {
      const health = await fetchHealth(baseUrl, signal, instance);
      onStatus({ kind: "ready", health, baseUrl });
      return;
    } catch (error) {
      if (aborted()) {
        return;
      }
      if (attempt === STARTUP_ATTEMPTS) {
        onStatus({
          kind: "failed",
          baseUrl,
          message: error instanceof Error ? error.message : String(error),
        });
        return;
      }
      await sleep(RETRY_DELAY_MS);
    }
  }
}
