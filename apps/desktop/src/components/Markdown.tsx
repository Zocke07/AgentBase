import { Fragment, useMemo, type ReactNode } from "react";

import {
  headingText,
  parseMarkdown,
  propertyTags,
  type Block,
  type Inline,
  type ListItem,
  type Property,
} from "../lib/markdown";
import { insideTauri } from "../lib/tauri";

/**
 * Obsidian-flavoured Markdown as React elements. Everything is built from the
 * parsed tree, never from strings, so a note or an agent's prose cannot inject
 * markup. The same component renders a vault note, the supervisor's summary
 * and a retrieved excerpt; what differs is which callbacks are wired.
 */

export interface MarkdownProps {
  source: string;
  /** Follow a `[[wikilink]]`. Without it links are plain text. */
  onLink?: ((target: string, heading: string | null) => void) | undefined;
  /** A `#tag` was clicked. Without it tags are plain chips. */
  onTag?: ((tag: string) => void) | undefined;
  /** A task's checkbox was toggled; `line` indexes the whole source. Without it boxes are read-only. */
  onToggleTask?: ((line: number, checked: boolean) => void) | undefined;
  /** Show the frontmatter as a properties panel above the body. */
  properties?: boolean;
  className?: string | undefined;
}

export function Markdown({ source, onLink, onTag, onToggleTask, properties = false, className }: MarkdownProps) {
  const document = useMemo(() => parseMarkdown(source), [source]);
  const context: Context = { onLink, onTag, onToggleTask };
  return (
    <div className={`md${className === undefined ? "" : ` ${className}`}`}>
      {properties && document.properties.length > 0 && (
        <PropertiesPanel properties={document.properties} onTag={onTag} />
      )}
      {document.blocks.map((block) => renderBlock(block, context))}
    </div>
  );
}

interface Context {
  onLink: MarkdownProps["onLink"];
  onTag: MarkdownProps["onTag"];
  onToggleTask: MarkdownProps["onToggleTask"];
}

function PropertiesPanel({ properties, onTag }: { properties: readonly Property[]; onTag: MarkdownProps["onTag"] }) {
  return (
    <dl className="md__properties" aria-label="Properties">
      {properties.map((property) => (
        <div key={property.name} className="md__property">
          <dt>{property.name}</dt>
          <dd>{renderPropertyValue(property, onTag)}</dd>
        </div>
      ))}
    </dl>
  );
}

function renderPropertyValue(property: Property, onTag: MarkdownProps["onTag"]): ReactNode {
  if (property.name === "tags" || property.name === "tag") {
    return propertyTags([property]).map((tag) => <Tag key={tag} tag={tag} onTag={onTag} />);
  }
  if (typeof property.value === "string") {
    return property.value === "" ? <span className="md__property-empty">empty</span> : property.value;
  }
  if (property.value.length === 0) return <span className="md__property-empty">empty</span>;
  return property.value.map((item, index) => (
    <span key={`${String(index)}:${item}`} className="md__property-item">
      {item}
    </span>
  ));
}

function renderBlock(block: Block, context: Context): ReactNode {
  const key = `${block.kind}:${String(block.line)}`;
  switch (block.kind) {
    case "heading": {
      const text = headingText(block.children);
      const children = renderInline(block.children, context, key);
      const props = { key, className: "md__heading", "data-heading": text };
      switch (block.level) {
        case 1:
          return <h1 {...props}>{children}</h1>;
        case 2:
          return <h2 {...props}>{children}</h2>;
        case 3:
          return <h3 {...props}>{children}</h3>;
        case 4:
          return <h4 {...props}>{children}</h4>;
        case 5:
          return <h5 {...props}>{children}</h5>;
        default:
          return <h6 {...props}>{children}</h6>;
      }
    }
    case "paragraph":
      return <p key={key}>{renderInline(block.children, context, key)}</p>;
    case "code":
      return (
        <pre key={key} className="md__code" data-language={block.language === "" ? undefined : block.language}>
          <code>{block.text}</code>
        </pre>
      );
    case "quote":
      return (
        <blockquote key={key} className="md__quote">
          {block.children.map((child) => renderBlock(child, context))}
        </blockquote>
      );
    case "callout": {
      const type = calloutFamily(block.type);
      const title =
        block.title.length === 0 ? (
          <span>{calloutTitle(block.type)}</span>
        ) : (
          <span>{renderInline(block.title, context, key)}</span>
        );
      const body = block.children.map((child) => renderBlock(child, context));
      if (block.fold === null) {
        return (
          <div key={key} className={`md__callout md__callout--${type}`} data-callout={block.type}>
            <p className="md__callout-title">{title}</p>
            {body.length > 0 && <div className="md__callout-body">{body}</div>}
          </div>
        );
      }
      return (
        <details
          key={key}
          className={`md__callout md__callout--${type} md__callout--foldable`}
          data-callout={block.type}
          open={block.fold === "open"}
        >
          <summary className="md__callout-title">{title}</summary>
          {body.length > 0 && <div className="md__callout-body">{body}</div>}
        </details>
      );
    }
    case "list": {
      const items = block.items.map((item) => renderItem(item, context));
      return block.ordered ? (
        <ol key={key} className="md__list" start={block.start === 1 ? undefined : block.start}>
          {items}
        </ol>
      ) : (
        <ul key={key} className="md__list">
          {items}
        </ul>
      );
    }
    case "table":
      return (
        <div key={key} className="md__table-wrap">
          <table className="md__table">
            <thead>
              <tr>
                {block.header.map((cell, column) => (
                  <th key={column} style={alignStyle(block.align[column] ?? null)}>
                    {renderInline(cell, context, `${key}:h${String(column)}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {row.map((cell, column) => (
                    <td key={column} style={alignStyle(block.align[column] ?? null)}>
                      {renderInline(cell, context, `${key}:${String(rowIndex)}:${String(column)}`)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case "rule":
      return <hr key={key} className="md__rule" />;
  }
}

function alignStyle(align: "left" | "center" | "right" | null): { textAlign: "left" | "center" | "right" } | undefined {
  return align === null ? undefined : { textAlign: align };
}

function renderItem(item: ListItem, context: Context): ReactNode {
  const key = `item:${String(item.line)}`;
  const children = item.children.map((child) => renderBlock(child, context));
  if (item.task === null) return <li key={key}>{children}</li>;
  const checked = item.task !== " ";
  const editable = context.onToggleTask !== undefined;
  return (
    <li key={key} className={`md__task${checked ? " md__task--done" : ""}`} data-task={item.task}>
      <label className="md__task-box">
        <input
          type="checkbox"
          checked={checked}
          readOnly={!editable}
          disabled={!editable}
          aria-label={checked ? "Mark as not done" : "Mark as done"}
          onChange={(event) => {
            context.onToggleTask?.(item.line, event.target.checked);
          }}
        />
      </label>
      <div className="md__task-text">{children}</div>
    </li>
  );
}

function renderInline(nodes: readonly Inline[], context: Context, prefix: string): ReactNode[] {
  return nodes.map((node, index) => {
    const key = `${prefix}:${String(index)}`;
    switch (node.kind) {
      case "text":
        return <Fragment key={key}>{node.text}</Fragment>;
      case "break":
        return <br key={key} />;
      case "strong":
        return <strong key={key}>{renderInline(node.children, context, key)}</strong>;
      case "em":
        return <em key={key}>{renderInline(node.children, context, key)}</em>;
      case "strike":
        return <del key={key}>{renderInline(node.children, context, key)}</del>;
      case "mark":
        return <mark key={key}>{renderInline(node.children, context, key)}</mark>;
      case "code":
        return <code key={key}>{node.text}</code>;
      case "tag":
        return <Tag key={key} tag={node.tag} onTag={context.onTag} />;
      case "link":
        return <ExternalLink key={key} href={node.href}>{renderInline(node.children, context, key)}</ExternalLink>;
      case "wikilink": {
        const className = node.embed ? "md__wikilink md__wikilink--embed" : "md__wikilink";
        const title = node.heading === null ? node.target : `${node.target}#${node.heading}`;
        if (context.onLink === undefined) {
          return (
            <span key={key} className={className} title={title}>
              {node.label}
            </span>
          );
        }
        const follow = context.onLink;
        return (
          <button
            key={key}
            type="button"
            className={className}
            title={title}
            onClick={() => {
              follow(node.target, node.heading);
            }}
          >
            {node.label}
          </button>
        );
      }
    }
  });
}

function Tag({ tag, onTag }: { tag: string; onTag: MarkdownProps["onTag"] }) {
  if (onTag === undefined) return <span className="md__tag">#{tag}</span>;
  return (
    <button
      type="button"
      className="md__tag"
      onClick={() => {
        onTag(tag);
      }}
    >
      #{tag}
    </button>
  );
}

/**
 * The webview is granted no opener, so inside the shell an external address
 * is copied for the person to open where they choose; in a browser tab it is
 * an ordinary link.
 */
function ExternalLink({ href, children }: { href: string; children: ReactNode }) {
  const shell = insideTauri();
  return (
    <a
      className="md__link"
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      title={shell ? `${href} (click to copy the address)` : href}
      onClick={
        shell
          ? (event) => {
              event.preventDefault();
              void navigator.clipboard.writeText(href).catch(() => undefined);
            }
          : undefined
      }
    >
      {children}
    </a>
  );
}

/** Obsidian's callout aliases, folded to the family whose colour and icon they share. */
function calloutFamily(type: string): string {
  switch (type) {
    case "abstract":
    case "summary":
    case "tldr":
      return "abstract";
    case "info":
      return "info";
    case "todo":
      return "todo";
    case "tip":
    case "hint":
    case "important":
      return "tip";
    case "success":
    case "check":
    case "done":
      return "success";
    case "question":
    case "help":
    case "faq":
      return "question";
    case "warning":
    case "caution":
    case "attention":
      return "warning";
    case "failure":
    case "fail":
    case "missing":
      return "failure";
    case "danger":
    case "error":
      return "danger";
    case "bug":
      return "bug";
    case "example":
      return "example";
    case "quote":
    case "cite":
      return "quote";
    default:
      return "note";
  }
}

function calloutTitle(type: string): string {
  return type.charAt(0).toUpperCase() + type.slice(1);
}
