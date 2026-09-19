import type { CreateSpaceRequest, SpaceResponse } from "@agentspace/schemas";
import { useEffect, useRef, useState } from "react";

import * as api from "../lib/api";

/**
 * The space switcher at the top of the rail: the current space, a list to
 * switch, and "New space…" (a name and how the roster starts). Archived
 * spaces sit in a collapsed group, still reachable. Creating one hands the
 * result up; the shell owns which space the window is looking at.
 */

export interface SpaceSwitcherProps {
  spaces: readonly SpaceResponse[];
  currentId: string | null;
  onSelect: (id: string) => void;
  /** A space was created; the shell reloads the list and may switch to it. */
  onCreated: (space: SpaceResponse) => void;
}

type Seed = CreateSpaceRequest["seed"];

export function SpaceSwitcher({ spaces, currentId, onSelect, onCreated }: SpaceSwitcherProps) {
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [seed, setSeed] = useState<"builtins" | "empty" | "copy">("builtins");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const nameInput = useRef<HTMLInputElement>(null);

  const current = spaces.find((space) => space.id === currentId) ?? null;
  const live = spaces.filter((space) => space.archived !== true);
  const archived = spaces.filter((space) => space.archived === true);

  const close = () => {
    setOpen(false);
    setCreating(false);
    setError(null);
  };

  // Click outside, or Escape, closes it.
  useEffect(() => {
    if (!open) return undefined;
    const onPointer = (pressed: MouseEvent) => {
      if (root.current !== null && !root.current.contains(pressed.target as Node)) close();
    };
    const onKey = (pressed: KeyboardEvent) => {
      if (pressed.key === "Escape") close();
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  useEffect(() => {
    if (creating) nameInput.current?.focus();
  }, [creating]);

  const create = async () => {
    const trimmed = name.trim();
    if (trimmed === "") return;
    setBusy(true);
    setError(null);
    const body: Seed =
      seed === "copy" && currentId !== null ? { copy_from: currentId } : seed === "copy" ? "builtins" : seed;
    try {
      const created = await api.createSpace({ name: trimmed, seed: body });
      setName("");
      setSeed("builtins");
      close();
      onCreated(created);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="switcher" ref={root} data-testid="space-switcher" data-tour="space">
      <button
        type="button"
        className="switcher__current"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`Space: ${current?.name ?? "loading"}`}
        onClick={() => {
          setOpen((was) => !was);
        }}
      >
        <span className="switcher__label">Space</span>
        <span className="switcher__name">{current?.name ?? "…"}</span>
        <svg viewBox="0 0 20 20" aria-hidden="true" className="switcher__chevron">
          <path d="M5 8l5 5 5-5" fill="none" stroke="currentColor" strokeWidth="1.8" />
        </svg>
      </button>

      {open && (
        <div className="switcher__menu">
          <ul className="switcher__list" role="listbox" aria-label="Spaces">
            {live.map((space) => (
              <li key={space.id} role="option" aria-selected={space.id === currentId}>
                <button
                  type="button"
                  className={`switcher__item${space.id === currentId ? " switcher__item--current" : ""}`}
                  onClick={() => {
                    onSelect(space.id);
                    close();
                  }}
                >
                  {space.name}
                  {space.is_default && <span className="switcher__default">default</span>}
                </button>
              </li>
            ))}
          </ul>
          {archived.length > 0 && (
            <details className="switcher__archived">
              <summary>Archived ({archived.length})</summary>
              <ul className="switcher__list" role="listbox" aria-label="Archived spaces">
                {archived.map((space) => (
                  <li key={space.id} role="option" aria-selected={space.id === currentId}>
                    <button
                      type="button"
                      className={`switcher__item${space.id === currentId ? " switcher__item--current" : ""}`}
                      onClick={() => {
                        onSelect(space.id);
                        close();
                      }}
                    >
                      {space.name}
                    </button>
                  </li>
                ))}
              </ul>
            </details>
          )}

          {creating ? (
            <form
              className="switcher__new"
              onSubmit={(submitted) => {
                submitted.preventDefault();
                void create();
              }}
            >
              <label className="editor__field">
                <span>Name</span>
                <input
                  ref={nameInput}
                  type="text"
                  value={name}
                  maxLength={60}
                  onChange={(changed) => {
                    setName(changed.target.value);
                  }}
                  data-testid="new-space-name"
                />
              </label>
              <fieldset className="switcher__seed">
                <legend>Start with</legend>
                {(
                  [
                    ["builtins", "the three starter roles (researcher, writer, reviewer)"],
                    ["empty", "no agents"],
                    ["copy", `copies of ${current?.name ?? "this space"}'s agents`],
                  ] as const
                ).map(([value, label]) => (
                  <label key={value} className="editor__tool">
                    <input
                      type="radio"
                      name="seed"
                      checked={seed === value}
                      onChange={() => {
                        setSeed(value);
                      }}
                    />
                    <span>{label}</span>
                  </label>
                ))}
              </fieldset>
              {error !== null && (
                <p className="field-error" role="alert">
                  {error}
                </p>
              )}
              <div className="switcher__actions">
                <button
                  type="button"
                  className="button button--small"
                  onClick={() => {
                    setCreating(false);
                    setError(null);
                  }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="button button--small button--primary"
                  disabled={busy || name.trim() === ""}
                >
                  {busy ? "Creating…" : "Create space"}
                </button>
              </div>
            </form>
          ) : (
            <button
              type="button"
              className="switcher__item switcher__item--new"
              onClick={() => {
                setCreating(true);
              }}
            >
              New space…
            </button>
          )}
        </div>
      )}
    </div>
  );
}
