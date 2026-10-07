/** Scroll a list's active row into view; jsdom has no scrollIntoView. */
export function scrollToActive(container: HTMLElement | null, selector: string): void {
  const active = container?.querySelector<HTMLElement>(selector);
  if (active !== undefined && active !== null && typeof active.scrollIntoView === "function") {
    active.scrollIntoView({ block: "nearest" });
  }
}
