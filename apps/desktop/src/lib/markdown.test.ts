import { describe, expect, it } from "vitest";

import {
  countWords,
  headingText,
  openWikilinkAt,
  parseFrontmatter,
  parseInline,
  parseMarkdown,
  propertyTags,
  toggleTaskLine,
  type Block,
} from "./markdown";

/**
 * The Obsidian dialect, as data. The renderer builds elements from this tree
 * and never from strings, so what is checked here is that a note written in
 * Obsidian is read the way Obsidian reads it.
 */

const kinds = (blocks: readonly Block[]) => blocks.map((block) => block.kind);

describe("frontmatter", () => {
  it("reads scalars, inline lists and dashed lists, and says where the body starts", () => {
    const { properties, body, bodyLine } = parseFrontmatter(
      "---\nstatus: accepted\ntags: [architecture, storage]\naliases:\n  - Storage\n  - 'DB choice'\n---\n# Title\n",
    );

    expect(properties).toEqual([
      { name: "status", value: "accepted" },
      { name: "tags", value: ["architecture", "storage"] },
      { name: "aliases", value: ["Storage", "DB choice"] },
    ]);
    expect(body).toBe("# Title\n");
    expect(bodyLine).toBe(7);
  });

  it("leaves a note without a closing fence alone", () => {
    const { properties, body, bodyLine } = parseFrontmatter("---\nstatus: draft\n# Not closed");

    expect(properties).toEqual([]);
    expect(body).toBe("---\nstatus: draft\n# Not closed");
    expect(bodyLine).toBe(0);
  });

  it("collects tags from a list or a comma separated string, without the hash", () => {
    expect(propertyTags([{ name: "tags", value: ["a", "#b"] }])).toEqual(["a", "b"]);
    expect(propertyTags([{ name: "tag", value: "one, two three" }])).toEqual(["one", "two", "three"]);
    expect(propertyTags([{ name: "status", value: "x" }])).toEqual([]);
  });
});

describe("blocks", () => {
  it("recognises headings, rules, code fences, quotes, lists and tables", () => {
    const { blocks } = parseMarkdown(
      [
        "# Title",
        "",
        "Some *prose*.",
        "",
        "---",
        "",
        "```ts",
        "const x = 1;",
        "```",
        "",
        "> quoted",
        "",
        "- one",
        "- two",
        "",
        "| a | b |",
        "|---|:-:|",
        "| 1 | 2 |",
      ].join("\n"),
    );

    expect(kinds(blocks)).toEqual(["heading", "paragraph", "rule", "code", "quote", "list", "table"]);
    const code = blocks[3];
    expect(code?.kind === "code" && code.language).toBe("ts");
    expect(code?.kind === "code" && code.text).toBe("const x = 1;");
    const table = blocks[6];
    expect(table?.kind === "table" && table.align).toEqual([null, "center"]);
    expect(table?.kind === "table" && table.rows).toHaveLength(1);
  });

  it("reads an Obsidian callout with its type, fold state and title", () => {
    const { blocks } = parseMarkdown("> [!warning]- Careful\n> The body.\n> More body.");

    const callout = blocks[0];
    expect(callout?.kind).toBe("callout");
    if (callout?.kind !== "callout") throw new Error("expected a callout");
    expect(callout.type).toBe("warning");
    expect(callout.fold).toBe("closed");
    expect(headingText(callout.title)).toBe("Careful");
    expect(kinds(callout.children)).toEqual(["paragraph"]);
  });

  it("nests list items by indentation and keeps task state per item", () => {
    const { blocks } = parseMarkdown("- [ ] open\n  - [x] nested done\n- plain\n1. first\n2. second");

    const [bullets, numbers] = blocks;
    if (bullets?.kind !== "list" || numbers?.kind !== "list") throw new Error("expected two lists");
    expect(bullets.ordered).toBe(false);
    expect(bullets.items.map((item) => item.task)).toEqual([" ", null]);
    const nested = bullets.items[0]?.children.find((child) => child.kind === "list");
    expect(nested?.kind === "list" && nested.items[0]?.task).toBe("x");
    expect(numbers.ordered).toBe(true);
    expect(numbers.items).toHaveLength(2);
  });

  it("numbers lines over the whole file so a task can be written back", () => {
    const source = "---\ntags: [x]\n---\n# T\n\n- [ ] first\n- [x] second";
    const { blocks, bodyLine } = parseMarkdown(source);

    expect(bodyLine).toBe(3);
    const list = blocks[1];
    if (list?.kind !== "list") throw new Error("expected a list");
    expect(list.items.map((item) => item.line)).toEqual([5, 6]);
    expect(toggleTaskLine(source, 5, true)).toContain("- [x] first");
    expect(toggleTaskLine(source, 6, false)).toContain("- [ ] second");
    expect(toggleTaskLine(source, 3, true)).toBe(source);
  });

  it("treats a single newline inside a paragraph as a line break, as Obsidian does", () => {
    const { blocks } = parseMarkdown("line one\nline two");

    const paragraph = blocks[0];
    if (paragraph?.kind !== "paragraph") throw new Error("expected a paragraph");
    expect(paragraph.children.map((node) => node.kind)).toEqual(["text", "break", "text"]);
  });
});

describe("inline", () => {
  it("reads wikilinks with headings and aliases, embeds and Markdown links to notes", () => {
    const nodes = parseInline("See [[decisions/storage#Choice|the choice]] and ![[diagram]] and [x](notes/x.md).");

    expect(nodes).toContainEqual({
      kind: "wikilink",
      target: "decisions/storage",
      heading: "Choice",
      label: "the choice",
      embed: false,
    });
    expect(nodes).toContainEqual({ kind: "wikilink", target: "diagram", heading: null, label: "diagram", embed: true });
    expect(nodes).toContainEqual({ kind: "wikilink", target: "notes/x", heading: null, label: "x", embed: false });
  });

  it("labels a heading link the way Obsidian displays it", () => {
    expect(parseInline("[[note#Part two]]")[0]).toMatchObject({ label: "note > Part two" });
  });

  it("keeps only http, https and mailto destinations as external links", () => {
    expect(parseInline("[a](https://example.test)")[0]).toMatchObject({ kind: "link", href: "https://example.test" });
    expect(parseInline("[a](javascript:alert(1))")).toEqual([{ kind: "text", text: "[a](javascript:alert(1))" }]);
  });

  it("reads emphasis, highlights, strikethrough and code, and leaves snake_case alone", () => {
    const nodes = parseInline("**bold** *em* ==mark== ~~gone~~ `code` snake_case_name");

    expect(nodes.map((node) => node.kind)).toEqual([
      "strong",
      "text",
      "em",
      "text",
      "mark",
      "text",
      "strike",
      "text",
      "code",
      "text",
    ]);
    expect(nodes.at(-1)).toEqual({ kind: "text", text: " snake_case_name" });
  });

  it("reads tags but not headings, numbers or fragments inside words", () => {
    expect(parseInline("a #tag/nested and #2026 and word#not")).toEqual([
      { kind: "text", text: "a " },
      { kind: "tag", tag: "tag/nested" },
      { kind: "text", text: " and #2026 and word#not" },
    ]);
  });

  it("honours backslash escapes", () => {
    expect(parseInline("\\*not em\\* and \\[\\[not a link\\]\\]")).toEqual([
      { kind: "text", text: "*not em* and [[not a link]]" },
    ]);
  });
});

describe("editor helpers", () => {
  it("counts words in the body only", () => {
    expect(countWords("---\ntags: [a, b, c]\n---\nOne two three.")).toBe(3);
  });

  it("finds an unfinished wikilink at the caret and nothing once it is closed", () => {
    expect(openWikilinkAt("see [[dec", 9)).toEqual({ start: 4, query: "dec" });
    expect(openWikilinkAt("see [[decisions]] more", 22)).toBeNull();
    expect(openWikilinkAt("see [[\nnext", 10)).toBeNull();
  });
});
