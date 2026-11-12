import { join } from "node:path";

import { build } from "vite";
import { describe, expect, it } from "vitest";

/**
 * The workbench is a development page. This builds the app as `just
 * build-desktop` does, in memory, and checks that nothing of the workbench,
 * its fixtures or the design tooling is in what would ship.
 */

interface Emitted {
  fileName: string;
  moduleIds?: readonly string[];
}

describe("the production build", () => {
  it("holds the app and nothing of the workbench", async () => {
    const result = await build({ logLevel: "silent", build: { write: false, sourcemap: false } });
    const outputs = (Array.isArray(result) ? result : [result]).flatMap((entry) => ("output" in entry ? entry.output : []));
    const files: readonly Emitted[] = outputs;

    const names = files.map((file) => file.fileName);
    expect(names).toContain("index.html");
    expect(names.filter((name) => /workbench/i.test(name))).toEqual([]);

    const modules = files.flatMap((file) => file.moduleIds ?? []).map((id) => id.split("\\").join("/"));
    // A guard on the check itself: the app's own modules are in the bundle.
    expect(modules).toContain(`${join(import.meta.dirname, "..", "..").split("\\").join("/")}/src/App.tsx`);
    // The app's own folders, not a dependency that happens to have a `scripts/`.
    const app = join(import.meta.dirname, "..", "..").split("\\").join("/");
    const development = ["src/workbench/", "src/test/", "src/design/", "scripts/"].map((folder) => `${app}/${folder}`);
    expect(modules.filter((id) => development.some((folder) => id.startsWith(folder)))).toEqual([]);
  }, 120_000);
});
