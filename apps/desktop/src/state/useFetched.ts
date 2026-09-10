import { useCallback, useEffect, useState } from "react";

/**
 * Load something from the sidecar on mount, and again on demand.
 *
 * Three panels need the same thing — a list that is fetched when the view opens
 * and refetched after something changes it — and writing it out each time meant
 * three copies of the same in-flight and error handling.
 *
 * The state is set from inside the promise's callback rather than from the
 * effect body. That is what React's `set-state-in-effect` rule asks for, and the
 * reason behind the rule is real here: a synchronous setState in an effect
 * renders twice for every mount.
 *
 * `load` must be stable — wrap it in `useCallback` — or the effect refetches on
 * every render. The `token` is what makes an explicit `reload()` refetch without
 * changing `load` itself.
 */
export function useFetched<T>(
  load: () => Promise<T>,
  initial: T,
): { data: T; error: string | null; reload: () => void } {
  const [data, setData] = useState<T>(initial);
  const [error, setError] = useState<string | null>(null);
  const [token, setToken] = useState(0);

  useEffect(() => {
    // Guards against a response arriving after the component went away, which
    // is ordinary when a user switches tabs while a request is in flight.
    let live = true;

    void load()
      .then((value) => {
        if (live) {
          setData(value);
          setError(null);
        }
      })
      .catch((failure: unknown) => {
        if (live) setError(failure instanceof Error ? failure.message : String(failure));
      });

    return () => {
      live = false;
    };
  }, [load, token]);

  const reload = useCallback(() => {
    setToken((current) => current + 1);
  }, []);

  return { data, error, reload };
}
