import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { applyPlatform } from "./lib/platform";
import { watchVisibility } from "./lib/visibility";
import "./index.css";

// Before the first paint, so the platform's styles never arrive late.
applyPlatform();
// Animations pause while the window cannot be seen.
watchVisibility();

const container = document.getElementById("root");

if (container === null) {
  throw new Error("#root is missing from index.html");
}

createRoot(container).render(
  <StrictMode>
    <ErrorBoundary label="AgentBase">
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
