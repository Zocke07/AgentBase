import type { CreateSpaceRequest, SpaceResponse } from "@agentbase/schemas";
import { useEffect, useRef, useState } from "react";

import * as api from "../lib/api";

import { Icon } from "./icons/Icon";
import { Popover } from "./ui/Popover";

/**
 * Rail-top space switcher with current/list/new-space flow. Archived spaces
 * remain in a collapsed group. Shell owns selection after creation.
 */

export interface SpaceSwitcherProps {
  spaces: readonly SpaceResponse[];
  currentId: string | null;
  onSelect: (id: string) => void;
  /** Created space; shell reloads and may select it. */
  onCreated: (space: SpaceResponse) => void;
  /** Icon-only rail shows initial and name tooltip. */
  compact?: boolean | undefined;
}

type Seed = CreateSpaceRequest["seed"];

export function SpaceSwitcher({ spaces, currentId, onSelect, onCreated, compact = false }: SpaceSwitcherProps) {
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [seed, setSeed] = useState<"builtins" | "empty" | "copy">("builtins");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const nameInput = useRef<HTMLInputElement>(null);

  const current = spaces.find((space) => space.id === currentId) ?? null;
  // The default space's agents are its investment pipeline, which stays there:
  // a new space starts from the starter roles or nothing instead (2026-10-13).
  const copyable = current !== null && !current.is_default;
  const chosen = seed === "copy" && !copyable ? "builtins" : seed;
  const live = spaces.filter((space) => space.archived !== true);
  const archived = spaces.filter((space) => space.archived === true);

  const close = () => {
    setOpen(false);
    setCreating(false);
    setError(null);
  };

  useEffect(() => {
    if (creating) nameInput.current?.focus();
  }, [creating]);

  const create = async () => {
    const trimmed = name.trim();
    if (trimmed === "") return;
    setBusy(true);
    setError(null);
    const body: Seed = chosen === "copy" && currentId !== null ? { copy_from: currentId } : chosen === "copy" ? "builtins" : chosen;
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
    <div className={`switcher${compact ? " switcher--compact" : ""}`} data-testid="space-switcher" data-tour="space">
      <button
        ref={button}
        type="button"
        className="switcher__current"
        aria-haspopup="dialog"
        aria-expanded={open}
        // The open rail's button is named by what it shows, "Space: Main".
        // Folded, it shows an initial alone, so the name is given here.
        aria-label={compact ? `Space: ${current?.name ?? "loading"}` : undefined}
        title={compact ? `Space: ${current?.name ?? "…"}` : undefined}
        onClick={() => {
          setOpen((was) => !was);
        }}
      >
        <span className="switcher__initial" aria-hidden="true">
          {(current?.name ?? "…").slice(0, 1).toLocaleUpperCase()}
        </span>
        <span className="switcher__label">
          Space<span className="sr-only">:</span>
        </span>{" "}
        <span className="switcher__name">{current?.name ?? "…"}</span>
        <Icon name="chevrons-up-down" size={16} className="switcher__chevron" />
      </button>

      <Popover
        open={open}
        onClose={close}
        anchor={button}
        role="dialog"
        label="Switch space"
        className="switcher__menu"
        // Focus lands on the space the window is in, the menu's own "you are here".
        focus={(panel) => panel.querySelector<HTMLElement>(".switcher__item--current")}
      >
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
                )
                  .filter(([value]) => value !== "copy" || copyable)
                  .map(([value, label]) => (
                    <label key={value} className="editor__tool">
                      <input
                        type="radio"
                        name="seed"
                        checked={chosen === value}
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
      </Popover>
    </div>
  );
}
