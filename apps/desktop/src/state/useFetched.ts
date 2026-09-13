import { useCallback, useEffect, useState } from "react";

/**
 * Load something from the sidecar on mount, and again on demand. `load` must
 * be stable (`useCallback`) or the effect refetches every render; `token` is
 * what makes `reload()` refetch. `loading` is derived from the token rather
 * than stored, so no render sees a moved-on token with a stale flag.
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
    // Guards against a response arriving after the component went away, or
    // after a newer request was issued: both ordinary when a user switches
    // tabs or clicks retry while a request is in flight.
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
    // A retry is a fresh question: the old answer's error does not apply to it.
    setError(null);
    setToken((current) => current + 1);
  }, []);

  return { data, error, loading: settledToken !== token, reload };
}
