import type { Section } from "./sections";

/**
 * The first-run tour's script, apart from the component that draws it so
 * the words can be read and tested as data. Each step names the element it
 * points at by its `data-tour` value and the section that element lives in.
 */

export interface TourStep {
  title: string;
  body: string;
  /** The `data-tour` value of the element to spotlight; none centres the card. */
  target: string | null;
  /** The section the target lives in, switched to before measuring. */
  section: Section | null;
}

export const TOUR_STEPS: readonly TourStep[] = [
  {
    title: "Welcome to AgentSpace",
    body:
      "A place on your own computer where a few AI agents work on a task together while you watch. " +
      "This takes about a minute. Esc skips it; you can replay it from Settings.",
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
    title: "Start a task on Home",
    body:
      "Describe what you want done. The supervisor plans it, hands parts to workers and reports back. " +
      "Notes from the space that match the task are shown before you start, and you can leave any out.",
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
      "said and did. Anything that needs your permission docks at the top of the run until you answer.",
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
    title: "That is the whole app",
    body: "Try a demo run to see a scripted run on the canvas without a key or a model, or finish and start your own.",
    target: null,
    section: "home",
  },
];

