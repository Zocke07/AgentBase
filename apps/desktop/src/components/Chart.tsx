import { useMemo, useRef, useState } from "react";

import { prepareChart, type DataSet, type Scalar, type VisualizationSpec } from "../lib/visualization";

/**
 * Dependency-free SVG charts for saved visualizations and dashboards. The
 * same figure always carries a readable table, and export serializes only the
 * SVG we drew rather than taking a screenshot of the window.
 */

export interface ChartProps {
  data: DataSet;
  spec: VisualizationSpec;
  compact?: boolean;
}

const WIDTH = 800;
const HEIGHT = 360;
const LEFT = 64;
const RIGHT = 24;
const TOP = 26;
const BOTTOM = 58;
const PLOT_WIDTH = WIDTH - LEFT - RIGHT;
const PLOT_HEIGHT = HEIGHT - TOP - BOTTOM;
const COLOURS = [
  "var(--viz-1)",
  "var(--viz-2)",
  "var(--viz-3)",
  "var(--viz-4)",
  "var(--viz-5)",
  "var(--viz-6)",
] as const;

export function Chart({ data, spec, compact = false }: ChartProps) {
  const prepared = useMemo(() => prepareChart(data, spec), [data, spec]);
  const figure = useRef<HTMLDivElement>(null);
  const [tableOpen, setTableOpen] = useState(spec.chart === "table");
  const empty = prepared.rows.length === 0;
  const hasValues = prepared.series.some((series) => series.points.length > 0);

  return (
    <section className={`viz-chart${compact ? " viz-chart--compact" : ""}`} aria-label={spec.title}>
      <div className="viz-chart__head">
        <div>
          <h3>{spec.title || "Untitled visualization"}</h3>
          <p>{prepared.rows.length} row{prepared.rows.length === 1 ? "" : "s"} · {spec.chart}</p>
        </div>
        <div className="viz-chart__actions">
          <button
            type="button"
            className="button button--small"
            aria-pressed={tableOpen}
            onClick={() => { setTableOpen((open) => !open); }}
          >
            {tableOpen ? "Hide data" : "Show data"}
          </button>
          {spec.chart !== "table" && (
            <button
              type="button"
              className="button button--small"
              disabled={empty || !hasValues}
              onClick={() => { exportSvg(figure.current?.querySelector("svg") ?? null, spec.title); }}
            >
              Export SVG
            </button>
          )}
          <button type="button" className="button button--small" disabled={empty} onClick={() => { exportCsv(prepared.rows, spec.title); }}>
            Export CSV
          </button>
        </div>
      </div>

      <div className="viz-chart__figure" ref={figure}>
        {empty ? (
          <p className="viz-chart__empty">The source has no rows to visualize.</p>
        ) : spec.chart === "table" ? null : !hasValues ? (
          <p className="viz-chart__empty">Choose at least one numeric value column.</p>
        ) : spec.chart === "pie" ? (
          <PieChart spec={spec} prepared={prepared} />
        ) : spec.chart === "metric" ? (
          <MetricChart spec={spec} prepared={prepared} />
        ) : (
          <CartesianChart spec={spec} prepared={prepared} />
        )}
      </div>

      {(tableOpen || spec.chart === "table") && <DataTable data={prepared.rows} columns={prepared.columns.map((column) => column.name)} />}
    </section>
  );
}

function CartesianChart({ spec, prepared }: { spec: VisualizationSpec; prepared: ReturnType<typeof prepareChart> }) {
  const values = prepared.series.flatMap((series) => series.points.map((point) => point.value));
  const minimum = Math.min(0, ...values);
  const maximum = Math.max(0, ...values);
  const span = maximum - minimum || 1;
  const y = (value: number) => TOP + ((maximum - value) / span) * PLOT_HEIGHT;
  const zero = y(0);
  const labelStep = Math.max(1, Math.ceil(prepared.labels.length / 10));
  const categoryWidth = PLOT_WIDTH / Math.max(1, prepared.labels.length);
  const pointFor = (seriesIndex: number, label: string) => prepared.series[seriesIndex]?.points.find((point) => point.label === label);
  const ticks = Array.from({ length: 5 }, (_unused, index) => maximum - (span * index) / 4);

  return (
    <svg className="viz-chart__svg" viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`} role="img" aria-label={`${spec.chart} chart: ${spec.title}`}>
      <title>{spec.title}</title>
      {ticks.map((tick) => (
        <g key={tick}>
          <line className="viz-chart__grid" x1={LEFT} x2={WIDTH - RIGHT} y1={y(tick)} y2={y(tick)} />
          <text className="viz-chart__axis-label" x={LEFT - 9} y={y(tick) + 4} textAnchor="end">{shortNumber(tick)}</text>
        </g>
      ))}
      <line className="viz-chart__axis" x1={LEFT} x2={WIDTH - RIGHT} y1={zero} y2={zero} />
      {prepared.labels.map((label, index) => index % labelStep === 0 && (
        <text
          key={label}
          className="viz-chart__axis-label"
          x={LEFT + categoryWidth * (index + 0.5)}
          y={HEIGHT - BOTTOM + 22}
          textAnchor="middle"
        >
          {truncate(label, 14)}
        </text>
      ))}

      {spec.chart === "bar" ? prepared.labels.flatMap((label, labelIndex) => {
        const width = Math.max(1, (categoryWidth * 0.76) / Math.max(1, prepared.series.length));
        return prepared.series.map((series, seriesIndex) => {
          const point = pointFor(seriesIndex, label);
          if (point === undefined) return null;
          const top = Math.min(zero, y(point.value));
          return (
            <rect
              key={`${series.name}:${label}`}
              className="viz-chart__mark"
              x={LEFT + categoryWidth * labelIndex + categoryWidth * 0.12 + width * seriesIndex}
              y={top}
              width={Math.max(1, width - 2)}
              height={Math.max(1, Math.abs(zero - y(point.value)))}
              fill={colour(seriesIndex)}
            >
              <title>{label} · {series.name}: {formatNumber(point.value)}</title>
            </rect>
          );
        });
      }) : prepared.series.map((series, seriesIndex) => {
        const points = prepared.labels.flatMap((label, labelIndex) => {
          const point = pointFor(seriesIndex, label);
          return point === undefined ? [] : [{ ...point, x: LEFT + categoryWidth * (labelIndex + 0.5), y: y(point.value) }];
        });
        const line = points.map((point, index) => `${index === 0 ? "M" : "L"}${String(point.x)},${String(point.y)}`).join(" ");
        const area = points.length === 0 ? "" : `${line} L${String(points.at(-1)?.x ?? LEFT)},${String(zero)} L${String(points[0]?.x ?? LEFT)},${String(zero)} Z`;
        return (
          <g key={series.name}>
            {spec.chart === "area" && <path d={area} fill={colour(seriesIndex)} opacity="0.18" />}
            {spec.chart !== "scatter" && <path className="viz-chart__line" d={line} stroke={colour(seriesIndex)} />}
            {points.map((point) => (
              <circle key={`${series.name}:${point.label}`} className="viz-chart__point" cx={point.x} cy={point.y} r={spec.chart === "scatter" ? 5 : 3.5} fill={colour(seriesIndex)}>
                <title>{point.label} · {series.name}: {formatNumber(point.value)}</title>
              </circle>
            ))}
          </g>
        );
      })}

      {prepared.series.length > 1 && prepared.series.map((series, index) => (
        <g key={series.name} transform={`translate(${String(LEFT + index * 132)}, ${String(HEIGHT - 11)})`}>
          <rect width="10" height="10" y="-9" rx="2" fill={colour(index)} />
          <text className="viz-chart__legend" x="15">{truncate(series.name, 16)}</text>
        </g>
      ))}
    </svg>
  );
}

function PieChart({ spec, prepared }: { spec: VisualizationSpec; prepared: ReturnType<typeof prepareChart> }) {
  const points = (prepared.series[0]?.points ?? []).filter((point) => point.value > 0);
  const total = points.reduce((sum, point) => sum + point.value, 0);
  let angle = -Math.PI / 2;
  const centreX = 255;
  const centreY = 178;
  const radius = 124;
  return (
    <svg className="viz-chart__svg" viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`} role="img" aria-label={`pie chart: ${spec.title}`}>
      <title>{spec.title}</title>
      {total <= 0 ? <text className="viz-chart__empty-svg" x={WIDTH / 2} y={HEIGHT / 2} textAnchor="middle">Pie values must be greater than zero.</text> : points.length === 1 ? (
        <circle cx={centreX} cy={centreY} r={radius} fill={colour(0)} className="viz-chart__mark">
          <title>{points[0]?.label}: {formatNumber(points[0]?.value ?? 0)} (100%)</title>
        </circle>
      ) : points.map((point, index) => {
        const start = angle;
        const sweep = (point.value / total) * Math.PI * 2;
        angle += sweep;
        return (
          <path key={point.label} d={arcPath(centreX, centreY, radius, start, angle)} fill={colour(index)} className="viz-chart__mark">
            <title>{point.label}: {formatNumber(point.value)} ({String(Math.round((point.value / total) * 100))}%)</title>
          </path>
        );
      })}
      {points.slice(0, 12).map((point, index) => (
        <g key={`legend:${point.label}`} transform={`translate(440, ${String(44 + index * 23)})`}>
          <rect width="11" height="11" y="-9" rx="2" fill={colour(index)} />
          <text className="viz-chart__legend" x="17">{truncate(point.label, 22)} · {shortNumber(point.value)}</text>
        </g>
      ))}
    </svg>
  );
}

function MetricChart({ spec, prepared }: { spec: VisualizationSpec; prepared: ReturnType<typeof prepareChart> }) {
  const series = prepared.series[0];
  const values = series?.points.map((point) => point.value) ?? [];
  const value = spec.aggregate === "none" ? (values.at(-1) ?? 0) : (values[0] ?? 0);
  const previous = spec.aggregate === "none" && values.length > 1 ? values.at(-2) ?? null : null;
  const change = previous === null || previous === 0 ? null : ((value - previous) / Math.abs(previous)) * 100;
  return (
    <svg className="viz-chart__svg viz-chart__svg--metric" viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`} role="img" aria-label={`metric: ${spec.title}, ${formatNumber(value)}`}>
      <title>{spec.title}: {formatNumber(value)}</title>
      <text className="viz-chart__metric-value" x={WIDTH / 2} y={HEIGHT / 2} textAnchor="middle">{shortNumber(value)}</text>
      <text className="viz-chart__metric-label" x={WIDTH / 2} y={HEIGHT / 2 + 42} textAnchor="middle">{series?.name ?? "Value"}</text>
      {change !== null && <text className={`viz-chart__metric-change${change < 0 ? " viz-chart__metric-change--down" : ""}`} x={WIDTH / 2} y={HEIGHT / 2 + 76} textAnchor="middle">{change >= 0 ? "+" : ""}{change.toFixed(1)}% from previous</text>}
    </svg>
  );
}

function DataTable({ data, columns }: { data: Record<string, Scalar>[]; columns: string[] }) {
  return (
    <div className="viz-table" tabIndex={0}>
      <table>
        <thead><tr>{columns.map((column) => <th key={column} scope="col">{column}</th>)}</tr></thead>
        <tbody>{data.slice(0, 500).map((row, index) => (
          <tr key={index}>{columns.map((column) => <td key={column}>{display(row[column] ?? null)}</td>)}</tr>
        ))}</tbody>
      </table>
      {data.length > 500 && <p>Showing the first 500 of {data.length} rows.</p>}
    </div>
  );
}

function exportSvg(svg: SVGSVGElement | null, title: string): void {
  if (svg === null) return;
  const copy = svg.cloneNode(true) as SVGSVGElement;
  copy.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  copy.querySelectorAll<SVGElement>("*").forEach((element) => {
    const style = getComputedStyle(element);
    if (style.fill !== "") element.style.fill = style.fill;
    if (style.stroke !== "") element.style.stroke = style.stroke;
    if (style.color !== "") element.style.color = style.color;
    if (style.font !== "") element.style.font = style.font;
  });
  download(new Blob([new XMLSerializer().serializeToString(copy)], { type: "image/svg+xml;charset=utf-8" }), `${slug(title)}.svg`);
}

function exportCsv(rows: Record<string, Scalar>[], title: string): void {
  const columns = unique(rows.flatMap((row) => Object.keys(row)));
  const csv = [columns, ...rows.map((row) => columns.map((column) => display(row[column] ?? null)))]
    .map((row) => row.map(csvCell).join(","))
    .join("\n");
  download(new Blob([`${csv}\n`], { type: "text/csv;charset=utf-8" }), `${slug(title)}.csv`);
}

function download(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function arcPath(cx: number, cy: number, radius: number, start: number, end: number): string {
  const first = { x: cx + radius * Math.cos(start), y: cy + radius * Math.sin(start) };
  const last = { x: cx + radius * Math.cos(end), y: cy + radius * Math.sin(end) };
  return `M${String(cx)},${String(cy)} L${String(first.x)},${String(first.y)} A${String(radius)},${String(radius)} 0 ${end - start > Math.PI ? "1" : "0"},1 ${String(last.x)},${String(last.y)} Z`;
}

function csvCell(value: string): string {
  return /[",\r\n]/.test(value) ? `"${value.replaceAll('"', '""')}"` : value;
}

function display(value: Scalar): string {
  if (value === null) return "";
  return typeof value === "number" ? formatNumber(value) : String(value);
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 4 }).format(value);
}

function shortNumber(value: number): string {
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 2 }).format(value);
}

function colour(index: number): string {
  return COLOURS[index % COLOURS.length] ?? COLOURS[0];
}

function truncate(value: string, length: number): string {
  return value.length <= length ? value : `${value.slice(0, length - 1)}…`;
}

function slug(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "visualization";
}

function unique<T>(values: T[]): T[] {
  return [...new Set(values)];
}
