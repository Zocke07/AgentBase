import {
  DASHBOARD_SCHEMA,
  blankVisualization,
  dashboardJson,
  visualizationJson,
  type FileKind,
} from "./visualization";

/**
 * How Knowledge shows an agent file: read in Preview, as editable text, or
 * drawn. Every file opens in a reading view, Preview or its drawing, so a
 * look cannot change it; a data file can also be drawn as a chart.
 */

export type FileView = "preview" | "text" | "chart" | "dashboard" | "diagram";

/** The views a file offers, its default first. */
export function viewsFor(kind: FileKind): readonly FileView[] {
  switch (kind) {
    case "data":
      return ["preview", "chart", "text"];
    case "chart":
      return ["chart", "text"];
    case "dashboard":
      return ["dashboard", "text"];
    case "diagram":
      return ["diagram", "text"];
    case "text":
      return ["preview", "text"];
  }
}

export const VIEW_LABELS: Readonly<Record<FileView, string>> = {
  preview: "Preview",
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
