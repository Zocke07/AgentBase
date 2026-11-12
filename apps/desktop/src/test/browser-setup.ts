/// <reference types="@vitest/browser-playwright" />
import { cleanup } from "@testing-library/react";
import { afterEach, beforeAll } from "vitest";

import "../index.css";
import "../workbench/workbench.css";

import { STILL_CSS } from "./still";

/**
 * Setup for the visual tests, which run in a real browser. The stylesheet is
 * loaded as the app loads it, and every animation and transition ends at
 * once, so a screenshot is a frame at rest: the same rule `ui-shots` uses.
 */

beforeAll(() => {
  const still = document.createElement("style");
  still.textContent = STILL_CSS;
  document.head.append(still);
});

afterEach(() => {
  cleanup();
  // Panel sizes and folds a test left behind would move the next one.
  localStorage.clear();
});
