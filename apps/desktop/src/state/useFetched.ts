import { useCallback, useEffect, useState } from "react";

/**
 * Load sidecar data on mount and demand. `load` must be `useCallback`-stable;
 * `token` drives `reload()`. Derive loading from token to avoid stale flags.
 */
export function useFetched<T>(
  load: () => Promise<T>,
  initial: T,
): { data: T; error: string | null; loading: boolean; reload: () => void } {
  const [data, setData] = useState<T>(initial);
  const [error, setError] = useState<string | null>(null);
  const [token, setToken] = useState(0);
  const [settledToken, setSettledToken] = useState(-1);

  useEffect(() => {
    // Ignore responses after unmount or a newer request, such as tab switches
    // or in-flight retries.
    let live = true;
    const mine = token;

    void load()
      .then((value) => {
        if (live) {
          setData(value);
          setError(null);
        }
      })
      .catch((failure: unknown) => {
        if (live) setError(failure instanceof Error ? failure.message : String(failure));
      })
      .finally(() => {
        if (live) setSettledToken(mine);
      });

    return () => {
      live = false;
    };
  }, [load, token]);

  const reload = useCallback(() => {
    // Retry invalidates the previous response error.
    setError(null);
    setToken((current) => current + 1);
  }, []);

  return { data, error, loading: settledToken !== token, reload };
}
