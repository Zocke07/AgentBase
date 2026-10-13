import type { MemoryItem } from "@agentbase/schemas";
import { useEffect, useRef, useState } from "react";

import * as api from "../lib/api";
import { ellipsise, formatCount, formatDuration, formatMicros } from "../lib/format";
import { policySentence, STATUS_LABEL } from "../state/describe";
import { splitPath, writtenFiles, type WrittenFile } from "../state/files";
import { isMissedLookup, type RunView } from "../state/reducer";

import { Markdown } from "./Markdown";
import { MetricBar } from "./MetricBar";

/**
 * Run header and outcome. Label terminal `summary` as supervisor claim, not
 * fact, and show it beside log-derived counts.
 */

export interface RunSummaryProps {
  view: RunView;
  /** An automation's name for the run, from its row; its goal then folds beneath. */
  title?: string | null | undefined;
  /** Open cited Knowledge note; absent without navigation. */
  onOpenNote?: ((path: string, heading: string | null) => void) | undefined;
  /** Open a written data file in Knowledge's Agent files; absent without navigation. */
  onOpenFile?: ((path: string) => void) | undefined;
  /** Run space, used to look up memory status. */
  spaceId?: string | null | undefined;
  /** Open run memory beside inbox for approval or dismissal. */
  onOpenMemory?: ((path: string) => void) | undefined;
  /** Memory status changed; reload Knowledge inbox. */
  onMemoryChanged?: (() => void) | undefined;
  /** Do not fold; parent has fixed height and scrolls. */
  unfolded?: boolean | undefined;
}

/** Fold summaries above this height to preserve canvas visibility. */
const CLAIM_FOLD_PX = 220;

export function RunSummary({
  view,
  title = null,
  onOpenNote,
  onOpenFile,
  spaceId = null,
  onOpenMemory,
  onMemoryChanged,
  unfolded,
}: RunSummaryProps) {
  const denied = view.denials.length;
  const sandboxed = view.denials.filter((denial) => denial.blockedBy === "sandbox").length;
  // A lookup that found nothing changed nothing; it is listed, not alarmed.
  const lookups = view.errors.filter(isMissedLookup).length;
  const modelErrors = view.errors.filter((error) => error.kind === "llm").length;
  const toolErrors = view.errors.length - modelErrors - lookups;
  const failures = modelErrors + toolErrors;
  const failureKinds = [
    modelErrors > 0
      ? `${String(modelErrors)} model failure${modelErrors === 1 ? "" : "s"}`
      : null,
    toolErrors > 0 ? `${String(toolErrors)} tool failure${toolErrors === 1 ? "" : "s"}` : null,
    lookups > 0 ? `${String(lookups)} missed lookup${lookups === 1 ? "" : "s"}` : null,
  ].filter((label): label is string => label !== null);
  const kinds =
    failureKinds.length > 1
      ? `${failureKinds.slice(0, -1).join(", ")} and ${failureKinds[failureKinds.length - 1] ?? ""}`
      : (failureKinds[0] ?? "");
  // Use log timestamps so replay matches live; live duration grows with events.
  const duration =
    view.startedTs !== null && view.latestTs !== null
      ? formatDuration(Date.parse(view.latestTs) - Date.parse(view.startedTs))
      : null;

  return (
    <section className="run-summary" data-testid="run-summary">
      <header className="run-summary__head">
        <span className={`status status--${view.status}`} data-testid="run-status">
          {STATUS_LABEL[view.status]}
        </span>
        {failures > 0 && (
          <span className="run-summary__issue-badge" data-testid="run-issue-badge">
            {failures} {failures === 1 ? "error" : "errors"}
          </span>
        )}
        {title === null ? (
          <h2 className="run-summary__goal">{view.goal ?? "No goal recorded yet"}</h2>
        ) : (
          <>
            <h2 className="run-summary__goal" data-testid="run-title">
              {title}
            </h2>
            {view.goal !== null && (
              <details className="run-summary__brief">
                <summary>What it was asked to do</summary>
                <p>{view.goal}</p>
              </details>
            )}
          </>
        )}
        {view.origin !== null && (
          // Same fold for Discord runs; show origin identity.
          <p className="run-summary__origin" data-testid="run-origin">
            Started from {view.origin.channel} by {view.origin.identity ?? "an unknown identity"}
            {view.origin.displayName !== null && ` (${view.origin.displayName})`}
          </p>
        )}
        {view.approvalPolicy !== null && (
          // With nobody answering calls one by one, this is why each one ran.
          <p className="run-summary__policy" data-testid="run-policy">
            {policySentence(view.approvalPolicy)}
          </p>
        )}
      </header>

      <dl className="run-summary__facts">
        <div>
          <dt>Agents</dt>
          <dd data-testid="fact-agents">{view.agentOrder.length}</dd>
        </div>
        <div>
          <dt>Tool calls</dt>
          {/* `tool.called`, not `tool.requested`: what executed, not what was asked. */}
          <dd data-testid="fact-tool-calls">{view.toolCalls.length}</dd>
        </div>
        <div>
          <dt>Denied</dt>
          <dd data-testid="fact-denied">
            {denied}
            {sandboxed > 0 && <span className="run-summary__sandboxed"> ({sandboxed} sandbox)</span>}
          </dd>
        </div>
        <div>
          <dt>Tokens</dt>
          <dd data-testid="fact-tokens">
            {formatCount(view.inputTokens)} in / {formatCount(view.outputTokens)} out
          </dd>
        </div>
        {duration !== null && (
          <div>
            <dt>Duration</dt>
            <dd data-testid="fact-duration">{duration}</dd>
          </div>
        )}
        <div>
          <dt>Cost</dt>
          {/* Summed from the ledger's figure on each `llm.response`: the same
              integer the budget meter is built from, never a float here. */}
          <dd data-testid="fact-cost">{formatMicros(view.costMicros)}</dd>
        </div>
        <div className={failures > 0 ? "run-summary__fact--bad" : undefined}>
          <dt>Errors</dt>
          {/* `llm.error` and `tool.error`. Folded from the start, rendered
              nowhere until now: an agent that hit five provider errors in
              a row looked exactly like an agent that was thinking. */}
          <dd data-testid="fact-errors">{failures}</dd>
        </div>
      </dl>

      {/* Keyed by run so a list unfolded for one run starts folded for the next. */}
      <RunFiles key={view.runId ?? ""} files={writtenFiles(view)} onOpenNote={onOpenNote} onOpenFile={onOpenFile} />

      {view.budgetExceeded && (
        <p className="run-summary__cap" role="alert" data-testid="budget-exceeded">
          This run hit the monthly cap. Nothing past this point called a model.
        </p>
      )}

      {view.errors.length > 0 && (
        <details
          className={`run-summary__problems${failures === 0 ? " run-summary__problems--lookups" : ""}`}
          data-testid="run-errors"
        >
          <summary>
            <span className="run-summary__problem-mark" aria-hidden="true">
              {failures === 0 ? "?" : "!"}
            </span>
            <span className="run-summary__problem-copy">
              {failures === 0 ? (
                <>
                  <strong>
                    {lookups} missed {lookups === 1 ? "lookup" : "lookups"}
                  </strong>
                  <small>
                    An agent looked for something that was not there, or asked without saying what.
                    Nothing was changed, and the agent was told each time.
                  </small>
                </>
              ) : (
                <>
                  <strong>
                    {failures} {failures === 1 ? "error" : "errors"} during this run
                  </strong>
                  <small>{kinds}. Review these before trusting the outcome.</small>
                </>
              )}
            </span>
            <span className="run-summary__problem-action" aria-hidden="true">
              Details
            </span>
          </summary>
          <ul className="run-summary__errors">
            {view.errors.map((error) => (
              <li key={error.seq} className={`run-summary__error run-summary__error--${error.kind}`}>
                <span className="run-summary__error-who">
                  {error.agent ?? "run"} ·{" "}
                  {error.kind === "llm" ? "model" : isMissedLookup(error) ? "lookup" : "tool"}
                </span>
                <span className="run-summary__error-text">{ellipsise(error.message, 160)}</span>
              </li>
            ))}
          </ul>
        </details>
      )}

      {(view.knowledge.length > 0 || view.knowledgeExclusions.length > 0) && (
        <details className="run-summary__context" data-testid="run-context">
          <summary>
            Retrieved context: {view.knowledge.length} excerpt
            {view.knowledge.length === 1 ? "" : "s"}, about{" "}
            {formatCount(
              view.knowledge.reduce((total, hit) => total + (hit.estimatedTokens ?? 0), 0),
            )}{" "}
            tokens
            {view.knowledgeExclusions.length > 0 &&
              `, ${String(view.knowledgeExclusions.length)} excluded by you`}
          </summary>
          <p className="run-summary__context-note">
            {/* The excerpts are what `run.started` recorded for the supervisor;
                each worker's own retrieval is in its `llm.request` message. */}
            These excerpts were sent to the supervisor with the goal as untrusted reference
            material. Workers retrieved their own for each handoff; see their model requests
            in the log.
          </p>
          <ul className="run-summary__excerpts">
            {view.knowledge.map((hit) => (
              <li key={hit.citation}>
                {onOpenNote !== undefined && hit.path !== null ? (
                  <button
                    type="button"
                    className="citation"
                    onClick={() => {
                      onOpenNote(hit.path ?? "", hit.heading);
                    }}
                  >
                    {hit.citation}
                  </button>
                ) : (
                  <code>{hit.citation}</code>
                )}
                {hit.score !== null && <MetricBar value={hit.score} label={`Relevance for ${hit.citation}`} />}
                <small>
                  {hit.score !== null && `${String(Math.round(hit.score * 100))}% relevance`}
                  {hit.estimatedTokens !== null && ` · ${String(hit.estimatedTokens)} tokens`}
                  {hit.matchedTerms.length > 0 && ` · matched ${hit.matchedTerms.join(", ")}`}
                  {hit.reasons.length > 0 && ` · ${hit.reasons.join(" · ")}`}
                </small>
              </li>
            ))}
            {view.knowledgeExclusions.map((citation) => (
              <li key={`excluded:${citation}`} className="run-summary__excluded">
                <code>{citation}</code>
                <small>excluded before the run started</small>
              </li>
            ))}
          </ul>
        </details>
      )}

      {view.claim !== null && (
        <div className={`claim claim--${view.claim.kind}`} data-testid="run-claim">
          <span className="claim__label">
            {view.claim.kind === "summary"
              ? "The supervisor's account of the run"
              : "Why the run stopped"}
          </span>
          {/* Keyed by run so the fold starts closed on each run rather than carrying over. */}
          <FoldedClaim key={view.runId ?? ""} text={view.claim.text} unfolded={unfolded ?? false} />
          {view.claim.kind === "summary" && (
            <p className="claim__caveat">
              This is what the agent said it did. What it actually did is the{" "}
              {view.toolCalls.length} tool {view.toolCalls.length === 1 ? "call" : "calls"} in the
              log below.
            </p>
          )}
          {view.memoryPath !== null && (
            <RunMemory
              key={`${spaceId ?? ""}:${view.memoryPath}`}
              path={view.memoryPath}
              spaceId={spaceId}
              onOpen={onOpenMemory ?? (onOpenNote === undefined ? undefined : (path) => { onOpenNote(path, null); })}
              onChanged={onMemoryChanged}
            />
          )}
        </div>
      )}

      {view.unrecognised.length > 0 && (
        <p className="run-summary__unknown" role="alert" data-testid="unrecognised-events">
          This build does not recognise {view.unrecognised.length} event type
          {view.unrecognised.length === 1 ? "" : "s"}: {[...new Set(view.unrecognised)].join(", ")}.
          The dashboard is out of date with the sidecar.
        </p>
      )}
    </section>
  );
}


/**
 * Fold long supervisor claims so their supporting canvas and log remain visible.
 */
function FoldedClaim({ text, unfolded }: { text: string; unfolded: boolean }) {
  const body = useRef<HTMLDivElement>(null);
  const [overflows, setOverflows] = useState(false);
  const [open, setOpen] = useState(false);
  const folded = overflows && !open && !unfolded;

  // Measure Markdown because layout and resize, not character count, set height.
  useEffect(() => {
    const element = body.current;
    if (element === null) return undefined;
    const observer = new ResizeObserver(() => {
      setOverflows(element.scrollHeight > CLAIM_FOLD_PX + 8);
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, [text]);

  return (
    <div className={`claim__body${folded ? " claim__body--folded" : ""}`}>
      <div ref={body} className="claim__scroll">
        <Markdown source={text} className="claim__text" />
      </div>
      {overflows && !unfolded && (
        <button
          type="button"
          className="claim__fold"
          aria-expanded={open}
          onClick={() => {
            setOpen((current) => !current);
          }}
        >
          {open ? "Show less" : "Show the whole summary"}
        </button>
      )}
    </div>
  );
}

const MEMORY_WORD: Record<MemoryItem["status"], string> = {
  proposed: "needs your attention before future runs can use it",
  approved: "available to future runs when relevant",
  archived: "in history; future runs will not use it",
};

const MEMORY_STATUS: Record<MemoryItem["status"], string> = {
  proposed: "needs attention",
  approved: "available",
  archived: "history",
};

/**
 * Run-written memory with live trust status and inline approval; other memory
 * actions remain in Knowledge inbox.
 */
function RunMemory({
  path,
  spaceId,
  onOpen,
  onChanged,
}: {
  path: string;
  spaceId: string | null;
  onOpen: ((path: string) => void) | undefined;
  onChanged: (() => void) | undefined;
}) {
  const [item, setItem] = useState<MemoryItem | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Caller keys by path, so different memory gets fresh row.
  useEffect(() => {
    if (spaceId === null) return undefined;
    let live = true;
    void api
      .listMemories(spaceId)
      .then((index) => {
        if (live) setItem(index.items.find((entry) => entry.path === path) ?? null);
      })
      .catch(() => {
        // Missing status still names file; not an alarm.
      });
    return () => {
      live = false;
    };
  }, [spaceId, path]);

  const approve = async () => {
    if (spaceId === null) return;
    setBusy(true);
    setError(null);
    try {
      setItem(await api.updateMemory(spaceId, path, { status: "approved" }));
      onChanged?.();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };

  const status = item?.status ?? null;
  return (
    <div className="claim__memory" data-testid="run-memory">
      <span className="claim__memory-text">
        Saved a run summary at <code>{path}</code>
        {status !== null && (
          <>
            {" "}
            <span className={`memory-status memory-status--${status}`}>{item?.pinned === true ? "always included" : MEMORY_STATUS[status]}</span>{" "}
            <span className="claim__memory-word">{item?.pinned === true ? "included in every future run" : MEMORY_WORD[status]}</span>
          </>
        )}
        {status === null && spaceId === null && ". Keep it in Saved context before later runs can retrieve it."}
        {item?.managed_at !== null && item?.managed_at !== undefined && (
          <span className="claim__memory-word">
            {` Managed by ${item.management_model ?? "the space model"}${item.management_reason === null || item.management_reason === undefined ? "." : `: ${item.management_reason}`}`}
          </span>
        )}
      </span>
      <span className="claim__memory-actions">
        {status === "proposed" && (
          <button type="button" className="button button--small button--primary" disabled={busy} onClick={() => void approve()}>
            {busy ? "Keeping…" : "Keep for future runs"}
          </button>
        )}
        {onOpen !== undefined && (
          <button
            type="button"
            className="button button--small"
            onClick={() => {
              onOpen(path);
            }}
          >
            Review saved context
          </button>
        )}
      </span>
      {error !== null && (
        <span className="field-error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

/** Chips shown before the rest of a long list folds behind a count. */
const FILES_SHOWN = 6;

/**
 * What the run wrote, from its log, each opening where it lives: a run that
 * reported "decisions/2026-10-07.md" left its reader searching for it.
 */
function RunFiles({
  files,
  onOpenNote,
  onOpenFile,
}: {
  files: readonly WrittenFile[];
  onOpenNote: RunSummaryProps["onOpenNote"];
  onOpenFile: RunSummaryProps["onOpenFile"];
}) {
  const [all, setAll] = useState(false);
  if (files.length === 0) return null;
  const shown = all ? files : files.slice(0, FILES_SHOWN);
  return (
    <div className="run-files" data-testid="run-files">
      <span className="run-files__label">
        Wrote {files.length} {files.length === 1 ? "file" : "files"}
      </span>
      <ul className="run-files__list">
        {shown.map((file) => {
          const { name, folder } = splitPath(file.path);
          const open =
            file.kind === "note"
              ? onOpenNote && (() => { onOpenNote(file.path, null); })
              : onOpenFile && (() => { onOpenFile(file.path); });
          const label = (
            <>
              {folder !== "" && <span className="run-files__folder">{folder}/</span>}
              <span className="run-files__name">{name}</span>
            </>
          );
          return (
            <li key={file.path}>
              {open === undefined ? (
                <code className="run-files__file">{label}</code>
              ) : (
                <button type="button" className="run-files__file" title={`Open ${file.path}`} onClick={open}>
                  {label}
                </button>
              )}
            </li>
          );
        })}
        {!all && files.length > FILES_SHOWN && (
          <li>
            <button
              type="button"
              className="run-files__more"
              onClick={() => {
                setAll(true);
              }}
            >
              {files.length - FILES_SHOWN} more
            </button>
          </li>
        )}
      </ul>
    </div>
  );
}
