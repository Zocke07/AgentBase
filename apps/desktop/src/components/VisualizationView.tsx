import type { SpaceResponse, TextFileSummary } from "@agentbase/schemas";
import { useCallback, useEffect, useMemo, useState } from "react";

import * as api from "../lib/api";
import {
  DASHBOARD_SCHEMA,
  VISUALIZATION_SCHEMA,
  dashboardJson,
  defaultVisualization,
  parseDashboardSpec,
  parseDataFile,
  parseVisualizationSpec,
  visualizationJson,
  type Aggregate,
  type ChartKind,
  type DashboardSpec,
  type DataSet,
  type SortOrder,
  type VisualizationSpec,
} from "../lib/visualization";

import { Chart } from "./Chart";
import { MermaidDiagram } from "./MermaidDiagram";

type Artifact = ChartArtifact | DashboardArtifact | DiagramArtifact;
interface ChartArtifact { kind: "chart"; spec: VisualizationSpec; data: DataSet; path: string | null }
interface DashboardArtifact { kind: "dashboard"; spec: DashboardSpec; charts: LoadedChart[]; path: string | null }
interface DiagramArtifact { kind: "diagram"; source: string; path: string | null; title: string }
interface LoadedChart { path: string; spec: VisualizationSpec; data: DataSet; error: string | null }

const DATA_SUFFIXES = [".csv", ".tsv", ".json", ".jsonl", ".ndjson"] as const;
const EMPTY_FILES: TextFileSummary[] = [];

export function VisualizationView({ space, active }: { space: SpaceResponse | null; active: boolean }) {
  const [files, setFiles] = useState<TextFileSummary[]>(EMPTY_FILES);
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (space === null) return;
    try {
      setFiles((await api.listFiles(space.id)).files);
    } catch (failure) {
      setError(message(failure));
    }
  }, [space]);

  useEffect(() => {
    if (!active || space === null) return undefined;
    let live = true;
    void api.listFiles(space.id).then((result) => {
      if (live) setFiles(result.files);
    }).catch((failure: unknown) => {
      if (live) setError(message(failure));
    });
    return () => { live = false; };
  }, [active, space]);

  const dataFiles = useMemo(() => files.filter((file) => dataPath(file.path)), [files]);
  const visualizations = useMemo(() => files.filter((file) => file.path.toLowerCase().endsWith(".viz.json")), [files]);
  const dashboards = useMemo(() => files.filter((file) => file.path.toLowerCase().endsWith(".dashboard.json")), [files]);
  const diagrams = useMemo(() => files.filter((file) => diagramPath(file.path)), [files]);

  const loadChart = useCallback(async (spaceId: string, specPath: string): Promise<LoadedChart> => {
    try {
      const spec = parseVisualizationSpec((await api.getFile(spaceId, specPath)).content);
      const source = await api.getFile(spaceId, spec.source);
      return { path: specPath, spec, data: parseDataFile(source.path, source.content), error: null };
    } catch (failure) {
      return {
        path: specPath,
        spec: blankVisualization("Missing source"),
        data: { columns: [], rows: [] },
        error: message(failure),
      };
    }
  }, []);

  const open = useCallback(async (wanted: string) => {
    if (space === null) return;
    setBusy(true);
    setError(null);
    try {
      const lower = wanted.toLowerCase();
      if (lower.endsWith(".viz.json")) {
        const loaded = await loadChart(space.id, wanted);
        if (loaded.error !== null) throw new Error(loaded.error);
        setArtifact({ kind: "chart", spec: loaded.spec, data: loaded.data, path: wanted });
        setPath(wanted);
      } else if (lower.endsWith(".dashboard.json")) {
        const spec = parseDashboardSpec((await api.getFile(space.id, wanted)).content);
        const charts = await Promise.all(spec.visualizations.map((chartPath) => loadChart(space.id, chartPath)));
        setArtifact({ kind: "dashboard", spec, charts, path: wanted });
        setPath(wanted);
      } else if (diagramPath(wanted)) {
        const file = await api.getFile(space.id, wanted);
        setArtifact({ kind: "diagram", source: file.content, path: wanted, title: stem(wanted) });
        setPath(wanted);
      } else {
        const file = await api.getFile(space.id, wanted);
        const data = parseDataFile(file.path, file.content);
        const spec = defaultVisualization(file.path, data);
        setArtifact({ kind: "chart", spec, data, path: null });
        setPath(`visualizations/${slug(spec.title)}.viz.json`);
      }
    } catch (failure) {
      setError(message(failure));
    } finally {
      setBusy(false);
    }
  }, [loadChart, space]);

  const newChart = async () => {
    const first = dataFiles[0];
    if (first === undefined) {
      setError("Add a CSV, TSV, JSON or JSON-lines file under Knowledge → Data files first.");
      return;
    }
    await open(first.path);
  };

  const newDashboard = () => {
    const spec: DashboardSpec = { $schema: DASHBOARD_SCHEMA, title: "Dashboard", visualizations: [], columns: 2 };
    setArtifact({ kind: "dashboard", spec, charts: [], path: null });
    setPath("visualizations/dashboard.dashboard.json");
    setError(null);
  };

  const newDiagram = () => {
    setArtifact({
      kind: "diagram",
      title: "Agent workflow",
      path: null,
      source: "flowchart LR\n  Goal --> Supervisor\n  Supervisor --> Researcher\n  Researcher --> Supervisor\n  Supervisor --> Outcome\n",
    });
    setPath("visualizations/agent-workflow.mmd");
    setError(null);
  };

  const save = async () => {
    if (space === null || artifact === null) return;
    const wanted = path.trim();
    if (wanted === "") {
      setError("Give this visualization a path inside the space.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (artifact.kind === "chart") {
        if (!wanted.toLowerCase().endsWith(".viz.json")) throw new Error("A saved chart path must end in .viz.json.");
        await api.writeFile(space.id, wanted, visualizationJson(artifact.spec));
        setArtifact({ ...artifact, path: wanted });
      } else if (artifact.kind === "dashboard") {
        if (!wanted.toLowerCase().endsWith(".dashboard.json")) throw new Error("A dashboard path must end in .dashboard.json.");
        await api.writeFile(space.id, wanted, dashboardJson(artifact.spec));
        setArtifact({ ...artifact, path: wanted });
      } else {
        if (!diagramPath(wanted)) throw new Error("A diagram path must end in .mmd or .mermaid.");
        await api.writeFile(space.id, wanted, artifact.source);
        setArtifact({ ...artifact, path: wanted });
      }
      await reload();
    } catch (failure) {
      setError(message(failure));
    } finally {
      setBusy(false);
    }
  };

  const changeSource = async (source: string) => {
    if (space === null || artifact?.kind !== "chart") return;
    setBusy(true);
    setError(null);
    try {
      const file = await api.getFile(space.id, source);
      const data = parseDataFile(file.path, file.content);
      const inferred = defaultVisualization(file.path, data);
      setArtifact({
        ...artifact,
        data,
        spec: { ...inferred, title: artifact.spec.title, chart: artifact.spec.chart },
      });
    } catch (failure) {
      setError(message(failure));
    } finally {
      setBusy(false);
    }
  };

  const changeDashboardCharts = async (selected: string[]) => {
    if (space === null || artifact?.kind !== "dashboard") return;
    const spec = { ...artifact.spec, visualizations: selected };
    setArtifact({ ...artifact, spec, charts: await Promise.all(selected.map((item) => loadChart(space.id, item))) });
  };

  return (
    <div className="visualize">
      <aside className="visualize__browser">
        <div className="visualize__browser-head">
          <strong>Visualizations</strong>
          <button type="button" className="button button--small" onClick={() => void reload()}>Refresh</button>
        </div>
        <ArtifactGroup title="Charts" files={visualizations} current={artifact?.kind === "chart" ? artifact.path : null} onOpen={open} />
        <ArtifactGroup title="Dashboards" files={dashboards} current={artifact?.kind === "dashboard" ? artifact.path : null} onOpen={open} />
        <ArtifactGroup title="Diagrams" files={diagrams} current={artifact?.kind === "diagram" ? artifact.path : null} onOpen={open} />
        <ArtifactGroup title="Data sources" files={dataFiles} current={artifact?.kind === "chart" ? artifact.spec.source : null} onOpen={open} />
        {files.length === 0 && <p className="visualize__empty">No visualizable files in this space yet.</p>}
      </aside>

      <section className="visualize__workspace">
        <div className="visualize__toolbar">
          <button type="button" className="button" onClick={() => void newChart()}>New chart</button>
          <button type="button" className="button" onClick={newDashboard}>New dashboard</button>
          <button type="button" className="button" onClick={newDiagram}>New diagram</button>
          {artifact !== null && (
            <>
              <label className="visualize__path"><span>Save as</span><input aria-label="Visualization path" value={path} onChange={(event) => { setPath(event.target.value); }} /></label>
              <button type="button" className="button button--primary" disabled={busy} onClick={() => void save()}>{busy ? "Saving…" : "Save"}</button>
            </>
          )}
        </div>
        {error !== null && <p className="field-error visualize__error" role="alert">{error}</p>}
        {busy && artifact === null && <p className="visualize__welcome">Loading visualization…</p>}
        {artifact === null && !busy && (
          <div className="visualize__welcome">
            <h2>Turn agent data into evidence you can see</h2>
            <p>Create a chart from CSV or JSON, compose saved charts into a dashboard, or render a Mermaid diagram. Saved definitions are ordinary files that agents can create and update through the same approval gate as other writes.</p>
            <code>{VISUALIZATION_SCHEMA}</code>
          </div>
        )}
        {artifact?.kind === "chart" && (
          <ChartEditor
            artifact={artifact}
            dataFiles={dataFiles}
            onChange={(next) => { setArtifact(next); }}
            onSource={(source) => void changeSource(source)}
          />
        )}
        {artifact?.kind === "dashboard" && (
          <DashboardEditor
            artifact={artifact}
            visualizations={visualizations}
            onChange={(spec) => { setArtifact({ ...artifact, spec }); }}
            onCharts={(selected) => void changeDashboardCharts(selected)}
          />
        )}
        {artifact?.kind === "diagram" && (
          <DiagramEditor artifact={artifact} onChange={(next) => { setArtifact(next); }} />
        )}
      </section>
    </div>
  );
}

function ChartEditor({ artifact, dataFiles, onChange, onSource }: { artifact: ChartArtifact; dataFiles: TextFileSummary[]; onChange: (artifact: ChartArtifact) => void; onSource: (path: string) => void }) {
  const { spec, data } = artifact;
  const numbers = data.columns.filter((column) => column.kind === "number" || column.kind === "boolean");
  const update = (changes: Partial<VisualizationSpec>) => { onChange({ ...artifact, spec: { ...spec, ...changes } }); };
  return (
    <div className="visualize__editor">
      <section className="visualize__controls" aria-label="Chart settings">
        <label><span>Title</span><input value={spec.title} onChange={(event) => { update({ title: event.target.value }); }} /></label>
        <label><span>Data source</span><select value={spec.source} onChange={(event) => { onSource(event.target.value); }}>{dataFiles.map((file) => <option key={file.path}>{file.path}</option>)}</select></label>
        <label><span>Chart</span><select value={spec.chart} onChange={(event) => { update({ chart: event.target.value as ChartKind }); }}>{["bar", "line", "area", "scatter", "pie", "metric", "table"].map((kind) => <option key={kind} value={kind}>{kind}</option>)}</select></label>
        <label><span>X / category</span><select value={spec.x ?? ""} onChange={(event) => { update({ x: event.target.value || null }); }}><option value="">Row number</option>{data.columns.map((column) => <option key={column.name}>{column.name}</option>)}</select></label>
        <fieldset className="visualize__values"><legend>Values</legend>{numbers.length === 0 ? <span>No numeric columns</span> : numbers.map((column) => <label key={column.name}><input type="checkbox" checked={spec.y.includes(column.name)} onChange={(event) => { update({ y: event.target.checked ? [...spec.y, column.name] : spec.y.filter((name) => name !== column.name) }); }} />{column.name}</label>)}</fieldset>
        <label><span>Series</span><select value={spec.series ?? ""} onChange={(event) => { update({ series: event.target.value || null }); }}><option value="">One series per value</option>{data.columns.map((column) => <option key={column.name}>{column.name}</option>)}</select></label>
        <label><span>Aggregate</span><select value={spec.aggregate} onChange={(event) => { update({ aggregate: event.target.value as Aggregate }); }}>{["none", "sum", "average", "count", "minimum", "maximum"].map((value) => <option key={value}>{value}</option>)}</select></label>
        <label><span>Sort</span><select value={spec.sort} onChange={(event) => { update({ sort: event.target.value as SortOrder }); }}>{["source", "x-ascending", "x-descending", "value-ascending", "value-descending"].map((value) => <option key={value}>{value}</option>)}</select></label>
        <label><span>Row limit</span><input type="number" min="1" max="2000" value={spec.limit} onChange={(event) => { update({ limit: Math.max(1, Math.min(2000, Number(event.target.value) || 1)) }); }} /></label>
      </section>
      <div className="visualize__preview"><Chart data={data} spec={spec} /></div>
    </div>
  );
}

function DashboardEditor({ artifact, visualizations, onChange, onCharts }: { artifact: DashboardArtifact; visualizations: TextFileSummary[]; onChange: (spec: DashboardSpec) => void; onCharts: (paths: string[]) => void }) {
  return (
    <div className="dashboard-editor">
      <section className="dashboard-editor__controls">
        <label><span>Dashboard title</span><input value={artifact.spec.title} onChange={(event) => { onChange({ ...artifact.spec, title: event.target.value }); }} /></label>
        <label><span>Columns</span><select value={artifact.spec.columns} onChange={(event) => { onChange({ ...artifact.spec, columns: Number(event.target.value) as 1 | 2 | 3 }); }}><option value="1">1</option><option value="2">2</option><option value="3">3</option></select></label>
        <fieldset><legend>Saved charts</legend>{visualizations.length === 0 ? <p>Save a chart first.</p> : visualizations.map((file) => <label key={file.path}><input type="checkbox" checked={artifact.spec.visualizations.includes(file.path)} onChange={(event) => { const selected = event.target.checked ? [...artifact.spec.visualizations, file.path] : artifact.spec.visualizations.filter((path) => path !== file.path); onCharts(selected); }} />{file.path}</label>)}</fieldset>
      </section>
      <section className={`dashboard dashboard--${String(artifact.spec.columns)}`} aria-label={artifact.spec.title}>
        {artifact.charts.length === 0 && <p className="visualize__welcome">Choose saved charts to compose this dashboard.</p>}
        {artifact.charts.map((chart) => chart.error === null ? <Chart key={chart.path} data={chart.data} spec={chart.spec} compact /> : <div key={chart.path} className="field-error">{chart.path}: {chart.error}</div>)}
      </section>
    </div>
  );
}

function DiagramEditor({ artifact, onChange }: { artifact: DiagramArtifact; onChange: (artifact: DiagramArtifact) => void }) {
  return (
    <div className="diagram-editor">
      <section className="diagram-editor__source">
        <label><span>Title</span><input value={artifact.title} onChange={(event) => { onChange({ ...artifact, title: event.target.value }); }} /></label>
        <label><span>Mermaid source</span><textarea aria-label="Mermaid source" spellCheck={false} value={artifact.source} onChange={(event) => { onChange({ ...artifact, source: event.target.value }); }} /></label>
        <p>Rendered with Mermaid strict security. Scripts, HTML labels, external links and embedded objects are removed.</p>
      </section>
      <div className="diagram-editor__preview"><MermaidDiagram source={artifact.source} title={artifact.title} /></div>
    </div>
  );
}

function ArtifactGroup({ title, files, current, onOpen }: { title: string; files: TextFileSummary[]; current: string | null; onOpen: (path: string) => Promise<void> }) {
  if (files.length === 0) return null;
  return <section className="visualize__group"><h3>{title}</h3><ul>{files.map((file) => <li key={file.path}><button type="button" aria-current={current === file.path ? "true" : undefined} className={current === file.path ? "visualize__item visualize__item--active" : "visualize__item"} onClick={() => void onOpen(file.path)}>{file.path}</button></li>)}</ul></section>;
}

function dataPath(path: string): boolean {
  const lower = path.toLowerCase();
  return DATA_SUFFIXES.some((suffix) => lower.endsWith(suffix)) && !lower.endsWith(".viz.json") && !lower.endsWith(".dashboard.json");
}

function diagramPath(path: string): boolean {
  const lower = path.toLowerCase();
  return lower.endsWith(".mmd") || lower.endsWith(".mermaid");
}

function blankVisualization(title: string): VisualizationSpec {
  return { $schema: VISUALIZATION_SCHEMA, title, source: "", chart: "table", x: null, y: [], series: null, aggregate: "none", sort: "source", limit: 250 };
}

function stem(path: string): string {
  return path.split("/").at(-1)?.replace(/\.(?:mmd|mermaid)$/i, "") ?? "Diagram";
}

function slug(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "chart";
}

function message(failure: unknown): string {
  return failure instanceof Error ? failure.message : String(failure);
}
