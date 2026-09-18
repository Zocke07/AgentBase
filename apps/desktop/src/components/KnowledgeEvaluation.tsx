import type { KnowledgeEvaluation, KnowledgeEvaluationCase } from "@agentspace/schemas";
import { useState } from "react";

import * as api from "../lib/api";

/**
 * Retrieval evaluation: one question per line with the notes it should
 * surface, scored as MRR and recall at k, so a change to ranking can be
 * judged before it reaches a run.
 */

export function KnowledgeEvaluationView({ spaceId }: { spaceId: string }) {
  const [source, setSource] = useState("");
  const [result, setResult] = useState<KnowledgeEvaluation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const evaluate = async () => {
    const cases = evaluationCases(source);
    if (cases.length === 0) {
      setError("Add at least one line in the form question => expected/note.md");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setResult(await api.evaluateKnowledge(spaceId, cases));
    } catch (failure) {
      setError(asMessage(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="knowledge__evaluation">
      <h2>Retrieval evaluation</h2>
      <p>
        Add one question per line, followed by <code>=&gt;</code> and one or more expected note paths.
        This measures whether the right evidence appears before changing ranking behavior.
      </p>
      <textarea
        aria-label="Retrieval evaluation cases"
        rows={9}
        value={source}
        placeholder={"How should storage work? => decisions/storage.md\nWhat improves retention? => research/retention.md"}
        onChange={(event) => { setSource(event.target.value); }}
      />
      <div className="knowledge__evaluation-actions">
        <button type="button" className="button button--primary" disabled={busy} onClick={() => void evaluate()}>
          {busy ? "Evaluating…" : "Run evaluation"}
        </button>
        {error !== null && <p className="form-error" role="alert">{error}</p>}
      </div>
      {result !== null && (
        <div className="knowledge__evaluation-result">
          <strong>
            MRR {Math.round(result.mean_reciprocal_rank * 100)}% · recall@{result.limit}{" "}
            {Math.round(result.mean_recall_at_k * 100)}%
          </strong>
          <ol>
            {result.results.map((item) => (
              <li key={item.question}>
                <span>{item.question}</span>
                <small>
                  expected {item.expected_paths.join(", ")} · retrieved {item.retrieved_paths.join(", ") || "nothing"}
                </small>
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}

function evaluationCases(source: string): KnowledgeEvaluationCase[] {
  return source
    .split("\n")
    .map((line) => line.split("=>", 2).map((part) => part.trim()))
    .filter((parts) => parts.length === 2 && parts[0] !== "" && parts[1] !== "")
    .map(([question = "", expected = ""]) => ({
      question,
      expected_paths: expected.split(",").map((path) => path.trim()).filter(Boolean),
    }))
    .filter((item) => item.expected_paths.length > 0);
}


function asMessage(failure: unknown): string {
  return failure instanceof Error ? failure.message : String(failure);
}
