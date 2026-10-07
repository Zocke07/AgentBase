import {
  DASHBOARD_SCHEMA,
  blankVisualization,
  dashboardJson,
  visualizationJson,
  type FileKind,
} from "./visualization";

/**
 * How Knowledge shows an agent file: as text, or drawn. A data file can be
 * drawn as a chart; a saved chart, dashboard or diagram opens drawn.
 */

export type FileView = "text" | "chart" | "dashboard" | "diagram";

/** The views a file offers, its default first. */
export function viewsFor(kind: FileKind): readonly FileView[] {
  switch (kind) {
    case "data":
      return ["text", "chart"];
    case "chart":
      return ["chart", "text"];
    case "dashboard":
      return ["dashboard", "text"];
    case "diagram":
      return ["diagram", "text"];
    case "text":
      return ["text"];
  }
}

export const VIEW_LABELS: Readonly<Record<FileView, string>> = {
  text: "Text",
  chart: "Chart",
  dashboard: "Dashboard",
  diagram: "Diagram",
};

/** New charts, dashboards and diagrams, offered beside the pipeline's starters. */
export const VISUAL_TEMPLATES: readonly { id: string; label: string; path: string; content: string; purpose: string }[] = [
  {
    id: "chart",
    label: "Chart",
    path: "visualizations/chart.viz.json",
    content: visualizationJson(blankVisualization("Chart")),
    purpose: "A chart drawn from one of this space's CSV or JSON files. Choose its data file and values, then save it.",
  },
  {
    id: "dashboard",
    label: "Dashboard",
    path: "visualizations/dashboard.dashboard.json",
    content: dashboardJson({ $schema: DASHBOARD_SCHEMA, title: "Dashboard", visualizations: [], columns: 2 }),
    purpose: "Saved charts side by side. Tick the charts it shows, then save it.",
  },
  {
    id: "diagram",
    label: "Mermaid diagram",
    path: "visualizations/diagram.mmd",
    content: "flowchart LR\n  Goal --> Supervisor\n  Supervisor --> Researcher\n  Researcher --> Supervisor\n  Supervisor --> Outcome\n",
    purpose: "A diagram written in Mermaid's text, drawn beside it as you type.",
  },
];
