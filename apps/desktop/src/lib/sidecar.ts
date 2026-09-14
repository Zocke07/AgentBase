/**
 * Finding and connecting to the sidecar. The base URL and the launch tag come
 * from the Rust shell; a plain browser tab gets the default origin and no tag.
 * The retry loop lives here so it is testable on its own.
 */

import type { HealthResponse } from "@agentspace/schemas";

/** Matches `agentspace.config.DEFAULT_BIND_PORT` and the Rust `SIDECAR_PORT`. */
const DEFAULT_BASE_URL = "http://127.0.0.1:8787";

/**
 * How long to keep retrying before calling it a failure. A quarantined app
 * launched from Downloads can run under macOS App Translocation, where the
 * frozen sidecar's first extraction has taken close to two minutes.
 */
const STARTUP_ATTEMPTS = 480;
const RETRY_DELAY_MS = 250;
/** How long one `/health` request may take before the attempt counts as failed. */
const HEALTH_TIMEOUT_MS = 2_000;

/** What `/health` says. `instance` is the launch tag, or null for a sidecar run by hand. */
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

/** Ask the shell where the sidecar is, falling back to the default. Dynamic import: no Tauri in a plain tab. */
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

/** Ask the shell where the sidecar is and which launch it should answer as. */
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
 * Fetch `/health`, rejecting on anything but a well-formed 200, or, when
 * `expected` is given, on a healthy answer from the wrong process: the port is
 * fixed, so a stranger holding it answers too, and the tag is what tells them apart.
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
 * Poll `/health` until it answers as the sidecar the shell launched. The
 * webview is ready before the frozen sidecar has unpacked and bound its port,
 * so the first attempts fail on almost every cold start.
 */
export async function connectWithRetry(
  onStatus: (status: SidecarStatus) => void,
  signal?: AbortSignal,
): Promise<void> {
  const { baseUrl, instance } = await resolveSidecarIdentity();

  // A function, so TypeScript does not narrow `signal.aborted` to a constant.
  const aborted = () => signal?.aborted ?? false;

  // A wrong instance is retried, not failed at once: a copy of this app closed
  // a second ago answers for a moment more. A stranger that stays is reported.
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
