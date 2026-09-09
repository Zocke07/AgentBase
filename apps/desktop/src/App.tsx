/**
 * Application shell.
 *
 * Phase 0 is scaffolding only: this renders enough to prove the toolchain
 * builds and typechecks. The sidecar fetch arrives in Phase 1 (packaging
 * spike) and the live run graph in Phase 7.
 */
export function App() {
  return (
    <main className="shell">
      <h1>AgentSpace</h1>
      <p className="shell__phase">Phase 0 — scaffold</p>
    </main>
  );
}
