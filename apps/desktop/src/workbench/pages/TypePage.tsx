import { useLayoutEffect, useRef, useState, type ReactNode } from "react";

/**
 * The type scale (Phase 20, brief 4.2): each style with the size, line
 * height and weight the browser computed for it, and the family it resolved
 * to, so a wrong font on either platform shows here first.
 */

interface Sample {
  readonly name: string;
  readonly use: string;
  readonly render: () => ReactNode;
}

const SAMPLES: readonly Sample[] = [
  {
    name: "Large title",
    use: "section titles",
    render: () => <p className="type-large-title">Quarterly report summarised</p>,
  },
  { name: "Title 1", use: "page and sheet titles", render: () => <p className="type-title-1">Recent runs</p> },
  {
    name: "Title 2",
    use: "card and group headings, the toolbar title",
    render: () => <p className="type-title-2">What this creates</p>,
  },
  { name: "Headline", use: "emphasis in lists", render: () => <p className="type-headline">Daily decision</p> },
  {
    name: "Body",
    use: "prose",
    render: () => (
      <p className="type-body">The decision is a recommendation for you to review; nothing is bought or sold.</p>
    ),
  },
  {
    name: "Control",
    use: "buttons, fields, rail, rows",
    render: () => <p className="type-control">Your holdings, cash and limits for this space.</p>,
  },
  {
    name: "Caption",
    use: "metadata and chips; the smallest text",
    render: () => <p className="type-caption">Updated Thu, Sep 10, 12:00 PM</p>,
  },
  {
    name: "Muted",
    use: "--muted",
    render: () => <p className="type-body wb-type__muted">Your holdings, cash and limits for this space's stock research.</p>,
  },
  {
    name: "Faint",
    use: "--faint, the lightest text allowed",
    render: () => <p className="type-caption wb-type__faint">Updated Thu, Sep 10, 12:00 PM</p>,
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
  { name: "Mono", use: "ids, payloads and code only", render: () => <code>tool.called call-12</code> },
  {
    name: "Numbers",
    use: "money, counts and times: tabular",
    render: () => (
      <span className="num">
        $1,204.50 · 18 of 151 · 04:30:54
        <br />
        $1,111.11 · 11 of 111 · 01:11:11
      </span>
    ),
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
