import { useCallback, useEffect, useState } from "react";

/**
 * Load something from the sidecar on mount, and again on demand.
 *
 * Three panels need the same thing (a list that is fetched when the view opens
 * and refetched after something changes it), and writing it out each time meant
 * three copies of the same in-flight and error handling.
 *
 * The state is set from inside the promise's callback rather than from the
 * effect body. That is what React's `set-state-in-effect` rule asks for, and the
 * reason behind the rule is real here: a synchronous setState in an effect
 * renders twice for every mount.
 *
 * `load` must be stable (wrap it in `useCallback`) or the effect refetches on
 * every render. The `token` is what makes an explicit `reload()` refetch without
 * changing `load` itself.
 *
 * `loading` is derived rather than stored: a request is in flight from the
 * moment a `token` is issued until the response for *that* token lands. Storing
 * it separately would mean a render where the token had moved on and the flag
 * had not, which is exactly the render where a list reads "No runs yet."
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
