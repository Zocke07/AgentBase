/**
 * Portable visualization JSON shared by agents and people; source data remains
 * CSV, TSV, JSON, or JSON-lines. Pure parsing and chart preparation keep editor,
 * dashboards, and tests consistent.
 */

export type Scalar = string | number | boolean | null;
export type DataRow = Record<string, Scalar>;
export type ColumnKind = "number" | "date" | "boolean" | "text";

export interface DataColumn {
  name: string;
  kind: ColumnKind;
}

export interface DataSet {
  columns: DataColumn[];
  rows: DataRow[];
}

export type ChartKind = "bar" | "line" | "area" | "scatter" | "pie" | "metric" | "table";
export type Aggregate = "none" | "sum" | "average" | "count" | "minimum" | "maximum";
export type SortOrder = "source" | "x-ascending" | "x-descending" | "value-ascending" | "value-descending";

export const VISUALIZATION_SCHEMA = "agentbase://visualization/v1" as const;
export const DASHBOARD_SCHEMA = "agentbase://dashboard/v1" as const;
const LEGACY_VISUALIZATION_SCHEMA = "agentspace://visualization/v1" as const;
const LEGACY_DASHBOARD_SCHEMA = "agentspace://dashboard/v1" as const;

export interface VisualizationSpec {
  $schema: typeof VISUALIZATION_SCHEMA;
  title: string;
  source: string;
  chart: ChartKind;
  x: string | null;
  y: string[];
  series: string | null;
  aggregate: Aggregate;
  sort: SortOrder;
  limit: number;
}

export interface DashboardSpec {
  $schema: typeof DASHBOARD_SCHEMA;
  title: string;
  visualizations: string[];
  columns: 1 | 2 | 3;
}

type SavedVisualizationSpec = Omit<VisualizationSpec, "$schema"> & {
  $schema: typeof VISUALIZATION_SCHEMA | typeof LEGACY_VISUALIZATION_SCHEMA;
};

type SavedDashboardSpec = Omit<DashboardSpec, "$schema"> & {
  $schema: typeof DASHBOARD_SCHEMA | typeof LEGACY_DASHBOARD_SCHEMA;
};

export interface ChartPoint {
  label: string;
  value: number;
  row: DataRow;
}

export interface ChartSeries {
  name: string;
  points: ChartPoint[];
}

export interface PreparedChart {
  labels: string[];
  series: ChartSeries[];
  rows: DataRow[];
  columns: DataColumn[];
  /** Source rows the chart was drawn from, before any aggregate. */
  sourceRows: number;
  /**
   * Rows not drawn because an earlier row in the same series has the same
   * category. Only a chart without an aggregate leaves rows out this way.
   */
  repeated: number;
}

const DATA_LIMIT = 10_000;
const CHART_LIMIT = 2_000;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}(?:[T ][0-9:.+-Z]+)?$/;

export function isVisualizationSpec(value: unknown): value is VisualizationSpec {
  return isSavedVisualizationSpec(value) && value.$schema === VISUALIZATION_SCHEMA;
}

function isSavedVisualizationSpec(value: unknown): value is SavedVisualizationSpec {
  if (!isRecord(value) || !isVisualizationSchema(value.$schema)) return false;
  return (
    typeof value.title === "string" &&
    typeof value.source === "string" &&
    isChartKind(value.chart) &&
    (typeof value.x === "string" || value.x === null) &&
    Array.isArray(value.y) &&
    value.y.every((field) => typeof field === "string") &&
    (typeof value.series === "string" || value.series === null) &&
    isAggregate(value.aggregate) &&
    isSortOrder(value.sort) &&
    typeof value.limit === "number" &&
    Number.isInteger(value.limit) &&
    value.limit > 0 &&
    value.limit <= CHART_LIMIT
  );
}

export function isDashboardSpec(value: unknown): value is DashboardSpec {
  return isSavedDashboardSpec(value) && value.$schema === DASHBOARD_SCHEMA;
}

function isSavedDashboardSpec(value: unknown): value is SavedDashboardSpec {
  if (!isRecord(value) || !isDashboardSchema(value.$schema)) return false;
  return (
    typeof value.title === "string" &&
    Array.isArray(value.visualizations) &&
    value.visualizations.every((path) => typeof path === "string") &&
    (value.columns === 1 || value.columns === 2 || value.columns === 3)
  );
}

export function parseVisualizationSpec(source: string): VisualizationSpec {
  const parsed: unknown = JSON.parse(source);
  if (!isSavedVisualizationSpec(parsed)) {
    throw new Error(`This is not an AgentBase visualization (${VISUALIZATION_SCHEMA}).`);
  }
  return { ...parsed, $schema: VISUALIZATION_SCHEMA };
}

export function parseDashboardSpec(source: string): DashboardSpec {
  const parsed: unknown = JSON.parse(source);
  if (!isSavedDashboardSpec(parsed)) {
    throw new Error(`This is not an AgentBase dashboard (${DASHBOARD_SCHEMA}).`);
  }
  return { ...parsed, $schema: DASHBOARD_SCHEMA };
}

export function visualizationJson(spec: VisualizationSpec): string {
  return `${JSON.stringify({ ...spec, $schema: VISUALIZATION_SCHEMA }, null, 2)}\n`;
}

export function dashboardJson(spec: DashboardSpec): string {
  return `${JSON.stringify({ ...spec, $schema: DASHBOARD_SCHEMA }, null, 2)}\n`;
}

export function defaultVisualization(path: string, data: DataSet): VisualizationSpec {
  const numeric = data.columns.filter((column) => column.kind === "number").map((column) => column.name);
  const dimension = defaultDimension(data);
  const y = numeric.filter((name) => name !== dimension).slice(0, 3);
  const title = path.split("/").at(-1)?.replace(/\.[^.]+$/, "") ?? "Visualization";
  return {
    $schema: VISUALIZATION_SCHEMA,
    title,
    source: path,
    chart: y.length === 0 ? "table" : data.columns.find((column) => column.name === dimension)?.kind === "date" ? "line" : "bar",
    x: dimension,
    y,
    series: null,
    // Several rows per category would draw only the first of each; a first
    // chart shows their average instead, and says so in its settings.
    aggregate: dimension !== null && y.length > 0 && repeats(data.rows, dimension) ? "average" : "none",
    sort: "source",
    limit: 250,
  };
}

function repeats(rows: DataRow[], name: string): boolean {
  return new Set(rows.map((row) => row[name] ?? null)).size < rows.length;
}

export function parseDataFile(path: string, source: string): DataSet {
  const lower = path.toLowerCase();
  let rows: DataRow[];
  if (lower.endsWith(".csv")) {
    rows = tabularRows(parseDelimited(source, ","));
  } else if (lower.endsWith(".tsv")) {
    rows = tabularRows(parseDelimited(source, "\t"));
  } else if (lower.endsWith(".jsonl") || lower.endsWith(".ndjson")) {
    rows = source
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line, index) => normalizeRow(JSON.parse(line) as unknown, index));
  } else if (lower.endsWith(".json")) {
    rows = rowsFromJson(JSON.parse(source) as unknown);
  } else {
    throw new Error("Charts read CSV, TSV, JSON, JSONL or NDJSON data files.");
  }
  if (rows.length > DATA_LIMIT) rows = rows.slice(0, DATA_LIMIT);
  const names: string[] = [];
  for (const row of rows) {
    for (const name of Object.keys(row)) if (!names.includes(name)) names.push(name);
  }
  const coerced = rows.map((row) => Object.fromEntries(names.map((name) => [name, coerce(row[name] ?? null)])));
  return {
    columns: names.map((name) => ({ name, kind: columnKind(coerced.map((row) => row[name] ?? null)) })),
    rows: coerced,
  };
}

export function prepareChart(data: DataSet, spec: VisualizationSpec): PreparedChart {
  const known = new Set(data.columns.map((column) => column.name));
  const x = spec.x !== null && known.has(spec.x) ? spec.x : null;
  const y = spec.y.filter((field) => known.has(field));
  const seriesField = spec.series !== null && known.has(spec.series) ? spec.series : null;
  let rows = data.rows.slice(0, Math.min(spec.limit, CHART_LIMIT));
  const sourceRows = rows.length;
  if (spec.aggregate !== "none") rows = aggregateRows(rows, x, y, seriesField, spec.aggregate);
  const drawn = new Set(
    rows.map((row, index) => JSON.stringify([seriesField === null ? null : row[seriesField] ?? null, x === null ? index : row[x] ?? null])),
  );
  rows = sortRows(rows, x, y[0] ?? null, spec.sort);

  const labels = unique(rows.map((row, index) => labelOf(x === null ? index + 1 : row[x] ?? index + 1)));
  let series: ChartSeries[];
  if (seriesField !== null && y[0] !== undefined) {
    const names = unique(rows.map((row) => labelOf(row[seriesField] ?? "Other")));
    series = names.map((name) => ({
      name,
      points: rows
        .filter((row) => labelOf(row[seriesField] ?? "Other") === name)
        .map((row, index) => ({
          label: labelOf(x === null ? index + 1 : row[x] ?? index + 1),
          value: numeric(row[y[0] ?? ""]),
          row,
        })),
    }));
  } else {
    series = y.map((field) => ({
      name: field,
      points: rows.map((row, index) => ({
        label: labelOf(x === null ? index + 1 : row[x] ?? index + 1),
        value: numeric(row[field]),
        row,
      })),
    }));
  }
  return { labels, series, rows, columns: data.columns, sourceRows, repeated: rows.length - drawn.size };
}

function parseDelimited(source: string, delimiter: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let value = "";
  let quoted = false;
  for (let index = 0; index < source.length; index += 1) {
    const character = source[index] ?? "";
    if (quoted) {
      if (character === '"' && source[index + 1] === '"') {
        value += '"';
        index += 1;
      } else if (character === '"') {
        quoted = false;
      } else {
        value += character;
      }
    } else if (character === '"' && value === "") {
      quoted = true;
    } else if (character === delimiter) {
      row.push(value);
      value = "";
    } else if (character === "\n" || character === "\r") {
      if (character === "\r" && source[index + 1] === "\n") index += 1;
      row.push(value);
      if (row.some((cell) => cell !== "")) rows.push(row);
      row = [];
      value = "";
    } else {
      value += character;
    }
  }
  if (quoted) throw new Error("The data ends inside a quoted field.");
  row.push(value);
  if (row.some((cell) => cell !== "")) rows.push(row);
  return rows;
}

function tabularRows(table: string[][]): DataRow[] {
  const [header, ...body] = table;
  if (header === undefined) return [];
  const names = header.map((name, index) => name.trim() || `column_${String(index + 1)}`);
  const duplicates = names.filter((name, index) => names.indexOf(name) !== index);
  if (duplicates.length > 0) throw new Error(`Duplicate column name: ${duplicates[0] ?? "unknown"}.`);
  return body.map((cells) => Object.fromEntries(names.map((name, index) => [name, cells[index]?.trim() ?? null])));
}

/**
 * The column a first chart is drawn along. A date that changes makes a time
 * series. Otherwise a short text label that tells rows apart (a ticker, a
 * name), since an ID, a URL or a sentence makes an unreadable axis. A date all
 * rows share, as one collector run stamps them, tells nothing apart.
 */
function defaultDimension(data: DataSet): string | null {
  const varies = (name: string) => new Set(data.rows.map((row) => row[name] ?? null)).size > 1;
  const series = data.columns.find((column) => column.kind === "date" && varies(column.name));
  if (series !== undefined) return series.name;
  const label = data.columns.find((column) => column.kind === "text" && varies(column.name) && shortLabels(data.rows, column.name));
  if (label !== undefined) return label.name;
  return data.columns.find((column) => column.kind === "date" || column.kind === "text")?.name ?? data.columns[0]?.name ?? null;
}

/** Longer than this on average reads as an ID or prose, not an axis label. */
const LABEL_LENGTH = 24;

function shortLabels(rows: DataRow[], name: string): boolean {
  const values = rows.map((row) => row[name]).filter((value) => typeof value === "string");
  return values.length > 0 && sum(values.map((value) => value.length)) / values.length <= LABEL_LENGTH;
}

function rowsFromJson(value: unknown): DataRow[] {
  if (Array.isArray(value)) return value.map(normalizeRow);
  if (!isRecord(value)) return [{ value: scalar(value) }];
  const keyed = keyedRows(value);
  if (keyed !== null) return keyed;
  const arrays = nestedArrays(value, 0).sort((left, right) => right.length - left.length);
  if (arrays[0] !== undefined) return arrays[0].map(normalizeRow);
  return fieldRows(value);
}

/**
 * `{"AAPL": {"last": 1}, "MSFT": {"last": 2}}`: a record per key, read as one
 * row per key with the key as a column. Only where every record is flat, so an
 * API envelope (`{"data": {"items": [...]}}`) still finds its table.
 */
function keyedRows(value: Record<string, unknown>): DataRow[] | null {
  const entries = Object.entries(value);
  const flat = (item: unknown) =>
    isRecord(item) &&
    Object.values(item).every((field) => !isRecord(field) && !(Array.isArray(field) && field.some((part) => isRecord(part) || Array.isArray(part))));
  if (entries.length === 0 || !entries.every(([, item]) => flat(item))) return null;
  const name = entries.some(([, item]) => isRecord(item) && "key" in item) ? "_key" : "key";
  return entries.map(([key, item], index) => ({ [name]: key, ...normalizeRow(item, index) }));
}

/**
 * A settings object such as `{"max_position_pct": 10, "max_sector_pct": 30}`:
 * one row per field, nested fields named by their dotted path, so each figure
 * is a bar of its own rather than one row of columns.
 */
function fieldRows(value: Record<string, unknown>): DataRow[] {
  const rows: DataRow[] = [];
  const visit = (prefix: string, item: unknown, depth: number) => {
    if (isRecord(item) && depth < 6) {
      for (const [key, child] of Object.entries(item)) visit(prefix === "" ? key : `${prefix}.${key}`, child, depth + 1);
    } else {
      rows.push({ field: prefix, value: isRecord(item) ? JSON.stringify(item) : scalar(item) });
    }
  };
  visit("", value, 0);
  return rows;
}

function nestedArrays(value: unknown, depth: number): unknown[][] {
  if (depth > 4) return [];
  if (Array.isArray(value)) return value.length === 0 ? [value] : [value, ...value.flatMap((item) => nestedArrays(item, depth + 1))];
  if (!isRecord(value)) return [];
  return Object.values(value).flatMap((item) => nestedArrays(item, depth + 1));
}

function normalizeRow(value: unknown, index: number): DataRow {
  if (!isRecord(value)) return { index: index + 1, value: scalar(value) };
  const row: DataRow = {};
  for (const [key, item] of Object.entries(value)) {
    row[key] = isRecord(item) || Array.isArray(item) ? JSON.stringify(item) : scalar(item);
  }
  return row;
}

function aggregateRows(rows: DataRow[], x: string | null, y: string[], series: string | null, aggregate: Aggregate): DataRow[] {
  const groups = new Map<string, DataRow[]>();
  for (const row of rows) {
    const key = JSON.stringify([x === null ? "All" : row[x], series === null ? null : row[series]]);
    groups.set(key, [...(groups.get(key) ?? []), row]);
  }
  return [...groups.values()].map((members) => {
    const first = members[0] ?? {};
    const result: DataRow = {};
    if (x !== null) result[x] = first[x] ?? null;
    if (series !== null) result[series] = first[series] ?? null;
    for (const field of y) {
      const values = members.map((row) => numeric(row[field]));
      result[field] = aggregate === "count" ? members.length : aggregate === "sum" ? sum(values) : aggregate === "average" ? sum(values) / Math.max(1, values.length) : aggregate === "minimum" ? Math.min(...values) : Math.max(...values);
    }
    return result;
  });
}

function sortRows(rows: DataRow[], x: string | null, y: string | null, order: SortOrder): DataRow[] {
  if (order === "source") return rows;
  const field = order.startsWith("x-") ? x : y;
  if (field === null) return rows;
  const direction = order.endsWith("descending") ? -1 : 1;
  return [...rows].sort((left, right) => compare(left[field] ?? null, right[field] ?? null) * direction);
}

function compare(left: Scalar, right: Scalar): number {
  if (typeof left === "number" && typeof right === "number") return left - right;
  const leftDate = typeof left === "string" && ISO_DATE.test(left) ? Date.parse(left) : Number.NaN;
  const rightDate = typeof right === "string" && ISO_DATE.test(right) ? Date.parse(right) : Number.NaN;
  if (Number.isFinite(leftDate) && Number.isFinite(rightDate)) return leftDate - rightDate;
  return labelOf(left).localeCompare(labelOf(right), undefined, { numeric: true });
}

function columnKind(values: Scalar[]): ColumnKind {
  const present = values.filter((value) => value !== null);
  if (present.length === 0) return "text";
  if (present.every((value) => typeof value === "number")) return "number";
  if (present.every((value) => typeof value === "boolean")) return "boolean";
  if (present.every((value) => typeof value === "string" && ISO_DATE.test(value) && !Number.isNaN(Date.parse(value)))) return "date";
  return "text";
}

function coerce(value: Scalar): Scalar {
  if (typeof value !== "string") return value;
  const trimmed = value.trim();
  if (trimmed === "") return null;
  const numericText = /^-?\d{1,3}(?:,\d{3})+(?:\.\d+)?$/.test(trimmed) ? trimmed.replaceAll(",", "") : trimmed;
  if (/^-?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(numericText)) {
    const number = Number(numericText);
    if (Number.isFinite(number)) return number;
  }
  if (trimmed.toLowerCase() === "true") return true;
  if (trimmed.toLowerCase() === "false") return false;
  return trimmed;
}

function scalar(value: unknown): Scalar {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "bigint") return value.toString();
  return "";
}

function numeric(value: Scalar | undefined): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "boolean") return value ? 1 : 0;
  const parsed = typeof value === "string" ? Number(value.replaceAll(",", "")) : 0;
  return Number.isFinite(parsed) ? parsed : 0;
}

function labelOf(value: Scalar | number): string {
  if (value === null) return "Empty";
  if (typeof value === "boolean") return value ? "True" : "False";
  return String(value);
}

function unique<T>(values: T[]): T[] {
  return [...new Set(values)];
}

function sum(values: number[]): number {
  return values.reduce((total, value) => total + value, 0);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isVisualizationSchema(value: unknown): value is typeof VISUALIZATION_SCHEMA | typeof LEGACY_VISUALIZATION_SCHEMA {
  return value === VISUALIZATION_SCHEMA || value === LEGACY_VISUALIZATION_SCHEMA;
}

function isDashboardSchema(value: unknown): value is typeof DASHBOARD_SCHEMA | typeof LEGACY_DASHBOARD_SCHEMA {
  return value === DASHBOARD_SCHEMA || value === LEGACY_DASHBOARD_SCHEMA;
}

function isChartKind(value: unknown): value is ChartKind {
  return ["bar", "line", "area", "scatter", "pie", "metric", "table"].includes(String(value));
}

function isAggregate(value: unknown): value is Aggregate {
  return ["none", "sum", "average", "count", "minimum", "maximum"].includes(String(value));
}

function isSortOrder(value: unknown): value is SortOrder {
  return ["source", "x-ascending", "x-descending", "value-ascending", "value-descending"].includes(String(value));
}
