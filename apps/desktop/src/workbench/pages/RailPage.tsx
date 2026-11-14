import { useState } from "react";

import { Rail, type Section } from "../../components/Rail";

import { SPACES } from "./fixtures";

/**
 * The rail as the shell draws it, open and folded, with made-up spaces and a
 * waiting badge. Creating a space is the one thing here that would call the
 * sidecar, and the workbench has none.
 */


function Framed({ label, collapsed }: { label: string; collapsed: boolean }) {
  const [section, setSection] = useState<Section>("runs");
  const [space, setSpace] = useState("space-main");

  return (
    <figure className="wb-frame">
      <figcaption className="wb-frame__label">{label}</figcaption>
      <div className={`wb-frame__rail${collapsed ? " app--rail-collapsed" : ""}`}>
        <Rail
          section={section}
          onSelect={setSection}
          spaces={SPACES}
          currentSpaceId={space}
          onSelectSpace={setSpace}
          onSpaceCreated={() => undefined}
          badges={{ runs: 2, knowledge: 1 }}
          collapsed={collapsed}
        />
      </div>
    </figure>
  );
}

export function RailPage() {
  return (
    <div className="wb-frames">
      <Framed label="Open" collapsed={false} />
      <Framed label="Folded" collapsed />
    </div>
  );
}
