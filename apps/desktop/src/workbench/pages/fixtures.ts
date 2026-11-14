import type { SpaceResponse } from "@agentbase/schemas";

/** Made-up spaces, for the pages that draw the rail. */
export const SPACES: readonly SpaceResponse[] = [
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
