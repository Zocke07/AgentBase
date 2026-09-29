import type { Section } from "./sections";

/**
 * First-run tour data, separate from rendering for readable, testable copy.
 * Each step names its `data-tour` target and containing section.
 */

export interface TourStep {
  title: string;
  body: string;
  /** `data-tour` target; omit to center the card. */
  target: string | null;
  /** Target section, selected before measuring. */
  section: Section | null;
}

export const TOUR_STEPS: readonly TourStep[] = [
  {
    title: "Welcome to AgentBase",
    body:
      "A place on your own computer where a few AI agents work on their own, on a schedule or a task " +
      "you give them, and you can watch every step. This takes about a minute. Esc skips it; you can " +
      "replay it from Settings.",
    target: null,
    section: null,
  },
  {
    title: "Spaces",
    body:
      "Everything happens inside a space: its own agents, its own folder on disk and its own rules. " +
      "Switch or create one here. The folder is also an Obsidian vault.",
    target: "space",
    section: null,
  },
  {
    title: "Automations",
    body:
      "What a space does on its own: a goal at set times, or right after another schedule's run " +
      "completes. The Main space ships an investment pipeline switched off; one click on Home turns it on. " +
      "Each run stops at its time and spending limits, and the monthly cap always holds.",
    target: "rail-automations",
    section: "automations",
  },
  {
    title: "Run a task once",
    body:
      "Describe what you want done and the supervisor plans it, hands parts to workers and reports back. " +
      "Tick Step through to be asked before every call, or make the task recurring.",
    target: "goal",
    section: "home",
  },
  {
    title: "Connect a model",
    body:
      "Runs need an Anthropic or OpenAI key, a ChatGPT sign-in, or a local Ollama. Keys stay in your " +
      "OS keychain; the app reads them at launch, so a new key needs a restart. The demo run needs none of this.",
    target: "keys",
    section: "settings",
  },
  {
    title: "Watch the run",
    body:
      "A run is drawn left to right: goal, supervisor, workers, outcome. Click a card for what that agent " +
      "said and did. Calls your approval policy allows run on their own, and the log says which rule let " +
      "them; a shell command, or anything else the policy does not answer, docks at the top until you do.",
    target: "rail-runs",
    section: "runs",
  },
  {
    title: "Knowledge and memory",
    body:
      "The space folder as a vault: notes, tags, links and a graph. A finished run proposes a memory; " +
      "nothing is remembered until you approve it in the inbox here.",
    target: "rail-knowledge",
    section: "knowledge",
  },
  {
    title: "Visualize the evidence",
    body:
      "Turn CSV and JSON into charts, combine saved charts into dashboards, or render Mermaid diagrams. " +
      "The definitions are ordinary files, so agents can create and update them behind the normal approval gate.",
    target: "rail-visualize",
    section: "visualize",
  },
  {
    title: "That is the whole app",
    body: "Try a demo run to see a scripted run on the canvas without a key or a model, or finish and start your own.",
    target: null,
    section: "home",
  },
];
