import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * The app's stylesheet as tests read it: `index.css` and the files it
 * imports, in import order, which is the order the cascade sees.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

export interface StyleFile {
  /** Relative to `src`, with forward slashes: `styles/tokens.css`. */
  readonly path: string;
  readonly css: string;
}

const IMPORT = /^@import "\.\/([^"]+)";$/;

/** Every file `index.css` imports, in order. */
export function styleFiles(): StyleFile[] {
  const index = readFileSync(join(SRC, "index.css"), "utf8");
  const files: StyleFile[] = [];
  for (const line of index.split("\n")) {
    const path = IMPORT.exec(line)?.[1];
    if (path !== undefined) files.push({ path, css: readFileSync(join(SRC, path), "utf8") });
  }
  return files;
}

/** The whole stylesheet as one text, as the build joins it. */
export function stylesheet(): string {
  return styleFiles()
    .map((file) => file.css)
    .join("");
}
