import { useEffect, useId, useRef, useState } from "react";

/** Mermaid mutates global configuration while rendering; serialize requests. */
let renderQueue: Promise<void> = Promise.resolve();

/**
 * Mermaid source rendered with strict security, then parsed and sanitized once
 * more before it reaches the document. Keeping the source as a normal `.mmd`
 * file means an agent can propose a diagram through the existing file gate.
 */
export function MermaidDiagram({ source, title }: { source: string; title: string }) {
  const rawId = useId();
  const target = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    let live = true;
    const render = async () => {
      if (live) {
        setBusy(true);
        setError(null);
      }
      try {
        const { default: mermaid } = await import("mermaid");
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          htmlLabels: false,
          suppressErrorRendering: true,
          theme: document.documentElement.dataset.theme === "dark" ? "dark" : "neutral",
          flowchart: { htmlLabels: false },
        });
        const id = `agentbase-mermaid-${rawId.replaceAll(":", "")}`;
        const rendered = await mermaid.render(id, source);
        if (!live || target.current === null) return;
        const parsed = new DOMParser().parseFromString(rendered.svg, "image/svg+xml");
        const root = parsed.documentElement;
        if (root.nodeName.toLowerCase() !== "svg" || parsed.querySelector("parsererror") !== null) {
          throw new Error("Mermaid returned an invalid SVG document.");
        }
        sanitizeSvg(root);
        target.current.replaceChildren(document.importNode(root, true));
      } catch (failure) {
        if (live) setError(failure instanceof Error ? failure.message : String(failure));
      } finally {
        if (live) setBusy(false);
      }
    };
    renderQueue = renderQueue.then(render, render);
    return () => { live = false; };
  }, [rawId, source]);

  return (
    <section className="mermaid-card" aria-label={title}>
      <div className="mermaid-card__head">
        <h3>{title || "Diagram"}</h3>
        <button
          type="button"
          className="button button--small"
          disabled={busy || error !== null}
          onClick={() => { exportDiagram(target.current?.querySelector("svg") ?? null, title); }}
        >
          Export SVG
        </button>
      </div>
      {busy && <p className="viz-chart__empty">Rendering diagram…</p>}
      {error !== null && <p className="field-error" role="alert">{error}</p>}
      <div className="mermaid-card__figure" ref={target} data-testid="mermaid-diagram" />
    </section>
  );
}

function sanitizeSvg(svg: Element): void {
  svg.querySelectorAll("script, foreignObject, iframe, object, embed").forEach((element) => { element.remove(); });
  for (const element of [svg, ...svg.querySelectorAll("*")]) {
    for (const attribute of [...element.attributes]) {
      const name = attribute.name.toLowerCase();
      if (name.startsWith("on")) element.removeAttribute(attribute.name);
      if ((name === "href" || name === "xlink:href") && !attribute.value.startsWith("#")) {
        element.removeAttribute(attribute.name);
      }
    }
  }
}

function exportDiagram(svg: SVGSVGElement | null, title: string): void {
  if (svg === null) return;
  const copy = svg.cloneNode(true) as SVGSVGElement;
  copy.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  const blob = new Blob([new XMLSerializer().serializeToString(copy)], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${title.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "diagram"}.svg`;
  link.click();
  URL.revokeObjectURL(url);
}
