/**
 * Why an action failed, said for the person who asked for it. Kept apart from
 * `api.ts` and free of its classes, so the many tests that replace the API
 * module still get these: an API error is recognized by its numeric status.
 */

function statusOf(failure: Error): number | null {
  const status = (failure as { status?: unknown }).status;
  return typeof status === "number" ? status : null;
}

/** The engine's own explanation where it gave one; otherwise what the status means. */
export function failureMessage(failure: unknown): string {
  if (!(failure instanceof Error)) return String(failure);
  const status = statusOf(failure);
  if (status !== null && /^HTTP \d+$/u.test(failure.message)) {
    return status >= 500
      ? `AgentBase could not finish this (error ${String(status)}). Try again; if it keeps happening, restart AgentBase.`
      : `AgentBase did not accept this (error ${String(status)}).`;
  }
  return failure.message;
}

/** The thing asked for is no longer there, as when another window or a run removed it. */
export function isMissing(failure: unknown): boolean {
  return failure instanceof Error && statusOf(failure) === 404;
}
