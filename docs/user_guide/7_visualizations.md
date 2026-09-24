# Visualizations and dashboards

[Guide contents](README.md)

## The Visualize workspace

Open **Visualize** in the left rail. It reads the ordinary files in the
selected space and separates them into charts, dashboards, Mermaid diagrams
and data sources. Nothing is copied into the database, uploaded to a chart
service or converted into a proprietary binary format.

Charts can read `.csv`, `.tsv`, `.json`, `.jsonl` and `.ndjson`. A JSON array
is a table; an object containing one array uses that array; a plain object is
one row. CSV and TSV support quoted fields, embedded delimiters and embedded
newlines. The first 10,000 rows are parsed, and a chart may render at most
2,000 so an accidental large export does not freeze the window.

Choose a data source to infer a first chart, then set:

- **Chart:** bar, line, area, scatter, pie, metric or table.
- **X / category:** the labels along the horizontal axis, or row number.
- **Values:** one or more numeric columns.
- **Series:** split one value by a category such as region or model.
- **Aggregate:** sum, average, count, minimum or maximum repeated categories.
- **Sort** and **Row limit:** the order and amount shown.

Every chart has an accessible data table. **Export SVG** saves the rendered
graphic as a scalable image; **Export CSV** saves the rows behind the chart.

## Saved charts that agents can create

**Save** writes a normal JSON file ending in `.viz.json`. This is the complete
version-one contract:

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

An agent with `write_file` can write the data and this definition under
`visualizations/`. The write still asks or runs according to the same tool
policy as every other file write. AgentBase validates JSON before saving it
through the app and validates the visualization contract before rendering it.
A malformed or missing source is shown as an error, never executed.

## Dashboards

Save charts first, choose **New dashboard**, select the charts, and choose one,
two or three columns. A dashboard is also ordinary JSON:

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

Each card keeps its own chart settings and export controls. Updating a source
file and reopening the dashboard redraws it from the new data.

## Mermaid diagrams

Choose **New diagram** or open a `.mmd` or `.mermaid` file. Mermaid supports
flowcharts, sequence diagrams, class and entity diagrams, state diagrams,
timelines, Gantt charts, mind maps and its other built-in syntaxes. Diagram
rendering uses Mermaid's strict security mode with HTML labels disabled, then
AgentBase removes scripts, embedded objects, event handlers and external SVG
links before inserting the result. The source stays editable beside the live
preview, and the rendered diagram can be exported as SVG.

The renderer runs locally in the webview. Mermaid source and data files do not
leave the machine unless an agent reads them and sends their contents to the
selected model as part of a run.

## Knowledge and memory metrics

Visualization also appears where a separate dashboard would slow down a
decision:

- retrieval matches have relevance bars on Home, in Knowledge search and in
  a run's recorded context;
- retrieval evaluation shows MRR, recall at k and each case as progress bars;
- the memory inbox shows the proposed, approved and archived distribution;
- Usage retains its day-by-day spend chart.
