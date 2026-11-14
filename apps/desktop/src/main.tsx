import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { suppressNativeMenu } from "./lib/nativeMenu";
import { applyPlatform } from "./lib/platform";
import { watchVisibility } from "./lib/visibility";
import { watchWindowFocus } from "./lib/windowFocus";
import "./index.css";

// Before the first paint, so the platform's styles never arrive late.
applyPlatform();
// Animations pause while the window cannot be seen.
watchVisibility();
// A Mac app greys its selection while another window is in front.
watchWindowFocus();
// No webview menu over the chrome; the app's own menus stand in for it.
suppressNativeMenu();

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
