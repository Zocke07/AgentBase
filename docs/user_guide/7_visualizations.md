# Visualizations and dashboards

[Guide contents](README.md)

## The Visualize workspace

Open **Visualize** in the left rail. It reads ordinary selected-space files as
charts, dashboards, Mermaid diagrams, and data sources; it neither uploads,
stores, nor converts them into proprietary binaries.

Charts read `.csv`, `.tsv`, `.json`, `.jsonl`, and `.ndjson`. JSON arrays are
tables, and an object that holds an array uses its largest one. An object of
records keyed by name, such as `{"AAPL": {...}, "MSFT": {...}}`, is one row per
key, with the key in a `key` column. Any other object, such as a settings file
like `config/limits.json`, is one row per setting, with `field` and `value`
columns (nested settings are named by their dotted path), so each figure gets
a bar of its own. CSV/TSV support quoted fields, embedded delimiters, and
newlines. Parsing stops at 10,000 rows and rendering at 2,000 to keep large
exports responsive.

Choose a data source to infer a first chart. It is drawn along a date that
changes from row to row, or else a short label such as a ticker, never an ID,
a link or a sentence. Where several rows share a category, the first chart
averages them. A chart that does not combine them draws only the first row of
each category, and says how many rows it left out. Then set:

- **Chart:** bar, line, area, scatter, pie, metric or table.
- **X / category:** horizontal labels or row number.
- **Values:** one or more numeric columns.
- **Series:** split a value by a category, such as region or model.
- **Aggregate:** sum, average, count, minimum, or maximum repeated categories.
- **Sort** / **Row limit:** display order and size.

Every chart has an accessible data table. **Export SVG** saves the graphic;
**Export CSV** saves its rows.

## Saved charts that agents can create

**Save** writes an ordinary `.viz.json` file. Its complete v1 contract:

```json
{
  "$schema": "agentbase://visualization/v1",
  "title": "Revenue by month",
  "source": "data/revenue.csv",
  "chart": "line",
  "x": "month",
  "y": ["revenue", "cost"],
  "series": null,
  "aggregate": "sum",
  "sort": "x-ascending",
  "limit": 250
}
```

An agent with `write_file` can write data and definitions under
`visualizations/`, subject to the normal write policy. AgentBase validates JSON
before saving and the visualization contract before rendering. Missing or
malformed sources display errors and never execute.

## Dashboards

Save charts, choose **New dashboard**, select them, and choose one, two, or
three columns. Dashboards are also ordinary JSON:

```json
{
  "$schema": "agentbase://dashboard/v1",
  "title": "Research dashboard",
  "visualizations": [
    "visualizations/revenue.viz.json",
    "visualizations/risk.viz.json"
  ],
  "columns": 2
}
```

Each card retains chart settings and export controls. Reopening redraws changed
source data.

## Mermaid diagrams

Choose **New diagram** or open `.mmd` / `.mermaid`. Mermaid supports flow,
sequence, class, entity, state, timeline, Gantt, mind-map, and other built-in
syntaxes. Rendering uses strict security with HTML labels disabled; AgentBase
also removes scripts, embedded objects, event handlers, and external SVG links.
Source remains editable beside the live preview, which exports as SVG.

The webview renders locally. Mermaid and data files leave the machine only if
an agent reads and sends them to the selected model during a run.

## Knowledge and memory metrics

Visualization also supports fast decisions:

- retrieval matches have relevance bars on Home, in Knowledge search and in
  a run's recorded context;
- retrieval evaluation shows MRR, recall at k and each case as progress bars;
- the memory inbox shows the proposed, approved and archived distribution;
- Usage retains its day-by-day spend chart, with a place for every day of the
  month.
