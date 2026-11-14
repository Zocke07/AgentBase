import { EmptyState, StartupDesk } from "../../components/EmptyState";

/**
 * The empty states (brief 6.7, 7.13): the room at rest for Runs, the
 * library for Knowledge, the calendar for Automations, each with its
 * sentence and its one action; and the start screen's desk at each stage.
 */

const NOTHING = () => undefined;

export function EmptyPage() {
  return (
    <div className="wb-frames">
      <figure className="wb-frame wb-empty">
        <figcaption className="wb-frame__label">Runs</figcaption>
        <EmptyState scene="room" action={{ label: "Run once", onClick: NOTHING }}>
          Pick a run on the left to watch it or replay it, or start one.
        </EmptyState>
      </figure>
      <figure className="wb-frame wb-empty">
        <figcaption className="wb-frame__label">Knowledge</figcaption>
        <EmptyState scene="library">Pick a note on the left to read it.</EmptyState>
      </figure>
      <figure className="wb-frame wb-empty">
        <figcaption className="wb-frame__label">The start screen, stage by stage</figcaption>
        <div className="wb-startup">
          <StartupDesk engine={false} settings={false} spaces={false} />
          <StartupDesk engine settings={false} spaces={false} />
          <StartupDesk engine settings spaces={false} />
          <StartupDesk engine settings spaces />
        </div>
      </figure>
      <figure className="wb-frame wb-empty">
        <figcaption className="wb-frame__label">Automations</figcaption>
        <EmptyState scene="calendar" action={{ label: "New schedule", onClick: NOTHING }}>
          Nothing in this space runs on its own yet. A schedule runs a goal at set times, or after another one.
        </EmptyState>
      </figure>
    </div>
  );
}
