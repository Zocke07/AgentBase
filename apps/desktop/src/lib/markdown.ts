/**
 * Obsidian-flavoured Markdown, parsed into a small tree the renderer walks.
 *
 * The vault is Obsidian-compatible (BUILD_SPEC Phase 12), so what a person
 * wrote in Obsidian should read the same here: `[[wikilinks]]` with aliases
 * and headings, `![[embeds]]`, `#tags`, `==highlights==`, `> [!callout]`
 * blocks, task lists, tables, and a single newline as a line break. Nothing
 * here produces HTML: the tree is data, and the renderer builds elements from
 * it, so a note cannot inject markup.
 *
 * Every block carries the source line it starts on, counted over the whole
 * file including the frontmatter, so a checkbox ticked in the preview can be
 * written back to the right line of the source.
 */

export type Alignment = "left" | "center" | "right" | null;

export type Inline =
  | { readonly kind: "text"; readonly text: string }
  | { readonly kind: "strong"; readonly children: readonly Inline[] }
  | { readonly kind: "em"; readonly children: readonly Inline[] }
  | { readonly kind: "strike"; readonly children: readonly Inline[] }
  | { readonly kind: "mark"; readonly children: readonly Inline[] }
  | { readonly kind: "code"; readonly text: string }
  | {
      readonly kind: "wikilink";
      readonly target: string;
      readonly heading: string | null;
      readonly label: string;
      readonly embed: boolean;
    }
  | { readonly kind: "link"; readonly href: string; readonly children: readonly Inline[] }
  | { readonly kind: "tag"; readonly tag: string }
  | { readonly kind: "break" };

export interface ListItem {
  readonly line: number;
  /** null for a plain item; otherwise the character inside the brackets (" " is unchecked). */
  readonly task: string | null;
  readonly children: readonly Block[];
}

export type Block =
  | { readonly kind: "heading"; readonly line: number; readonly level: number; readonly children: readonly Inline[] }
  | { readonly kind: "paragraph"; readonly line: number; readonly children: readonly Inline[] }
  | { readonly kind: "code"; readonly line: number; readonly language: string; readonly text: string }
  | { readonly kind: "quote"; readonly line: number; readonly children: readonly Block[] }
  | {
      readonly kind: "callout";
      readonly line: number;
      readonly type: string;
      readonly fold: "open" | "closed" | null;
      readonly title: readonly Inline[];
      readonly children: readonly Block[];
    }
  | {
      readonly kind: "list";
      readonly line: number;
      readonly ordered: boolean;
      readonly start: number;
      readonly items: readonly ListItem[];
    }
  | {
      readonly kind: "table";
      readonly line: number;
      readonly align: readonly Alignment[];
      readonly header: readonly (readonly Inline[])[];
      readonly rows: readonly (readonly (readonly Inline[])[])[];
    }
  | { readonly kind: "rule"; readonly line: number };

export interface Property {
  readonly name: string;
  readonly value: string | readonly string[];
}

export interface Document {
  readonly properties: readonly Property[];
  readonly blocks: readonly Block[];
  /** The line the body starts on: zero without frontmatter. */
  readonly bodyLine: number;
}

export function parseMarkdown(source: string): Document {
  const { properties, body, bodyLine } = parseFrontmatter(source);
  return { properties, blocks: parseBlocks(body.split("\n"), bodyLine), bodyLine };
}

// --- frontmatter -----------------------------------------------------------

/**
 * The YAML subset Obsidian's properties panel writes: `key: value`,
 * `key: [a, b]`, and `key:` followed by `- item` lines. Anything else is kept
 * as the text it was.
 */
export function parseFrontmatter(source: string): {
  properties: Property[];
  body: string;
  bodyLine: number;
} {
  const text = source.replaceAll("\r\n", "\n");
  if (!text.startsWith("---\n") && text !== "---") return { properties: [], body: text, bodyLine: 0 };
  const lines = text.split("\n");
  let end = -1;
  for (let index = 1; index < lines.length; index += 1) {
    const line = lines[index] ?? "";
    if (line.trim() === "---" || line.trim() === "...") {
      end = index;
      break;
    }
  }
  if (end < 0) return { properties: [], body: text, bodyLine: 0 };

  const properties: Property[] = [];
  let index = 1;
  while (index < end) {
    const line = lines[index] ?? "";
    index += 1;
    const entry = /^([A-Za-z0-9_.\- ]+?)\s*:(?:\s+(.*))?$/.exec(line);
    if (entry === null || line.startsWith(" ") || line.startsWith("#")) continue;
    const name = entry[1]?.trim() ?? "";
    const raw = entry[2]?.trim() ?? "";
    if (raw === "") {
      const items: string[] = [];
      while (index < end) {
        const item = /^\s+-\s*(.*)$/.exec(lines[index] ?? "");
        if (item === null) break;
        items.push(unquote(item[1] ?? ""));
        index += 1;
      }
      properties.push({ name, value: items });
    } else if (raw.startsWith("[") && raw.endsWith("]")) {
      properties.push({
        name,
        value: raw
          .slice(1, -1)
          .split(",")
          .map((item) => unquote(item.trim()))
          .filter((item) => item !== ""),
      });
    } else {
      properties.push({ name, value: unquote(raw) });
    }
  }
  const body = lines.slice(end + 1).join("\n");
  return { properties, body, bodyLine: end + 1 };
}

function unquote(value: string): string {
  if (value.length >= 2) {
    const first = value[0];
    if ((first === '"' || first === "'") && value.endsWith(first)) return value.slice(1, -1);
  }
  return value;
}

/** The tags a note's properties declare, as Obsidian reads them: `tags` or `tag`, list or comma/space separated. */
export function propertyTags(properties: readonly Property[]): string[] {
  const tags: string[] = [];
  for (const property of properties) {
    if (property.name !== "tags" && property.name !== "tag") continue;
    const values = typeof property.value === "string" ? property.value.split(/[\s,]+/) : property.value;
    for (const value of values) {
      const clean = value.trim().replace(/^#/, "");
      if (clean !== "" && !tags.includes(clean)) tags.push(clean);
    }
  }
  return tags;
}

// --- blocks ------------------------------------------------------------------

const FENCE = /^ {0,3}(`{3,}|~{3,})[ \t]*([^\s`]*)/;
const HEADING = /^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*#*[ \t]*$/;
const RULE = /^ {0,3}(?:(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})$/;
const QUOTE = /^ {0,3}>/;
const LIST = /^([ \t]*)([-*+]|\d{1,9}[.)])(?:[ \t]+(.*)|[ \t]*)$/;
const TABLE_DELIMITER = /^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$/;
const CALLOUT = /^\[!([A-Za-z0-9_-]+)\]([+-])?(?:[ \t]+(.*))?$/;
const TASK = /^\[(.)\](?:[ \t]+(.*)|[ \t]*)$/;

function parseBlocks(lines: readonly string[], firstLine: number): Block[] {
  const blocks: Block[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index] ?? "";
    const at = firstLine + index;
    if (line.trim() === "") {
      index += 1;
      continue;
    }

    const fence = FENCE.exec(line);
    if (fence !== null) {
      const marker = fence[1] ?? "```";
      const body: string[] = [];
      let cursor = index + 1;
      while (cursor < lines.length) {
        const candidate = (lines[cursor] ?? "").trim();
        if (candidate.startsWith(marker[0] ?? "`") && /^(`{3,}|~{3,})$/.test(candidate)) break;
        body.push(lines[cursor] ?? "");
        cursor += 1;
      }
      blocks.push({ kind: "code", line: at, language: fence[2] ?? "", text: body.join("\n") });
      index = cursor + 1;
      continue;
    }

    if (RULE.test(line)) {
      blocks.push({ kind: "rule", line: at });
      index += 1;
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading !== null && (heading[2] ?? "") !== "") {
      blocks.push({
        kind: "heading",
        line: at,
        level: heading[1]?.length ?? 1,
        children: parseInline(heading[2] ?? ""),
      });
      index += 1;
      continue;
    }

    if (QUOTE.test(line)) {
      const inner: string[] = [];
      let cursor = index;
      while (cursor < lines.length && QUOTE.test(lines[cursor] ?? "")) {
        inner.push((lines[cursor] ?? "").replace(/^ {0,3}> ?/, ""));
        cursor += 1;
      }
      const callout = CALLOUT.exec(inner[0] ?? "");
      if (callout !== null) {
        blocks.push({
          kind: "callout",
          line: at,
          type: (callout[1] ?? "note").toLowerCase(),
          fold: callout[2] === "+" ? "open" : callout[2] === "-" ? "closed" : null,
          title: parseInline(callout[3] ?? ""),
          children: parseBlocks(inner.slice(1), at + 1),
        });
      } else {
        blocks.push({ kind: "quote", line: at, children: parseBlocks(inner, at) });
      }
      index = cursor;
      continue;
    }

    if (isTableStart(lines, index)) {
      const header = splitRow(line);
      const align = splitRow(lines[index + 1] ?? "").map(alignmentOf);
      const rows: Inline[][][] = [];
      let cursor = index + 2;
      while (cursor < lines.length) {
        const candidate = lines[cursor] ?? "";
        if (candidate.trim() === "" || !candidate.includes("|")) break;
        rows.push(splitRow(candidate).map(parseInline));
        cursor += 1;
      }
      blocks.push({ kind: "table", line: at, align, header: header.map(parseInline), rows });
      index = cursor;
      continue;
    }

    const list = LIST.exec(expandTabs(line));
    if (list !== null) {
      const { block, next } = parseList(lines, index, firstLine);
      blocks.push(block);
      index = next;
      continue;
    }

    // A paragraph: up to a blank line or the start of another block.
    const text: string[] = [line];
    let cursor = index + 1;
    while (cursor < lines.length) {
      const candidate = lines[cursor] ?? "";
      if (candidate.trim() === "" || startsBlock(lines, cursor)) break;
      text.push(candidate);
      cursor += 1;
    }
    blocks.push({ kind: "paragraph", line: at, children: parseInline(text.join("\n")) });
    index = cursor;
  }
  return blocks;
}

function startsBlock(lines: readonly string[], index: number): boolean {
  const line = lines[index] ?? "";
  const heading = HEADING.exec(line);
  return (
    FENCE.test(line) ||
    RULE.test(line) ||
    (heading !== null && (heading[2] ?? "") !== "") ||
    QUOTE.test(line) ||
    LIST.test(expandTabs(line)) ||
    isTableStart(lines, index)
  );
}

function isTableStart(lines: readonly string[], index: number): boolean {
  const line = lines[index] ?? "";
  const next = lines[index + 1];
  return line.includes("|") && next !== undefined && TABLE_DELIMITER.test(next) && next.includes("-");
}

function splitRow(line: string): string[] {
  let trimmed = line.trim();
  if (trimmed.startsWith("|")) trimmed = trimmed.slice(1);
  if (trimmed.endsWith("|") && !trimmed.endsWith("\\|")) trimmed = trimmed.slice(0, -1);
  const cells: string[] = [];
  let current = "";
  for (let index = 0; index < trimmed.length; index += 1) {
    const char = trimmed[index] ?? "";
    if (char === "\\" && trimmed[index + 1] === "|") {
      current += "|";
      index += 1;
    } else if (char === "|") {
      cells.push(current.trim());
      current = "";
    } else {
      current += char;
    }
  }
  cells.push(current.trim());
  return cells;
}

function alignmentOf(cell: string): Alignment {
  const left = cell.startsWith(":");
  const right = cell.endsWith(":");
  if (left && right) return "center";
  if (right) return "right";
  if (left) return "left";
  return null;
}

function expandTabs(line: string): string {
  return line.replace(/^\t+/, (tabs) => "    ".repeat(tabs.length));
}

function indentOf(line: string): number {
  return /^[ ]*/.exec(expandTabs(line))?.[0].length ?? 0;
}

function parseList(
  lines: readonly string[],
  start: number,
  firstLine: number,
): { block: Block; next: number } {
  const opening = LIST.exec(expandTabs(lines[start] ?? ""));
  const indent = opening?.[1]?.length ?? 0;
  const ordered = /^\d/.test(opening?.[2] ?? "");
  const startNumber = ordered ? Number.parseInt(opening?.[2] ?? "1", 10) : 1;
  const items: ListItem[] = [];
  let index = start;

  while (index < lines.length) {
    const expanded = expandTabs(lines[index] ?? "");
    const marker = LIST.exec(expanded);
    if (marker === null || (marker[1]?.length ?? 0) !== indent || /^\d/.test(marker[2] ?? "") !== ordered) break;
    const contentIndent = indent + (marker[2]?.length ?? 1) + 1;
    const itemLine = firstLine + index;
    const content: string[] = [marker[3] ?? ""];
    let cursor = index + 1;
    while (cursor < lines.length) {
      const candidate = lines[cursor] ?? "";
      if (candidate.trim() === "") {
        // A blank line stays in the item only if indented content follows it.
        const after = lines[cursor + 1];
        if (after !== undefined && after.trim() !== "" && indentOf(after) >= contentIndent) {
          content.push("");
          cursor += 1;
          continue;
        }
        break;
      }
      const candidateIndent = indentOf(candidate);
      if (candidateIndent >= contentIndent) {
        content.push(expandTabs(candidate).slice(contentIndent));
        cursor += 1;
        continue;
      }
      // Lazy continuation: prose that wraps under the item without indenting.
      const previous = content[content.length - 1] ?? "";
      if (previous !== "" && !startsBlock(lines, cursor) && !LIST.test(expandTabs(candidate))) {
        content.push(candidate.trim());
        cursor += 1;
        continue;
      }
      break;
    }
    const task = TASK.exec(content[0] ?? "");
    if (task !== null) content[0] = task[2] ?? "";
    items.push({
      line: itemLine,
      task: task === null ? null : (task[1] ?? " "),
      children: parseBlocks(content, itemLine),
    });
    index = cursor;
    // A blank line between items is fine; a blank line followed by anything
    // else ends the list.
    while (index < lines.length && (lines[index] ?? "").trim() === "") {
      const after = lines[index + 1];
      if (after === undefined) break;
      const following = LIST.exec(expandTabs(after));
      if (following === null || (following[1]?.length ?? 0) !== indent) break;
      index += 1;
    }
  }
  return { block: { kind: "list", line: firstLine + start, ordered, start: startNumber, items }, next: index };
}

// --- inline --------------------------------------------------------------------

const TAG_BODY = /^[\p{L}\p{N}_/-]+/u;
const PUNCTUATION = /[!"#$%&'()*+,\-./:;<=>?@[\\\]^_`{|}~]/;
const SAFE_HREF = /^(https?:|mailto:)/i;

export function parseInline(source: string): Inline[] {
  const nodes: Inline[] = [];
  let text = "";
  const flush = () => {
    if (text !== "") {
      nodes.push({ kind: "text", text });
      text = "";
    }
  };

  let index = 0;
  while (index < source.length) {
    const char = source[index] ?? "";
    const rest = source.slice(index);

    if (char === "\\" && index + 1 < source.length) {
      const next = source[index + 1] ?? "";
      if (next === "\n") {
        flush();
        nodes.push({ kind: "break" });
        index += 2;
        continue;
      }
      if (PUNCTUATION.test(next)) {
        text += next;
        index += 2;
        continue;
      }
    }

    if (char === "\n") {
      text = text.replace(/ +$/, "");
      flush();
      nodes.push({ kind: "break" });
      index += 1;
      continue;
    }

    if (char === "`") {
      const run = /^`+/.exec(rest)?.[0] ?? "`";
      const close = rest.indexOf(run, run.length);
      if (close > 0) {
        flush();
        nodes.push({ kind: "code", text: rest.slice(run.length, close).trim() });
        index += close + run.length;
        continue;
      }
    }

    if (rest.startsWith("![[") || rest.startsWith("[[")) {
      const embed = rest.startsWith("!");
      const open = embed ? 3 : 2;
      const close = rest.indexOf("]]", open);
      if (close > open) {
        flush();
        nodes.push(wikilink(rest.slice(open, close), embed));
        index += close + 2;
        continue;
      }
    }

    if (char === "[") {
      const link = markdownLink(rest);
      if (link !== null) {
        flush();
        nodes.push(link.node);
        index += link.length;
        continue;
      }
    }

    if (char === "<") {
      const auto = /^<((?:https?:|mailto:)[^\s<>]+)>/i.exec(rest);
      if (auto !== null) {
        flush();
        const href = auto[1] ?? "";
        nodes.push({ kind: "link", href, children: [{ kind: "text", text: href }] });
        index += auto[0].length;
        continue;
      }
    }

    const wrapped =
      delimited(rest, "**", "strong") ??
      delimited(rest, "__", "strong", true) ??
      delimited(rest, "~~", "strike") ??
      delimited(rest, "==", "mark") ??
      delimited(rest, "*", "em") ??
      delimited(rest, "_", "em", true);
    if (wrapped !== null && (wrapped.node.kind !== "em" || !boundaryBlocked(source, index, wrapped))) {
      flush();
      nodes.push(wrapped.node);
      index += wrapped.length;
      continue;
    }

    if (char === "#" && tagAllowedAt(source, index)) {
      const body = TAG_BODY.exec(rest.slice(1))?.[0];
      if (body !== undefined && /[^\p{N}]/u.test(body)) {
        flush();
        nodes.push({ kind: "tag", tag: body });
        index += body.length + 1;
        continue;
      }
    }

    text += char;
    index += 1;
  }
  flush();
  return nodes;
}

function wikilink(inner: string, embed: boolean): Inline {
  const [reference = "", alias] = inner.split("|", 2);
  const [target = "", heading] = reference.split("#", 2);
  const cleanTarget = target.trim();
  const cleanHeading = heading?.trim() ?? null;
  const label =
    alias?.trim() ??
    (cleanHeading === null || cleanHeading === ""
      ? cleanTarget
      : cleanTarget === ""
        ? cleanHeading
        : `${cleanTarget} > ${cleanHeading}`);
  return {
    kind: "wikilink",
    target: cleanTarget,
    heading: cleanHeading === "" ? null : cleanHeading,
    label: label === "" ? reference : label,
    embed,
  };
}

function markdownLink(rest: string): { node: Inline; length: number } | null {
  const close = rest.indexOf("](");
  if (close < 1) return null;
  const end = rest.indexOf(")", close + 2);
  if (end < 0) return null;
  const label = rest.slice(1, close);
  const destination = rest.slice(close + 2, end).trim().split(/\s+/, 1)[0] ?? "";
  if (label.includes("[") || label.includes("\n")) return null;
  if (SAFE_HREF.test(destination)) {
    return { node: { kind: "link", href: destination, children: parseInline(label) }, length: end + 1 };
  }
  // A relative destination is another note, which Obsidian also writes as a
  // Markdown link when asked to.
  if (destination !== "" && !/^[a-z][a-z0-9+.-]*:/i.test(destination) && !destination.startsWith("#")) {
    let target = destination;
    try {
      target = decodeURIComponent(destination);
    } catch {
      // Not URI-encoded: use it as written.
    }
    const [path = "", heading] = target.replace(/\.md$/i, "").split("#", 2);
    return {
      node: { kind: "wikilink", target: path, heading: heading ?? null, label, embed: false },
      length: end + 1,
    };
  }
  return null;
}

interface Wrapped {
  node: Inline;
  length: number;
  marker: string;
}

function delimited(
  rest: string,
  marker: string,
  kind: "strong" | "em" | "strike" | "mark",
  wordBounded = false,
): Wrapped | null {
  if (!rest.startsWith(marker)) return null;
  const opening = marker.length;
  const first = rest[opening];
  if (first === undefined || /\s/.test(first) || first === marker[0]) return null;
  let close = rest.indexOf(marker, opening + 1);
  while (close > 0) {
    const before = rest[close - 1] ?? "";
    const after = rest[close + marker.length];
    const inwardOk = !/\s/.test(before);
    const boundaryOk = !wordBounded || after === undefined || !/[\p{L}\p{N}]/u.test(after);
    if (inwardOk && boundaryOk) break;
    close = rest.indexOf(marker, close + 1);
  }
  if (close < 0) return null;
  const inner = rest.slice(opening, close);
  if (inner.includes("\n\n")) return null;
  return { node: { kind, children: parseInline(inner) }, length: close + marker.length, marker };
}

/** `_em_` and `*em*` need a word boundary before them; `snake_case_names` are not emphasis. */
function boundaryBlocked(source: string, index: number, wrapped: Wrapped): boolean {
  if (wrapped.marker !== "_") return false;
  const before = source[index - 1];
  return before !== undefined && /[\p{L}\p{N}]/u.test(before);
}

function tagAllowedAt(source: string, index: number): boolean {
  const before = source[index - 1];
  return before === undefined || /[\s([{"'>]/.test(before);
}

// --- helpers for the editor ---------------------------------------------------------

/** Flip the checkbox on `line` of `source`; a line without one is returned unchanged. */
export function toggleTaskLine(source: string, line: number, checked: boolean): string {
  const lines = source.replaceAll("\r\n", "\n").split("\n");
  const current = lines[line];
  if (current === undefined) return source;
  const match = /^(\s*(?:[-*+]|\d{1,9}[.)])\s+)\[(.)\]/.exec(expandTabs(current));
  if (match === null) return source;
  const prefix = match[1] ?? "";
  lines[line] = `${prefix}[${checked ? "x" : " "}]${expandTabs(current).slice(prefix.length + 3)}`;
  return lines.join("\n");
}

/** Words in the body of a note, ignoring the frontmatter. */
export function countWords(source: string): number {
  const { body } = parseFrontmatter(source);
  return body.split(/\s+/).filter((word) => /[\p{L}\p{N}]/u.test(word)).length;
}

/**
 * When the caret sits inside an unfinished `[[`, the text typed so far and
 * where the link began, so the editor can offer note names to complete it.
 */
export function openWikilinkAt(source: string, caret: number): { start: number; query: string } | null {
  const before = source.slice(0, caret);
  const open = before.lastIndexOf("[[");
  if (open < 0) return null;
  const after = before.slice(open + 2);
  if (after.includes("]]") || after.includes("\n")) return null;
  return { start: open, query: after };
}

/** The heading's anchor as Obsidian writes it: the text, with punctuation kept and spaces intact. */
export function headingText(children: readonly Inline[]): string {
  return children
    .map((node) => {
      switch (node.kind) {
        case "text":
        case "code":
          return node.text;
        case "tag":
          return `#${node.tag}`;
        case "wikilink":
          return node.label;
        case "break":
          return " ";
        default:
          return headingText(node.children);
      }
    })
    .join("");
}
