/**
 * Resolve and connect to the sidecar. Rust supplies origin and launch tag; a
 * browser tab uses the default origin without a tag. Keep retry logic testable.
 */

import type { HealthResponse } from "@agentbase/schemas";

/** Matches `agentbase.config.DEFAULT_BIND_PORT` and the Rust `SIDECAR_PORT`. */
const DEFAULT_BASE_URL = "http://127.0.0.1:8787";

/**
 * Retry deadline. macOS App Translocation can make first sidecar extraction
 * from Downloads take nearly two minutes.
 */
const STARTUP_ATTEMPTS = 480;
const RETRY_DELAY_MS = 250;
/** How long one `/health` request may take before the attempt counts as failed. */
const HEALTH_TIMEOUT_MS = 2_000;

/** `/health` response; `instance` is null for a manually started sidecar. */
export type Health = HealthResponse;

/** Where the sidecar should be, and which launch it should say it is. */
export interface SidecarIdentity {
  baseUrl: string;
  /** Null in a browser tab, where no shell launch can be verified. */
  instance: string | null;
}

export type SidecarStatus =
  /** `blocked`: the last answer came from another process holding the port,
      usually an earlier AgentBase still closing. */
  | { kind: "connecting"; attempt: number; blocked?: boolean }
  | { kind: "ready"; health: Health; baseUrl: string }
  | { kind: "failed"; message: string; baseUrl: string };

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** Whether we are running inside the Tauri webview rather than a browser tab. */
function insideTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/** Resolve sidecar origin from the shell or default; dynamically import Tauri for tabs. */
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

/** Something other than this launch's sidecar answered on its port. */
export class PortTakenError extends Error {}

/**
 * Fetch `/health`; require valid 200 JSON and, when supplied, the expected
 * launch tag to reject another process on the fixed port.
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
        : "another AgentBase, still running or still shutting down";
    throw new PortTakenError(
      `Something else is listening on ${baseUrl}: ${who}. Close it and relaunch; this app's own sidecar could not take the port.`,
    );
  }

  return health;
}

/**
 * Poll `/health` for the shell-launched sidecar. Cold-start webviews usually
 * load before the frozen sidecar unpacks and binds its port.
 */
export async function connectWithRetry(
  onStatus: (status: SidecarStatus) => void,
  signal?: AbortSignal,
): Promise<void> {
  const { baseUrl, instance } = await resolveSidecarIdentity();

  // Function prevents TypeScript narrowing `signal.aborted` to a constant.
  const aborted = () => signal?.aborted ?? false;

  // Retry a briefly lingering prior instance; report a persistent stranger.
  let blocked = false;
  for (let attempt = 1; attempt <= STARTUP_ATTEMPTS; attempt += 1) {
    if (aborted()) {
      return;
    }

    onStatus(blocked ? { kind: "connecting", attempt, blocked } : { kind: "connecting", attempt });

    try {
      const health = await fetchHealth(baseUrl, signal, instance);
      onStatus({ kind: "ready", health, baseUrl });
      return;
    } catch (error) {
      if (aborted()) {
        return;
      }
      blocked = error instanceof PortTakenError;
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
