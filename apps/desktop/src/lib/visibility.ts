/**
 * Whether the window can be seen, written on `<html>` as `data-hidden` (brief
 * 5.2): the stylesheet pauses every animation while it is set, so a long
 * unattended run spends nothing on drawing an unseen window. Started once,
 * from `main.tsx`; returns what stops it.
 */
export function watchVisibility(doc: Document = document): () => void {
  const apply = () => {
    if (doc.hidden) doc.documentElement.dataset.hidden = "true";
    else delete doc.documentElement.dataset.hidden;
  };
  apply();
  doc.addEventListener("visibilitychange", apply);
  return () => {
    doc.removeEventListener("visibilitychange", apply);
  };
}
