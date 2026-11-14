import { DeskFigure } from "../../components/office/Room";
import { project, type Spot } from "../../lib/officeLayout";
import { officeOf, type Desk, type Slip } from "../../state/office";
import { reduceAll } from "../../state/reducer";
import { scenario } from "../../test/scenarios";

/**
 * Every pose a desk's figure takes (brief 7.4), each alone at a large size:
 * the face, the arms, the lamp, a raised card in each risk, the tray and the
 * lead's books. Stage 20.5 moves between these; this page is where to look
 * at each one.
 */

const SPOT: Spot = { across: 1, depth: 1, ...project(1, 1) };
const VIEW = { x: SPOT.x - 70, y: SPOT.y - 100, width: 140, height: 140 };

/** A worker's desk from a real run, to vary one fact at a time. */
function baseDesk(): Desk {
  const desk = officeOf(reduceAll(scenario("two-agents").events)).desks[0];
  if (desk === undefined) throw new Error("the scenario has a worker");
  return { ...desk, slips: [], trouble: null, documents: [], bubble: null, inbox: [] };
}

const asking = (risk: string): Slip => ({
  seq: 1,
  tool: "run_shell",
  family: "shell",
  action: "run a command",
  state: "waiting",
  stamp: null,
  label: "Waiting for you",
  risk,
  host: null,
});

interface Pose {
  readonly title: string;
  readonly desk: Desk;
  readonly books?: number;
}

function poses(): Pose[] {
  const desk = baseDesk();
  const file = (path: string) => ({ path, kind: "file" as const });
  return [
    { title: "Ready", desk: { ...desk, activity: "spawned", face: "dot" } },
    { title: "Asking its model", desk: { ...desk, activity: "calling", face: "asking" } },
    { title: "Thinking", desk: { ...desk, activity: "thinking", face: "thinking" } },
    { title: "Using a tool", desk: { ...desk, activity: "executing", face: "tool", family: "network" } },
    { title: "Waiting, low risk", desk: { ...desk, activity: "waiting", face: "question", slips: [asking("low")] } },
    { title: "Waiting, medium risk", desk: { ...desk, activity: "waiting", face: "question", slips: [asking("medium")] } },
    { title: "Waiting, high risk", desk: { ...desk, activity: "waiting", face: "question", slips: [asking("high")] } },
    { title: "Done", desk: { ...desk, activity: "completed", face: "tick" } },
    { title: "Stopped", desk: { ...desk, activity: "completed", face: "knot" } },
    {
      title: "Something failed",
      desk: { ...desk, activity: "thinking", face: "alert", trouble: { kind: "alarm", message: "The feed did not answer." } },
    },
    { title: "Wrote three files", desk: { ...desk, activity: "completed", face: "tick", documents: ["a.md", "b.md", "c.csv"].map(file) } },
    { title: "The lead, with two books", desk: { ...desk, name: "supervisor", lead: true, activity: "thinking", face: "thinking" }, books: 2 },
  ];
}

export function CharactersPage() {
  return (
    <div className="wb-controls">
      <ul className="wb-icons wb-poses">
        {poses().map((pose) => (
          <li key={pose.title} className="wb-icon">
            <svg
              className="wb-pose"
              viewBox={`${String(VIEW.x)} ${String(VIEW.y)} ${String(VIEW.width)} ${String(VIEW.height)}`}
              width={VIEW.width * 1.5}
              height={VIEW.height * 1.5}
              aria-hidden="true"
              focusable="false"
            >
              <DeskFigure desk={pose.desk} spot={SPOT} books={pose.books ?? 0} />
            </svg>
            <span className="wb-icon__name">{pose.title}</span>
          </li>
        ))}
      </ul>
      <p className="type-caption wb-type__muted">
        Each figure is drawn by the office's own Room component from a desk varied one fact at a time. The pose is in
        styles/office.css, keyed on the activity.
      </p>
    </div>
  );
}
