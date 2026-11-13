// After Claude Code edits a file: look for an em dash, and lint the file if
// it is TypeScript under apps/desktop. Mistakes then show at the edit, not at
// `just ci` (the hygiene test fails on one em dash anywhere).
//
// A PostToolUse hook: the edit's details arrive as JSON on stdin. Exit 2
// hands what is printed on stderr back to Claude; anything this script
// cannot check is left alone and it exits 0. Plain Node, so it runs the same
// on Windows and macOS, with no shell script (BUILD_SPEC §5 Phase 0).

import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const DESKTOP = join(ROOT, "apps", "desktop");
const EM_DASH = String.fromCodePoint(0x2014);
/** Text the hygiene test reads; a binary file is never searched. */
const TEXT = /\.(?:tsx?|mjs|cjs|jsx?|json|css|html|md|py|toml|ya?ml|rs|sql|txt)$|(?:^|[\\/])justfile$/i;

function editedFile() {
  try {
    const input = JSON.parse(readFileSync(0, "utf8"));
    const path = input?.tool_input?.file_path ?? input?.tool_response?.filePath;
    return typeof path === "string" && path !== "" ? resolve(path) : null;
  } catch {
    return null;
  }
}

const file = editedFile();
if (file === null || !existsSync(file)) process.exit(0);

const inside = relative(ROOT, file);
// Only this repository's own files, and nothing generated or vendored.
if (inside.startsWith("..") || /(?:^|[\\/])(?:node_modules|\.dev|dist|target|\.git)(?:[\\/]|$)/.test(inside)) process.exit(0);

const problems = [];

if (TEXT.test(file)) {
  const lines = readFileSync(file, "utf8").split("\n");
  const found = lines.flatMap((line, index) => (line.includes(EM_DASH) ? [index + 1] : []));
  if (found.length > 0) {
    problems.push(`${inside}: em dash on line ${found.slice(0, 8).join(", ")}. The repository uses none; reword with a colon, a comma or two sentences.`);
  }
}

const eslint = join(DESKTOP, "node_modules", "eslint", "bin", "eslint.js");
if (/\.tsx?$/.test(file) && file.startsWith(DESKTOP + sep) && existsSync(eslint)) {
  // The heap the project's own lint script allows: type-aware lint needs it.
  const run = spawnSync(process.execPath, ["--max-old-space-size=4096", eslint, "--max-warnings", "0", file], {
    cwd: DESKTOP,
    encoding: "utf8",
    timeout: 60_000,
  });
  if (run.status === 1) problems.push((run.stdout || run.stderr).trim());
}

if (problems.length > 0) {
  process.stderr.write(`${problems.join("\n\n")}\n`);
  process.exit(2);
}
