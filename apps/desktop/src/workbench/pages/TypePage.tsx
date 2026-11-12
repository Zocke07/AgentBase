import { useLayoutEffect, useRef, useState, type ReactNode } from "react";

/**
 * The type the stylesheet gives each kind of text today, with the size,
 * line height and weight the browser actually computed for it. Stage 20.2
 * replaces these with the type scale; this page is its before.
 */

interface Sample {
  readonly name: string;
  readonly use: string;
  readonly render: () => ReactNode;
}

const SAMPLES: readonly Sample[] = [
  { name: "Heading 1", use: "h1", render: () => <h1>Quarterly report summarised</h1> },
  { name: "Heading 2", use: "h2", render: () => <h2>Recent runs</h2> },
  { name: "Heading 3", use: "h3", render: () => <h3>What this creates</h3> },
  {
    name: "Body",
    use: "prose",
    render: () => <p className="wb-type__prose">The decision is a recommendation for you to review; nothing is bought or sold.</p>,
  },
  {
    name: "Muted",
    use: "--muted",
    render: () => (
      <p className="wb-type__prose wb-type__prose--muted">Your holdings, cash and limits for this space's stock research.</p>
    ),
  },
  {
    name: "Faint",
    use: "--faint, the lightest text allowed",
    render: () => <p className="wb-type__prose wb-type__prose--faint">Updated Thu, Sep 10, 12:00 PM</p>,
  },
  {
    name: "Link",
    use: ".link",
    render: () => (
      <button type="button" className="link">
        All reports as one page
      </button>
    ),
  },
  { name: "Mono", use: "ids, payloads and code", render: () => <code>tool.called call-12</code> },
  {
    name: "Numbers",
    use: "money, counts and times",
    render: () => <span className="wb-type__numbers">$1,204.50 · 18 of 151 · 04:30:54</span>,
  },
];

function Measured({ sample }: { sample: Sample }) {
  const holder = useRef<HTMLDivElement>(null);
  const [facts, setFacts] = useState("");

  useLayoutEffect(() => {
    const element = holder.current?.firstElementChild;
    if (element === null || element === undefined) return;
    const style = getComputedStyle(element);
    // jsdom computes no font metrics; say so rather than print blanks.
    setFacts(style.fontSize === "" ? "not measured here" : `${style.fontSize} / ${style.lineHeight} · weight ${style.fontWeight}`);
  }, []);

  return (
    <tr>
      <th scope="row">
        {sample.name}
        <span className="wb-table__note">{sample.use}</span>
      </th>
      <td>
        <div ref={holder}>{sample.render()}</div>
      </td>
      <td className="wb-table__figure">{facts}</td>
    </tr>
  );
}

export function TypePage() {
  return (
    <table className="wb-table">
      <thead>
        <tr>
          <th scope="col">Style</th>
          <th scope="col">Sample</th>
          <th scope="col">Computed</th>
        </tr>
      </thead>
      <tbody>
        {SAMPLES.map((sample) => (
          <Measured key={sample.name} sample={sample} />
        ))}
      </tbody>
    </table>
  );
}
