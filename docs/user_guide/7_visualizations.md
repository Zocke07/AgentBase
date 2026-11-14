# Charts and dashboards

[Guide contents](README.md)

## Charts in Knowledge

Saved charts, dashboards and diagrams are listed in **Knowledge → User
Summary** under **Charts and dashboards**, and open drawn; **New…** starts one.
Their data files are under **Technical Details → Agent files**: open a CSV,
TSV, JSON or JSON-lines file and choose **Chart** above it to draw it;
**Preview** shows it as a table and **Text** returns to its source. Everything is an ordinary file in the selected space; nothing is
uploaded, stored elsewhere, or converted into a proprietary format.

Charts read `.csv`, `.tsv`, `.json`, `.jsonl`, and `.ndjson`. JSON arrays are
tables, and an object that holds an array uses its largest one. An object of
records keyed by name, such as `{"AAPL": {...}, "MSFT": {...}}`, is one row per
key, with the key in a `key` column. Any other object, such as a settings file
like `config/limits.json`, is one row per setting, with `field` and `value`
columns (nested settings are named by their dotted path), so each figure gets
a bar of its own. CSV/TSV support quoted fields, embedded delimiters, and
newlines. Parsing stops at 10,000 rows and rendering at 2,000 to keep large
exports responsive.

**Chart** infers a first chart from the file. It is drawn along a date that
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

**Save chart**, beside **Save as**, writes the chart as an ordinary
`.viz.json` file, named so it never replaces a chart the space already has,
and opens it. Save the data file's own changes first: a saved chart reads the
saved file. A chart can also start from **From template… → Chart**, which asks
for its **Data source**. Opening a saved chart draws it from its data file; its
settings edit the file, **Save chart** keeps them, and **Text** shows the JSON.
Its complete v1 contract:

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

Save charts, choose **From template… → Dashboard**, tick them, choose one,
two, or three columns, and **Save dashboard**. Dashboards are also ordinary
JSON:

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

### Investment pipeline dashboard

Turning on Main's investment pipeline creates
`visualizations/pipeline.dashboard.json` and four stable chart definitions:

- daily change by ticker from `raw/prices/summary.csv`;
- current weights from `portfolio/weights.csv`;
- prediction hit rate by horizon and agent from `scores/accuracy.csv`;
- observed hit rate by confidence bucket from `scores/calibration.csv`.

The deterministic tools refresh those stable source paths, so the dashboard
does not need a new definition each day or month. Before a stage has produced
its source, that card shows the missing file clearly; the other cards still
render. Open **Pipeline** in **Knowledge → User Summary** after the morning
and review stages have created data; a chart still waiting says **No data
yet**.

The price forecast workbook is separate from these charts. Select it under
**Knowledge → User Summary → Forecast workbooks** and choose **Open in
spreadsheet app** (in a browser tab, **Download Excel workbook**). Each session's
sheet has a row per stock with every horizon's prediction beside its later
actual close; [Agents](3_agents.md#the-investment-roster) describes it. Later
runs update the original workbook, so reopen it to see new actual prices.

## Mermaid diagrams

Choose **From template… → Mermaid diagram** or open a `.mmd` / `.mermaid`
file. Mermaid supports flow,
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
- Saved context shows the needs-attention, available and history distribution;
- Usage retains its day-by-day spend chart, with a dynamic Y axis scaled from
  the actual usage and a place for every day of the month.
- Chart series take six colours in a fixed order, chosen so that neighbouring
  series stay distinct for colour-blind readers; a chart with more series
  than that is better read as a table.
