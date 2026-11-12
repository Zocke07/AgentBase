import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { ErrorBoundary } from "../components/ErrorBoundary";
import "../index.css";

import { Workbench } from "./Workbench";
import { applyEnvironment, environmentFrom } from "./environment";
import "./workbench.css";

const container = document.getElementById("root");

if (container === null) {
  throw new Error("#root is missing from workbench.html");
}

const query = new URLSearchParams(window.location.search);
const environment = environmentFrom(query);
// On the root before the first render, so no page is drawn in the wrong theme.
applyEnvironment(environment);

// A cursor is a whole number of events; anything else in the link is no cursor.
const linked = query.get("cursor") ?? "";
const cursor = /^\d+$/.test(linked) ? Number(linked) : null;

createRoot(container).render(
  <StrictMode>
    <ErrorBoundary label="The workbench">
      <Workbench
        initialPage={query.get("page")}
        initialEnvironment={environment}
        {...(cursor === null ? {} : { initialCursor: cursor })}
      />
    </ErrorBoundary>
  </StrictMode>,
);
