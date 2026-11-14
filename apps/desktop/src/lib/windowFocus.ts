/**
 * Whether this is the window in front, written on `<html>` as
 * `data-window-active` (Phase 20, brief 6.1). A Mac app greys its sidebar's
 * selection and its toolbar's icons while another window is key; the
 * stylesheet does that from this attribute. Started once, from `main.tsx`;
 * returns what stops it.
 */
export function watchWindowFocus(win: Window = window): () => void {
  const root = win.document.documentElement;
  const apply = (active: boolean) => {
    root.dataset.windowActive = active ? "true" : "false";
  };
  const onFocus = () => {
    apply(true);
  };
  const onBlur = () => {
    apply(false);
  };
  apply(win.document.hasFocus());
  win.addEventListener("focus", onFocus);
  win.addEventListener("blur", onBlur);
  return () => {
    win.removeEventListener("focus", onFocus);
    win.removeEventListener("blur", onBlur);
    delete root.dataset.windowActive;
  };
}
