import type { SettingsResponse, SpaceResponse } from "@agentbase/schemas";
import { useCallback, useEffect, useState } from "react";

import * as api from "../lib/api";
import { pipelineNotice } from "../lib/pipeline";
import { useFetched } from "../state/useFetched";

import { MarketWatch } from "./MarketWatch";
import { PipelineOffer } from "./PipelineOffer";
import { Schedules } from "./Schedules";

/**
 * Automations: how a space works on its own. Each schedule runs a goal at set
 * times, or right after another one completes, while AgentBase is open, under
 * the approval policy the readout spells out. This is the primary way to use a
 * space; Home's Run once is for a single task you watch.
 */

export interface AutomationsViewProps {
  space: SpaceResponse;
  settings: SettingsResponse | null;
  onOpenRun?: ((runId: string) => void) | undefined;
  /** A goal to open a new schedule with, from Home's "Make this recurring". */
  draftRequest?: { goal: string; nonce: number } | null | undefined;
  /** Moves when schedules change elsewhere, so this page rereads them. */
  schedulesNonce?: number | undefined;
  /** This page changed the schedules; Home rereads its strip. */
  onSchedulesChanged?: (() => void) | undefined;
  /** Open a space file, such as the market watch's settings, in Knowledge. */
  onOpenFile?: ((path: string) => void) | undefined;
}

const NONE: never[] = [];

export function AutomationsView({
  space,
  settings,
  onOpenRun,
  draftRequest,
  schedulesNonce = 0,
  onSchedulesChanged,
  onOpenFile,
}: AutomationsViewProps) {
  const load = useCallback(() => api.listSchedules(space.id), [space.id]);
  const schedules = useFetched(load, NONE);
  const { reload } = schedules;
  useEffect(() => {
    if (schedulesNonce > 0) reload();
  }, [schedulesNonce, reload]);
  const [notice, setNotice] = useState<string | null>(null);
  const runCap = space.max_run_cost_micros ?? settings?.settings.max_run_cost_micros ?? null;

  return (
    <div className="settings automations" data-testid="automations">
      <div className="settings__form">
        <p className="automations__intro">
          Automations are how {space.name} works on its own. Calls your approval policy allows run
          without asking; anything else waits in the approvals dock, and a question nobody answers
          expires so the run carries on without that call.
        </p>
        {notice !== null && (
          <p className="settings__saved" role="status">
            {notice}
          </p>
        )}
        {/* The pipeline and its market watch belong to the default space;
            other spaces use the general agent tools (2026-10-13). */}
        {space.is_default && (
          <PipelineOffer
            spaceId={space.id}
            schedules={schedules.data}
            runCapMicros={runCap}
            onTurnedOn={(result) => {
              setNotice(pipelineNotice(result));
              schedules.reload();
              onSchedulesChanged?.();
            }}
          />
        )}
        <Schedules
          key={space.id}
          space={space}
          settings={settings}
          onOpenRun={onOpenRun}
          draftRequest={draftRequest}
          reloadNonce={schedulesNonce}
          onChanged={onSchedulesChanged}
        />
        {space.is_default && <MarketWatch key={`watch-${space.id}`} spaceId={space.id} onOpenFile={onOpenFile} />}
      </div>
    </div>
  );
}
