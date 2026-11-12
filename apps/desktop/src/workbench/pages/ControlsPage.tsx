import type { ReactNode } from "react";

import { Skeleton } from "../../components/Skeleton";

/**
 * The shared controls as the stylesheet draws them today: buttons, status
 * and risk badges, cards, form fields and loading placeholders, each in the
 * states it has. Stage 20.2's primitives replace these one by one.
 */

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="wb-group">
      <h3 className="wb-group__title">{title}</h3>
      <div className="wb-group__row">{children}</div>
    </section>
  );
}

const STATUSES = ["pending", "running", "paused", "completed", "failed", "cancelled"] as const;
const RISKS = ["low", "medium", "high"] as const;

export function ControlsPage() {
  return (
    <div className="wb-controls">
      <Group title="Buttons">
        <button type="button" className="button">
          Open settings
        </button>
        <button type="button" className="button button--primary">
          Run once
        </button>
        <button type="button" className="button button--small">
          Jump to end
        </button>
        <button type="button" className="button button--danger">
          Delete run...
        </button>
        <button type="button" className="button" disabled>
          Save note
        </button>
        <button type="button" className="button button--primary" aria-busy="true">
          Saving
        </button>
      </Group>

      <Group title="Answers to a question">
        <button type="button" className="button button--deny">
          Deny
        </button>
        <button type="button" className="button button--allow">
          Allow
        </button>
        <button type="button" className="button button--allow-run">
          Allow for this run
        </button>
      </Group>

      <Group title="Run status">
        {STATUSES.map((status) => (
          <span key={status} className={`status status--${status}`}>
            {status}
          </span>
        ))}
      </Group>

      <Group title="Risk">
        {RISKS.map((risk) => (
          <span key={risk} className={`risk risk--${risk}`}>
            {risk}
          </span>
        ))}
      </Group>

      <Group title="Cards">
        <div className="card wb-controls__card">
          <h3 className="card__title">My portfolio</h3>
          <p>Your holdings, cash and limits for this space's stock research.</p>
          <div className="card__actions">
            <button type="button" className="button">
              Edit portfolio
            </button>
          </div>
        </div>
        <div className="card card--notice wb-controls__card">
          <h3 className="card__title">One step before your first run</h3>
          <p>No API key yet. Add one in Settings under Keys.</p>
        </div>
      </Group>

      <Group title="Fields">
        <label className="wb-controls__field">
          <span>Name</span>
          <input type="text" defaultValue="Main" />
        </label>
        <label className="wb-controls__field">
          <span>Invalid</span>
          <input type="text" defaultValue="" aria-invalid="true" placeholder="A name is required" />
        </label>
        <label className="wb-controls__field">
          <span>Provider</span>
          <select defaultValue="anthropic">
            <option value="anthropic">Anthropic</option>
            <option value="openai">OpenAI</option>
          </select>
        </label>
        <label className="wb-controls__field">
          <span>Disabled</span>
          <input type="text" defaultValue="Read only" disabled />
        </label>
        <label className="wb-controls__check">
          <input type="checkbox" defaultChecked /> <span>Notify me</span>
        </label>
        <label className="wb-controls__check">
          <input type="radio" name="wb-radio" defaultChecked /> <span>Daily</span>
        </label>
        <label className="wb-controls__field wb-controls__field--wide">
          <span>Goal</span>
          <textarea rows={2} defaultValue="Summarise the quarterly report" />
        </label>
      </Group>

      <Group title="Loading">
        <div className="wb-controls__card">
          <Skeleton label="Loading a note" title lines={3} />
        </div>
        <span className="spinner" aria-hidden="true" />
      </Group>
    </div>
  );
}
