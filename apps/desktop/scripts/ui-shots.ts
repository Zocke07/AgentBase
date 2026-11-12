/**
 * `just ui-shots`: screenshots of the real app, with nobody's screen.
 *
 * It starts a scratch sidecar and Vite, drives headless Chromium through
 * every section in both themes at three window sizes, and writes PNGs to
 * `.dev/shots/<label>/`. The terminal on the maintainer's Mac cannot see the
 * Tauri window; the same UI in a browser against the dev server can be
 * captured anywhere, including CI.
 *
 * The sidecar's data is a scratch folder under `.dev/shots/`, never `.dev/data`
 * or an installed app's data: the default space there holds a person's
 * portfolio. Everything on screen is seeded here, from made-up content.
 *
 *   node scripts/ui-shots.ts [label]             fresh scratch data
 *   node scripts/ui-shots.ts [label] --reuse     the previous data and clock
 *   node scripts/ui-shots.ts --compare a b       are two labels identical?
 *
 * `--reuse` exists to prove a change is invisible: the same data and the same
 * pinned clock give the same pixels, so any difference is the change's.
 */

import { type ChildProcessByStdio, spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdir, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { connect } from "node:net";
import { dirname, join, resolve } from "node:path";
import type { Readable, Writable } from "node:stream";
import { fileURLToPath } from "node:url";

import { chromium, type Browser, type Page } from "playwright";
import { createServer, type ViteDevServer } from "vite";

import { SECTION_ORDER } from "../src/lib/sections.ts";
import { STILL_CSS } from "../src/test/still.ts";

const DESKTOP = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const REPO = resolve(DESKTOP, "..", "..");
const BACKEND = join(REPO, "apps", "backend");
const SHOTS = join(REPO, ".dev", "shots");
const SCRATCH = join(SHOTS, ".scratch");
const SEED_FILE = join(SCRATCH, "seed.json");

/** The installed app may hold 8787, so the scratch sidecar takes another port. */
const SIDECAR_PORT = 8790;
/** The sidecar's CORS list names this origin alone, so Vite cannot move. */
const VITE_PORT = 5173;
const SIDECAR = `http://127.0.0.1:${String(SIDECAR_PORT)}`;
const PAGE = `http://127.0.0.1:${String(VITE_PORT)}/`;

const SIZES = [
  { width: 800, height: 600 },
  { width: 1100, height: 800 },
  { width: 1440, height: 900 },
] as const;
const THEMES = ["light", "dark"] as const;


/** Every capture is a frame at rest: see `src/test/still.ts`. */
const STILL = `
  document.addEventListener("DOMContentLoaded", () => {
    const style = document.createElement("style");
    style.textContent = ${JSON.stringify(STILL_CSS)};
    document.head.append(style);
  });
`;

interface Seed {
  /** The scratch run every capture opens. */
  runId: string;
  /** The browser's clock for every capture, so relative times never drift. */
  now: string;
}

const sleep = (ms: number) => new Promise((done) => setTimeout(done, ms));

function listening(port: number): Promise<boolean> {
  return new Promise((done) => {
    const socket = connect({ host: "127.0.0.1", port });
    socket.once("connect", () => {
      socket.destroy();
      done(true);
    });
    socket.once("error", () => {
      done(false);
    });
  });
}

async function api<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(`${SIDECAR}${path}`, {
    method,
    ...(body === undefined ? {} : { headers: { "content-type": "application/json" }, body: JSON.stringify(body) }),
  });
  if (!response.ok) {
    throw new Error(`${method} ${path} answered ${String(response.status)}: ${await response.text()}`);
  }
  return (await response.json()) as T;
}

// --- the scratch sidecar ----------------------------------------------------

type Sidecar = ChildProcessByStdio<Writable, null, Readable>;

async function startSidecar(): Promise<Sidecar> {
  const child = spawn("uv", ["run", "python", "-m", "agentbase"], {
    cwd: BACKEND,
    env: { ...process.env, AGENTBASE_DATA_DIR: join(SCRATCH, "data"), AGENTBASE_PORT: String(SIDECAR_PORT) },
    stdio: ["pipe", "ignore", "pipe"],
  });
  let log = "";
  child.stderr.on("data", (chunk: Buffer) => {
    log = (log + chunk.toString()).slice(-4000);
  });
  // Its first stdin line is the key handshake; an empty one gives it no keys.
  // Stdin then stays open: end of input is how a sidecar is told to stop.
  child.stdin.write("{}\n");

  for (let attempt = 0; attempt < 240; attempt += 1) {
    if (child.exitCode !== null) throw new Error(`The scratch sidecar exited early.\n${log}`);
    try {
      await api("/health");
      return child;
    } catch {
      await sleep(250);
    }
  }
  child.kill();
  throw new Error(`The scratch sidecar did not answer on ${SIDECAR} within a minute.\n${log}`);
}

async function stopSidecar(child: Sidecar): Promise<void> {
  if (child.exitCode !== null) return;
  const exited = new Promise<true>((done) => {
    child.once("exit", () => {
      done(true);
    });
  });
  child.stdin.end("shutdown\n");
  const stopped = await Promise.race([exited, sleep(10_000).then(() => false)]);
  if (!stopped) child.kill();
}

/** Made-up content, so no capture ever shows a person's data. */
async function seed(): Promise<Seed> {
  const spaces = await api<{ id: string; is_default: boolean }[]>("/spaces");
  const space = spaces.find((candidate) => candidate.is_default) ?? spaces[0];
  if (space === undefined) throw new Error("The scratch sidecar has no space.");

  // The first-run tour would cover every section.
  await api("/settings", "PATCH", { onboarding_completed: true });

  const note = (path: string, content: string) =>
    api(`/spaces/${space.id}/knowledge/note`, "PUT", { path, content });
  await note(
    "Field guide.md",
    [
      "---",
      "tags: [guide, example]",
      "---",
      "# Field guide",
      "",
      "A made-up note for screenshots. It links to [[Reading list]] and to a note",
      "that does not exist yet, [[Open questions]].",
      "",
      "## What to look for",
      "",
      "- Headings, lists and a table render in Preview.",
      "- A `code span` and a block:",
      "",
      "```text",
      "three plain lines",
      "of example text",
      "```",
      "",
      "| Item | Count |",
      "|---|---|",
      "| Apples | 3 |",
      "| Pears | 5 |",
      "",
    ].join("\n"),
  );
  await note(
    "Reading list.md",
    ["# Reading list", "", "Back to the [[Field guide]].", "", "1. First entry", "2. Second entry", ""].join("\n"),
  );
  await api(`/spaces/${space.id}/knowledge/file`, "PUT", {
    path: "data/fruit.csv",
    content: "month,apples,pears\nJan,3,5\nFeb,4,4\nMar,6,2\nApr,5,7\n",
  });

  // A scripted run with no model: every event type the canvas and log draw.
  const run = await api<{ id: string }>("/debug/fake_run?step_ms=0", "POST");
  const ended = new Set(["completed", "failed", "cancelled"]);
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const current = await api<{ status: string }>(`/runs/${run.id}`);
    if (ended.has(current.status)) return { runId: run.id, now: new Date().toISOString() };
    await sleep(250);
  }
  // A run still going would be captured mid-flight, differently each time.
  throw new Error("The scripted debug run did not finish within 30 seconds.");
}

// --- the captures -----------------------------------------------------------

/** Wait for a view to stop loading, then for two quiet frames. */
async function settle(page: Page): Promise<void> {
  await page.waitForFunction(
    () =>
      [...document.querySelectorAll(".skeleton")].every(
        (element) => element.closest("[hidden]") !== null || (element as HTMLElement).offsetParent === null,
      ),
    undefined,
    { timeout: 15_000 },
  );
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(350);
}

async function shot(page: Page, folder: string, name: string): Promise<void> {
  await settle(page);
  await page.screenshot({ path: join(folder, `${name}.png`), animations: "disabled", caret: "hide" });
}

async function capture(browser: Browser, folder: string, seeded: Seed): Promise<number> {
  let count = 0;
  for (const theme of THEMES) {
    for (const size of SIZES) {
      const context = await browser.newContext({
        viewport: size,
        deviceScaleFactor: 1,
        colorScheme: theme,
        locale: "en-US",
        timezoneId: "UTC",
      });
      const page = await context.newPage();
      await page.clock.setFixedTime(new Date(seeded.now));
      await page.addInitScript(STILL);
      await page.goto(PAGE);
      await page.locator('[data-testid="rail"]').waitFor({ timeout: 60_000 });

      const tag = `${theme}-${String(size.width)}x${String(size.height)}`;
      const take = async (name: string) => {
        await shot(page, folder, `${name}-${tag}`);
        count += 1;
      };

      // Rail order is also each section's Ctrl+digit shortcut.
      for (const [index, section] of SECTION_ORDER.entries()) {
        await page.keyboard.press(`Control+${String(index + 1)}`);
        await take(section);

        if (section === "runs") {
          // The run view: canvas, log and summary, then the agent inspector.
          await page.locator(`[data-testid$="-${seeded.runId}"]:visible`).first().click();
          await page.locator('[data-testid="run-graph"]:visible').waitFor();
          await take("run");
          const node = page.locator('[data-testid^="agent-node-"]:visible').first();
          if ((await node.count()) > 0) {
            await node.click();
            await take("run-agent");
          }
        }

        if (section === "knowledge") {
          const result = page.locator('[data-testid="knowledge-view"] button:visible', { hasText: "Field guide" }).first();
          if ((await result.count()) > 0) {
            await result.click();
            await take("knowledge-note");
          }
        }
      }
      await context.close();
    }
  }
  return count;
}

// --- comparing two labels ---------------------------------------------------

async function hashes(label: string): Promise<Map<string, string>> {
  const folder = join(SHOTS, label);
  const found = new Map<string, string>();
  for (const name of (await readdir(folder)).filter((entry) => entry.endsWith(".png")).sort()) {
    found.set(name, createHash("sha256").update(await readFile(join(folder, name))).digest("hex"));
  }
  return found;
}

interface Difference {
  pixels: number;
  /** The largest change in any channel, of 255. */
  most: number;
  box: { left: number; top: number; right: number; bottom: number } | null;
  sizes: string;
}

/** How two PNGs differ, measured in a browser, which can read them. */
async function measure(page: Page, left: Buffer, right: Buffer): Promise<Difference> {
  const urls = [left, right].map((png) => `data:image/png;base64,${png.toString("base64")}`);
  return page.evaluate(async ([first, second]) => {
    const read = async (url: string | undefined) => {
      const image = new Image();
      image.src = url ?? "";
      await image.decode();
      const canvas = new OffscreenCanvas(image.naturalWidth, image.naturalHeight);
      const context = canvas.getContext("2d");
      if (context === null) throw new Error("no canvas");
      context.drawImage(image, 0, 0);
      return context.getImageData(0, 0, canvas.width, canvas.height);
    };
    const [a, b] = [await read(first), await read(second)];
    const sizes = `${String(a.width)}x${String(a.height)} and ${String(b.width)}x${String(b.height)}`;
    if (a.width !== b.width || a.height !== b.height) return { pixels: -1, most: 255, box: null, sizes };
    let pixels = 0;
    let most = 0;
    const box = { left: a.width, top: a.height, right: 0, bottom: 0 };
    for (let index = 0; index < a.data.length; index += 4) {
      let change = 0;
      for (let channel = 0; channel < 4; channel += 1) {
        change = Math.max(change, Math.abs((a.data[index + channel] ?? 0) - (b.data[index + channel] ?? 0)));
      }
      if (change === 0) continue;
      pixels += 1;
      most = Math.max(most, change);
      const x = (index / 4) % a.width;
      const y = Math.floor(index / 4 / a.width);
      box.left = Math.min(box.left, x);
      box.right = Math.max(box.right, x);
      box.top = Math.min(box.top, y);
      box.bottom = Math.max(box.bottom, y);
    }
    return { pixels, most, box: pixels === 0 ? null : box, sizes };
  }, urls);
}

/**
 * Identical means every file is in both labels with the same bytes. For a
 * file that differs, say how much and where: a handful of pixels changed by
 * a level or two on a control's rounded corner is the browser's rasteriser,
 * and a second capture settles it; anything larger is the change's.
 */
async function compare(left: string, right: string): Promise<boolean> {
  const [a, b] = await Promise.all([hashes(left), hashes(right)]);
  const names = [...new Set([...a.keys(), ...b.keys()])].sort();
  const differing = names.filter((name) => a.get(name) !== b.get(name));
  const both = differing.filter((name) => a.has(name) && b.has(name));
  const browser = both.length === 0 ? null : await chromium.launch();
  try {
    const page = browser === null ? null : await browser.newPage();
    for (const name of differing) {
      if (page === null || !a.has(name) || !b.has(name)) {
        console.error(`  ${name}: only in ${a.has(name) ? left : right}`);
        continue;
      }
      const found = await measure(
        page,
        await readFile(join(SHOTS, left, name)),
        await readFile(join(SHOTS, right, name)),
      );
      const box = found.box;
      console.error(
        box === null
          ? `  ${name}: the sizes differ, ${found.sizes}`
          : `  ${name}: ${String(found.pixels)} pixels differ, by at most ${String(found.most)} of 255, ` +
              `within x ${String(box.left)} to ${String(box.right)}, y ${String(box.top)} to ${String(box.bottom)}`,
      );
    }
  } finally {
    await browser?.close();
  }
  console.error(
    differing.length === 0
      ? `${String(names.length)} screenshots, identical in ${left} and ${right}.`
      : `${String(differing.length)} of ${String(names.length)} screenshots differ between ${left} and ${right}.`,
  );
  return differing.length === 0 && names.length > 0;
}

// --- the run ----------------------------------------------------------------

async function main(): Promise<number> {
  const args = process.argv.slice(2);
  if (args[0] === "--compare") {
    const [, left, right] = args;
    if (left === undefined || right === undefined) throw new Error("Usage: --compare <label> <label>");
    return (await compare(left, right)) ? 0 : 1;
  }

  const unknown = args.filter((arg) => arg.startsWith("--") && arg !== "--reuse");
  const labels = args.filter((arg) => !arg.startsWith("--"));
  if (unknown.length > 0 || labels.length > 1) {
    // A mistyped --reuse must not be read as a fresh run: that deletes the
    // scratch data an earlier label was captured on.
    throw new Error(`Usage: ui-shots [label] [--reuse], or ui-shots --compare <label> <label>. Not understood: ${[...unknown, ...labels.slice(1)].join(" ")}`);
  }
  const reuse = args.includes("--reuse");
  const label = labels[0] ?? "latest";
  if (!/^[\w.-]+$/.test(label) || label.startsWith(".")) throw new Error(`"${label}" is not a usable label.`);

  for (const port of [SIDECAR_PORT, VITE_PORT]) {
    if (await listening(port)) {
      throw new Error(
        `Port ${String(port)} is in use. ui-shots needs ${String(SIDECAR_PORT)} for its scratch sidecar and ` +
          `${String(VITE_PORT)} for Vite: stop the dev server or dev app that holds it, then run this again.`,
      );
    }
  }

  let reused: Seed | null = null;
  if (reuse) {
    if (!existsSync(SEED_FILE)) throw new Error("--reuse needs an earlier run's scratch data, and there is none.");
    reused = JSON.parse(await readFile(SEED_FILE, "utf8")) as Seed;
    // Only the browser's clock is pinned. The sidecar's month-to-date figures
    // follow the real one, so data seeded in another month would not compare.
    if (reused.now.slice(0, 7) !== new Date().toISOString().slice(0, 7)) {
      throw new Error("The scratch data was seeded in an earlier month, so its figures have moved. Capture both sets again without --reuse.");
    }
  } else {
    await rm(SCRATCH, { recursive: true, force: true });
  }
  await mkdir(join(SCRATCH, "data"), { recursive: true });

  const folder = join(SHOTS, label);

  let sidecar: Sidecar | null = null;
  let vite: ViteDevServer | null = null;
  let browser: Browser | null = null;
  try {
    sidecar = await startSidecar();
    let seeded: Seed;
    if (reused !== null) {
      seeded = reused;
    } else {
      seeded = await seed();
      await writeFile(SEED_FILE, JSON.stringify(seeded, null, 2));
    }

    process.env.VITE_AGENTBASE_SIDECAR_PORT = String(SIDECAR_PORT);
    // The page's own console is not this script's to report.
    vite = await createServer({ root: DESKTOP, logLevel: "warn", server: { forwardConsole: false } });
    await vite.listen();

    browser = await chromium.launch();
    // The label's earlier screenshots go only now, with everything running.
    await rm(folder, { recursive: true, force: true });
    await mkdir(folder, { recursive: true });
    const count = await capture(browser, folder, seeded);
    console.error(`${String(count)} screenshots in ${folder}`);
    return 0;
  } finally {
    await browser?.close();
    await vite?.close();
    if (sidecar !== null) await stopSidecar(sidecar);
  }
}

main().then(
  (code) => {
    process.exit(code);
  },
  (error: unknown) => {
    console.error(error instanceof Error ? error.message : error);
    process.exit(1);
  },
);
