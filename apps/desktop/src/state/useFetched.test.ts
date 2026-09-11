import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useFetched } from "./useFetched";

/**
 * The one hook every list on the dashboard loads through.
 *
 * The two things it must get right are the ones the first version got wrong:
 * saying when a request is in flight, so a list does not read "No runs yet."
 * for the half-second before the first response; and not leaving a stale
 * error on screen after the user asked for a retry.
 */

/** A `load` whose promise the test settles by hand. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("useFetched", () => {
  it("says it is loading until the first response lands", async () => {
    const first = deferred<string[]>();
    const load = vi.fn(() => first.promise);

    const { result } = renderHook(() => useFetched(load, []));

    expect(result.current.loading).toBe(true);
    expect(result.current.data).toEqual([]);

    act(() => {
      first.resolve(["a"]);
    });
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });
    expect(result.current.data).toEqual(["a"]);
  });

  it("keeps the last good data beside the error when a fetch fails", async () => {
    let attempt = 0;
    const load = vi.fn(() => {
      attempt += 1;
      return attempt === 1 ? Promise.resolve(["a"]) : Promise.reject(new Error("sidecar went away"));
    });

    const { result } = renderHook(() => useFetched(load, []));
    await waitFor(() => {
      expect(result.current.data).toEqual(["a"]);
    });

    act(() => {
      result.current.reload();
    });
    await waitFor(() => {
      expect(result.current.error).toBe("sidecar went away");
    });

    expect(result.current.data).toEqual(["a"]);
    expect(result.current.loading).toBe(false);
  });

  it("clears the error and reports loading again when asked to reload", async () => {
    /* A user who reads an error and clicks retry should see the retry happen,
       not the old error sitting there until the new response arrives. */
    const second = deferred<string[]>();
    let attempt = 0;
    const load = vi.fn(() => {
      attempt += 1;
      return attempt === 1 ? Promise.reject(new Error("first failed")) : second.promise;
    });

    const { result } = renderHook(() => useFetched(load, []));
    await waitFor(() => {
      expect(result.current.error).toBe("first failed");
    });

    act(() => {
      result.current.reload();
    });

    expect(result.current.error).toBeNull();
    expect(result.current.loading).toBe(true);

    act(() => {
      second.resolve(["b"]);
    });
    await waitFor(() => {
      expect(result.current.data).toEqual(["b"]);
    });
  });

  it("ignores a response that arrives after a newer request was made", async () => {
    const slow = deferred<string[]>();
    const fast = deferred<string[]>();
    let attempt = 0;
    const load = vi.fn(() => {
      attempt += 1;
      return attempt === 1 ? slow.promise : fast.promise;
    });

    const { result } = renderHook(() => useFetched(load, []));
    act(() => {
      result.current.reload();
    });
    act(() => {
      fast.resolve(["new"]);
    });
    await waitFor(() => {
      expect(result.current.data).toEqual(["new"]);
    });

    act(() => {
      slow.resolve(["old"]);
    });
    await Promise.resolve();

    expect(result.current.data).toEqual(["new"]);
  });
});
