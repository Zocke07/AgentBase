import type { TextFileSummary } from "@agentbase/schemas";
import { useEffect, useMemo, useState } from "react";

import * as api from "../lib/api";
import { isMissing } from "../lib/errors";
import {
  dashboardJson,
  defaultVisualization,
  fileKind,
  parseDashboardSpec,
  parseDataFile,
  parseVisualizationSpec,
  slugify,
  uniquePath,
  visualizationJson,
  type Aggregate,
  type ChartKind,
  type DashboardSpec,
  type DataSet,
  type Scalar,
  type SortOrder,
  type VisualizationSpec,
} from "../lib/visualization";

import { Chart } from "./Chart";
import { MermaidDiagram } from "./MermaidDiagram";

/**
 * An agent file drawn rather than read as text: a data file as a chart, and a
 * saved chart, dashboard or diagram as itself. Each view edits the same file
 * text the Text view shows, so what is saved stays an ordinary file that an
 * agent writes through the same approval as any other write.
 */

/** How many rows a Preview shows; Text has the whole file. */
const PREVIEW_ROWS = 200;

type Preview =
  | { readonly kind: "table"; readonly data: DataSet }
  | { readonly kind: "text"; readonly text: string; readonly note: string | null };

/**
 * A file read, not edited, which is how Knowledge opens one: rows as a
 * table, other JSON indented, anything else as written. A look at a file can
 * no longer change it; Text is where it is edited.
 */
export function DataPreview({ path, content }: { path: string; content: string }) {
  const preview = useMemo(() => previewOf(path, content), [path, content]);
  if (preview.kind === "text") {
    return (
      <div className="file-preview" data-testid="file-preview">
        {preview.note !== null && <p className="file-preview__note">{preview.note}</p>}
        {preview.text !== "" && <pre className="file-preview__text">{preview.text}</pre>}
      </div>
    );
  }
  const { data } = preview;
  const total = data.rows.length;
  const rows = data.rows.slice(0, PREVIEW_ROWS);
  return (
    <div className="file-preview" data-testid="file-preview">
      <p className="file-preview__note">
        {total > PREVIEW_ROWS
          ? `The first ${String(PREVIEW_ROWS)} of ${total.toLocaleString()} rows. Text shows all of it.`
          : `${total.toLocaleString()} row${total === 1 ? "" : "s"}.`}
      </p>
      <div className="file-preview__scroll">
        <table className="file-preview__table">
          <thead>
            <tr>
              {data.columns.map((column) => (
                <th key={column.name} scope="col">
                  {column.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, position) => (
              <tr key={position}>
                {data.columns.map((column) => (
                  <td key={column.name} className={column.kind === "number" ? "file-preview__number" : undefined}>
                    {cellText(row[column.name] ?? null)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function previewOf(path: string, content: string): Preview {
  if (content.trim() === "") return { kind: "text", text: "", note: "This file is empty." };
  const lower = path.toLowerCase();
  if (lower.endsWith(".json")) {
    let value: unknown;
    try {
      value = JSON.parse(content);
    } catch (failure) {
      return { kind: "text", text: content, note: `This is not valid JSON (${message(failure)}), so it is shown as written.` };
    }
    // A list of records reads as a table; settings and nested records as indented JSON.
    if (Array.isArray(value) && value.length > 0) {
      const table = attempt(() => parseDataFile(path, content));
      if ("value" in table && table.value.columns.length > 0) return { kind: "table", data: table.value };
    }
    return { kind: "text", text: JSON.stringify(value, null, 2), note: null };
  }
  if (fileKind(path) === "data") {
    const table = attempt(() => parseDataFile(path, content));
    if ("error" in table) {
      return { kind: "text", text: content, note: `This could not be read as rows (${table.error}), so it is shown as written.` };
    }
    if (table.value.rows.length > 0 && table.value.columns.length > 0) return { kind: "table", data: table.value };
  }
  return { kind: "text", text: content, note: null };
}

/** A cell as a person reads it: large figures grouped, small ones and years as written. */
function cellText(value: Scalar): string {
  if (value === null) return "";
  if (typeof value === "number") {
    return value.toLocaleString(undefined, { maximumFractionDigits: 6, useGrouping: Math.abs(value) >= 10_000 });
  }
  return String(value);
}

interface LoadedChart {
  path: string;
  spec: VisualizationSpec | null;
  data: DataSet | null;
  error: string | null;
  /** Its data file is not written yet, as before a pipeline's first weekly review. */
  waiting: boolean;
}

/** A chart whose data is not there yet: said calmly, since a run will write it. */
function noDataYet(source: string): string {
  return `No data yet: ${source} appears once a run writes it.`;
}

/** An open data file drawn as a chart, which can be saved as a chart file of its own. */
export function DataChart({
  spaceId,
  path,
  content,
  dirty,
  files,
  onSaved,
}: {
  spaceId: string;
  path: string;
  /** The editor's text, so the chart is of what the Text view shows. */
  content: string;
  dirty: boolean;
  files: readonly TextFileSummary[];
  onSaved: (path: string) => void;
}) {
  const parsed = useMemo(() => attempt(() => parseDataFile(path, content)), [path, content]);
  // The person's settings; until they change one, the chart is inferred.
  const [chosen, setChosen] = useState<VisualizationSpec | null>(null);
  const [target, setTarget] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if ("error" in parsed) {
    return (
      <div className="file-view">
        <p className="file-view__note" role="alert">
          This file cannot be drawn as a chart: {parsed.error}
        </p>
      </div>
    );
  }

  const spec = chosen ?? defaultVisualization(path, parsed.value);
  const savePath =
    target ??
    uniquePath(
      `visualizations/${slugify(spec.title)}.viz.json`,
      files.map((file) => file.path),
    );

  const save = async () => {
    const wanted = savePath.trim();
    if (!wanted.toLowerCase().endsWith(".viz.json")) {
      setError("A saved chart's file name ends in .viz.json.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      // A new chart never replaces one the space already has under that name.
      await api.writeFile(spaceId, wanted, visualizationJson(spec), { create: true });
      onSaved(wanted);
    } catch (failure) {
      setError(message(failure));
      setBusy(false);
    }
  };

  return (
    <div className="file-view">
      <div className="file-view__bar">
        <label className="file-view__save-as">
          <span>Save as</span>
          <input
            aria-label="Chart file path"
            value={savePath}
            onChange={(event) => {
              setTarget(event.target.value);
            }}
          />
        </label>
        <button
          type="button"
          className="button button--small button--primary"
          disabled={busy || dirty}
          title={dirty ? "Save this file's changes first: a saved chart reads the saved file." : undefined}
          onClick={() => void save()}
        >
          {busy ? "Saving…" : "Save chart"}
        </button>
      </div>
      {error !== null && (
        <p className="field-error file-view__error" role="alert">
          {error}
        </p>
      )}
      <ChartEditor
        spec={spec}
        data={parsed.value}
        notice={null}
        sources={null}
        onChange={(changes) => {
          setChosen({ ...spec, ...changes });
        }}
      />
    </div>
  );
}

/** A saved `.viz.json` drawn from its data file, its settings editing the file's text. */
export function ChartFile({
  spaceId,
  content,
  onContent,
  files,
}: {
  spaceId: string;
  content: string;
  onContent: (content: string) => void;
  files: readonly TextFileSummary[];
}) {
  const parsed = useMemo(() => attempt(() => parseVisualizationSpec(content)), [content]);
  const spec = "value" in parsed ? parsed.value : null;
  const source = spec?.source ?? "";
  const [loaded, setLoaded] = useState<{
    source: string;
    data: DataSet | null;
    error: string | null;
    waiting?: boolean;
  } | null>(null);
  useEffect(() => {
    if (source === "") return undefined;
    let live = true;
    void api
      .getFile(spaceId, source)
      .then((file) => parseDataFile(file.path, file.content))
      .then(
        (data) => {
          if (live) setLoaded({ source, data, error: null });
        },
        (failure: unknown) => {
          if (live) setLoaded({ source, data: null, error: message(failure), waiting: isMissing(failure) });
        },
      );
    return () => {
      live = false;
    };
  }, [spaceId, source]);

  if (spec === null) {
    return (
      <div className="file-view">
        <p className="file-view__note" role="alert">
          This file is not a chart AgentBase can draw: {"error" in parsed ? parsed.error : ""} Fix it under Text.
        </p>
      </div>
    );
  }

  const current = loaded?.source === source ? loaded : null;
  const notice =
    source === ""
      ? "Choose the data file this chart draws."
      : current === null
        ? "Reading the data…"
        : current.waiting === true
          ? noDataYet(source)
          : current.error !== null
            ? `${source} cannot be drawn: ${current.error}`
            : null;

  const changeSource = async (next: string) => {
    try {
      const file = await api.getFile(spaceId, next);
      const data = parseDataFile(file.path, file.content);
      const inferred = defaultVisualization(file.path, data);
      setLoaded({ source: next, data, error: null });
      // A chart that drew something keeps its kind; a new one takes the inferred kind.
      onContent(visualizationJson({ ...inferred, title: spec.title, chart: spec.source === "" ? inferred.chart : spec.chart }));
    } catch (failure) {
      setLoaded({ source: next, data: null, error: message(failure) });
      onContent(visualizationJson({ ...spec, source: next }));
    }
  };

  return (
    <div className="file-view">
      <ChartEditor
        spec={spec}
        data={current?.data ?? null}
        notice={notice}
        sources={files.filter((file) => fileKind(file.path) === "data").map((file) => file.path)}
        onChange={(changes) => {
          onContent(visualizationJson({ ...spec, ...changes }));
        }}
        onSource={(next) => void changeSource(next)}
      />
    </div>
  );
}

/** A saved `.dashboard.json` drawn with its charts, its settings editing the file's text. */
export function DashboardFile({
  spaceId,
  content,
  onContent,
  files,
}: {
  spaceId: string;
  content: string;
  onContent: (content: string) => void;
  files: readonly TextFileSummary[];
}) {
  const parsed = useMemo(() => attempt(() => parseDashboardSpec(content)), [content]);
  const spec = "value" in parsed ? parsed.value : null;
  const paths = (spec?.visualizations ?? []).join("\n");
  const [charts, setCharts] = useState<{ paths: string; charts: LoadedChart[] } | null>(null);
  useEffect(() => {
    let live = true;
    const wanted = paths === "" ? [] : paths.split("\n");
    void Promise.all(wanted.map((path) => loadChart(spaceId, path))).then((loaded) => {
      if (live) setCharts({ paths, charts: loaded });
    });
    return () => {
      live = false;
    };
  }, [spaceId, paths]);

  if (spec === null) {
    return (
      <div className="file-view">
        <p className="file-view__note" role="alert">
          This file is not a dashboard AgentBase can draw: {"error" in parsed ? parsed.error : ""} Fix it under Text.
        </p>
      </div>
    );
  }

  const change = (next: DashboardSpec) => {
    onContent(dashboardJson(next));
  };
  const saved = files.filter((file) => fileKind(file.path) === "chart").map((file) => file.path);
  // A chart the dashboard names but the folder lacks stays listed, so it can be unticked.
  const offered = [...saved, ...spec.visualizations.filter((path) => !saved.includes(path))];
  const shown = charts?.paths === paths ? charts.charts : null;

  return (
    <div className="file-view">
      <div className="dashboard-editor">
        <section className="dashboard-editor__controls" aria-label="Dashboard settings">
          <label>
            <span>Dashboard title</span>
            <input
              value={spec.title}
              onChange={(event) => {
                change({ ...spec, title: event.target.value });
              }}
            />
          </label>
          <label>
            <span>Columns</span>
            <select
              value={spec.columns}
              onChange={(event) => {
                change({ ...spec, columns: Number(event.target.value) as 1 | 2 | 3 });
              }}
            >
              <option value="1">1</option>
              <option value="2">2</option>
              <option value="3">3</option>
            </select>
          </label>
          <fieldset>
            <legend>Saved charts</legend>
            {offered.length === 0 ? (
              <p>Save a chart first: open a CSV or JSON file and choose Chart.</p>
            ) : (
              offered.map((path) => (
                <label key={path}>
                  <input
                    type="checkbox"
                    checked={spec.visualizations.includes(path)}
                    onChange={(event) => {
                      change({
                        ...spec,
                        visualizations: event.target.checked
                          ? [...spec.visualizations, path]
                          : spec.visualizations.filter((item) => item !== path),
                      });
                    }}
                  />
                  {path}
                </label>
              ))
            )}
          </fieldset>
        </section>
        <section className={`dashboard dashboard--${String(spec.columns)}`} aria-label={spec.title}>
          {spec.visualizations.length === 0 && <p className="file-view__note">Tick saved charts to show them here.</p>}
          {spec.visualizations.length > 0 && shown === null && <p className="file-view__note">Reading the charts…</p>}
          {shown?.map((chart) =>
            chart.spec !== null && chart.data !== null ? (
              <Chart key={chart.path} data={chart.data} spec={chart.spec} compact />
            ) : chart.waiting && chart.spec !== null ? (
              <div key={chart.path} className="file-view__note dashboard__waiting">
                <strong>{chart.spec.title}</strong> {noDataYet(chart.spec.source)}
              </div>
            ) : (
              <div key={chart.path} className="field-error">
                {chart.path}: {chart.error}
              </div>
            ),
          )}
        </section>
      </div>
    </div>
  );
}

/** A Mermaid file: its text beside the diagram it draws. */
export function DiagramFile({
  content,
  title,
  onContent,
}: {
  content: string;
  title: string;
  onContent: (content: string) => void;
}) {
  return (
    <div className="file-view">
      <div className="diagram-editor">
        <section className="diagram-editor__source">
          <label>
            <span>Mermaid source</span>
            <textarea
              aria-label="Mermaid source"
              spellCheck={false}
              value={content}
              onChange={(event) => {
                onContent(event.target.value);
              }}
            />
          </label>
          <p>Drawn with Mermaid's strict security. Scripts, HTML labels, external links and embedded objects are removed.</p>
        </section>
        <div className="diagram-editor__preview">
          <MermaidDiagram source={content} title={title} />
        </div>
      </div>
    </div>
  );
}

function ChartEditor({
  spec,
  data,
  notice,
  sources,
  onChange,
  onSource,
}: {
  spec: VisualizationSpec;
  data: DataSet | null;
  /** Why nothing is drawn yet, in place of the chart. */
  notice: string | null;
  /** The data files a saved chart may draw from; null for a chart of the open file. */
  sources: readonly string[] | null;
  onChange: (changes: Partial<VisualizationSpec>) => void;
  onSource?: (path: string) => void;
}) {
  const columns = data?.columns ?? [];
  const numbers = columns.filter((column) => column.kind === "number" || column.kind === "boolean");
  return (
    <div className="chart-editor">
      <section className="chart-editor__controls" aria-label="Chart settings">
        <label>
          <span>Title</span>
          <input
            value={spec.title}
            onChange={(event) => {
              onChange({ title: event.target.value });
            }}
          />
        </label>
        {sources !== null && (
          <label>
            <span>Data source</span>
            <select
              value={spec.source}
              onChange={(event) => {
                onSource?.(event.target.value);
              }}
            >
              {spec.source === "" && <option value="">Choose a data file…</option>}
              {spec.source !== "" && !sources.includes(spec.source) && <option value={spec.source}>{spec.source}</option>}
              {sources.map((path) => (
                <option key={path} value={path}>
                  {path}
                </option>
              ))}
            </select>
          </label>
        )}
        <label>
          <span>Chart</span>
          <select
            value={spec.chart}
            onChange={(event) => {
              onChange({ chart: event.target.value as ChartKind });
            }}
          >
            {["bar", "line", "area", "scatter", "pie", "metric", "table"].map((kind) => (
              <option key={kind} value={kind}>
                {kind}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>X / category</span>
          <select
            value={spec.x ?? ""}
            onChange={(event) => {
              onChange({ x: event.target.value || null });
            }}
          >
            <option value="">Row number</option>
            {columns.map((column) => (
              <option key={column.name}>{column.name}</option>
            ))}
          </select>
        </label>
        <fieldset className="chart-editor__values">
          <legend>Values</legend>
          {numbers.length === 0 ? (
            <span>No numeric columns</span>
          ) : (
            numbers.map((column) => (
              <label key={column.name}>
                <input
                  type="checkbox"
                  checked={spec.y.includes(column.name)}
                  onChange={(event) => {
                    onChange({
                      y: event.target.checked ? [...spec.y, column.name] : spec.y.filter((name) => name !== column.name),
                    });
                  }}
                />
                {column.name}
              </label>
            ))
          )}
        </fieldset>
        <label>
          <span>Series</span>
          <select
            value={spec.series ?? ""}
            onChange={(event) => {
              onChange({ series: event.target.value || null });
            }}
          >
            <option value="">One series per value</option>
            {columns.map((column) => (
              <option key={column.name}>{column.name}</option>
            ))}
          </select>
        </label>
        <label>
          <span>Aggregate</span>
          <select
            value={spec.aggregate}
            onChange={(event) => {
              onChange({ aggregate: event.target.value as Aggregate });
            }}
          >
            {["none", "sum", "average", "count", "minimum", "maximum"].map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label>
          <span>Sort</span>
          <select
            value={spec.sort}
            onChange={(event) => {
              onChange({ sort: event.target.value as SortOrder });
            }}
          >
            {["source", "x-ascending", "x-descending", "value-ascending", "value-descending"].map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label>
          <span>Row limit</span>
          <input
            type="number"
            min="1"
            max="2000"
            value={spec.limit}
            onChange={(event) => {
              onChange({ limit: Math.max(1, Math.min(2000, Number(event.target.value) || 1)) });
            }}
          />
        </label>
      </section>
      <div className="chart-editor__preview">
        {data !== null && notice === null ? <Chart data={data} spec={spec} /> : <p className="file-view__note">{notice}</p>}
      </div>
    </div>
  );
}

async function loadChart(spaceId: string, path: string): Promise<LoadedChart> {
  let spec: VisualizationSpec;
  try {
    spec = parseVisualizationSpec((await api.getFile(spaceId, path)).content);
  } catch (failure) {
    return { path, spec: null, data: null, error: message(failure), waiting: false };
  }
  try {
    const source = await api.getFile(spaceId, spec.source);
    return { path, spec, data: parseDataFile(source.path, source.content), error: null, waiting: false };
  } catch (failure) {
    return { path, spec, data: null, error: message(failure), waiting: isMissing(failure) };
  }
}

function attempt<T>(parse: () => T): { value: T } | { error: string } {
  try {
    return { value: parse() };
  } catch (failure) {
    return { error: message(failure) };
  }
}

function message(failure: unknown): string {
  return failure instanceof Error ? failure.message : String(failure);
}
