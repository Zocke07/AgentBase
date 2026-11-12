import type { SpaceResponse } from "@agentbase/schemas";
import { useState } from "react";

import { Rail, type Section } from "../../components/Rail";

/**
 * The rail as the shell draws it, open and folded, with made-up spaces and a
 * waiting badge. Creating a space is the one thing here that would call the
 * sidecar, and the workbench has none.
 */

const SPACES: readonly SpaceResponse[] = [
  {
    id: "space-main",
    name: "Main",
    description: "The default space",
    created_at: "2026-09-10T12:00:00Z",
    updated_at: "2026-09-10T12:00:00Z",
    folder: "spaces/space-main",
    is_default: true,
  },
  {
    id: "space-handbook",
    name: "Handbook",
    description: "Chapter reviews",
    created_at: "2026-09-10T12:00:00Z",
    updated_at: "2026-09-10T12:00:00Z",
    folder: "spaces/space-handbook",
    is_default: false,
  },
];

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
