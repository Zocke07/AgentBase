import { useMemo, useRef, useState } from "react";

import { prepareChart, type DataSet, type Scalar, type VisualizationSpec } from "../lib/visualization";

/**
 * Dependency-free SVG charts for saved visualizations and dashboards. Each has
 * a readable table; export serializes SVG, not a window screenshot.
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
/** The widest a single bar is drawn, in view-box units. */
const MAX_BAR = 56;
/** Legend names show this many characters; the full name is the entry's tooltip. */
const LEGEND_LENGTH = 28;
const LEGEND_ROW = 18;
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
          <p>
            {spec.aggregate === "none"
              ? plural(prepared.rows.length, "row")
              : `${plural(prepared.rows.length, "group")} from ${plural(prepared.sourceRows, "row")} · ${spec.aggregate}`}{" "}
            · {spec.chart}
          </p>
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

      {prepared.repeated > 0 && spec.chart !== "table" && (
        <p className="viz-chart__note" role="note">
          {prepared.repeated === 1
            ? `1 row shares its ${spec.x ?? "category"} with an earlier row and is not drawn.`
            : `${String(prepared.repeated)} rows share their ${spec.x ?? "category"} with an earlier row and are not drawn.`}{" "}
          Choose an aggregate to combine them, or Show data to see every row.
        </p>
      )}

      {(tableOpen || spec.chart === "table") && <DataTable data={prepared.rows} columns={prepared.columns.map((column) => column.name)} />}
    </section>
  );
}

function CartesianChart({ spec, prepared }: { spec: VisualizationSpec; prepared: ReturnType<typeof prepareChart> }) {
  const values = prepared.series.flatMap((series) => series.points.map((point) => point.value));
  const scale = niceScale(Math.min(0, ...values), Math.max(0, ...values));
  const span = scale.high - scale.low;
  const y = (value: number) => TOP + ((scale.high - value) / span) * PLOT_HEIGHT;
  const zero = y(0);
  const labelStep = Math.max(1, Math.ceil(prepared.labels.length / 10));
  const categoryWidth = PLOT_WIDTH / Math.max(1, prepared.labels.length);
  // About 7px a character at the axis font: a label gets the room its slot has.
  const labelLength = Math.max(4, Math.min(32, Math.floor((categoryWidth * labelStep) / 7)));
  const pointFor = (seriesIndex: number, label: string) => prepared.series[seriesIndex]?.points.find((point) => point.label === label);
  const legend = prepared.series.length > 1 ? legendLayout(prepared.series.map((series) => series.name)) : [];
  const legendRows = legend.reduce((rows, item) => Math.max(rows, item.row + 1), 1);
  const height = HEIGHT + (legendRows - 1) * LEGEND_ROW;

  return (
    <svg className="viz-chart__svg" viewBox={`0 0 ${String(WIDTH)} ${String(height)}`} role="img" aria-label={`${spec.chart} chart: ${spec.title}`}>
      <title>{spec.title}</title>
      {scale.ticks.map((tick) => (
        <g key={tick}>
          <line className="viz-chart__grid" x1={LEFT} x2={WIDTH - RIGHT} y1={y(tick)} y2={y(tick)} />
          <text className="viz-chart__axis-label" x={LEFT - 9} y={y(tick) + 4} textAnchor="end">{shortNumber(tick)}</text>
        </g>
      ))}
      <line className="viz-chart__axis" x1={LEFT} x2={WIDTH - RIGHT} y1={zero} y2={zero} />
      {prepared.labels.map((label, index) => index % labelStep === 0 && (
        <g key={label}>
          <title>{label}</title>
          <text
            className="viz-chart__axis-label"
            x={LEFT + categoryWidth * (index + 0.5)}
            y={HEIGHT - BOTTOM + 22}
            textAnchor="middle"
          >
            {truncate(label, labelLength)}
          </text>
        </g>
      ))}

      {spec.chart === "bar" ? prepared.labels.flatMap((label, labelIndex) => {
        // A few categories would otherwise make each bar a slab a third of the chart wide.
        const group = Math.min(categoryWidth * 0.76, MAX_BAR * Math.max(1, prepared.series.length));
        const width = Math.max(1, group / Math.max(1, prepared.series.length));
        const start = LEFT + categoryWidth * labelIndex + (categoryWidth - group) / 2;
        return prepared.series.map((series, seriesIndex) => {
          const point = pointFor(seriesIndex, label);
          if (point === undefined) return null;
          const top = Math.min(zero, y(point.value));
          return (
            <rect
              key={`${series.name}:${label}`}
              className="viz-chart__mark"
              x={start + width * seriesIndex}
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

      {legend.map((item, index) => (
        <g key={item.name} transform={`translate(${String(LEFT + item.x)}, ${String(HEIGHT - 11 + item.row * LEGEND_ROW)})`}>
          <title>{item.name}</title>
          <rect width="10" height="10" y="-9" rx="2" fill={colour(index)} />
          <text className="viz-chart__legend" x="15">{truncate(item.name, LEGEND_LENGTH)}</text>
        </g>
      ))}
    </svg>
  );
}

/**
 * Axis bounds and ticks on round steps (1, 2, 2.5 or 5 times a power of ten),
 * so a 0 to 30 axis reads 0, 10, 20, 30 rather than quarters of the maximum.
 */
function niceScale(minimum: number, maximum: number): { low: number; high: number; ticks: number[] } {
  const rough = (maximum - minimum || Math.abs(maximum) || 1) / 4;
  const power = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((multiple) => multiple * power).find((candidate) => candidate >= rough) ?? 10 * power;
  const low = Math.floor(minimum / step) * step;
  const high = Math.max(Math.ceil(maximum / step) * step, low + step);
  const count = Math.round((high - low) / step);
  const ticks = Array.from({ length: count + 1 }, (_unused, index) => Number((high - step * index).toPrecision(12)));
  return { low, high, ticks };
}

/**
 * Legend entries laid left to right, each as wide as its name, starting a new
 * row rather than cutting names to fit a fixed slot.
 */
function legendLayout(names: string[]): { name: string; x: number; row: number }[] {
  let x = 0;
  let row = 0;
  return names.map((name) => {
    const width = 15 + Math.min(name.length, LEGEND_LENGTH) * 6.6 + 22;
    if (x > 0 && x + width > PLOT_WIDTH) {
      x = 0;
      row += 1;
    }
    const item = { name, x, row };
    x += width;
    return item;
  });
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

function plural(count: number, noun: string): string {
  return `${String(count)} ${noun}${count === 1 ? "" : "s"}`;
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
