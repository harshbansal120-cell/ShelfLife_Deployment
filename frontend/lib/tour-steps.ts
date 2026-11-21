/**
 * The guided walkthrough: an automatic tour of every feature, driving the real app.
 *
 * Each step can go to a page, run actions (click, wait for something to appear),
 * then point at an element with an explanation. Targets are `data-tour` names, or
 * CSS selectors when they start with "#", "[", "." or a tag name and a space.
 */

export type TourAction =
  | { click: string; optional?: boolean }
  | { waitFor: string; timeout?: number }
  | { pause: number }
  | { autopilot: "manual" | "auto" };

export interface TourStep {
  id: string;
  route?: string;
  actions?: TourAction[];
  target?: string;
  title: string;
  body: string;
  /** How long the step stays up before moving on, in ms. Defaults from the text length. */
  duration?: number;
}

export const TOUR_STEPS: TourStep[] = [
  {
    id: "welcome",
    route: "/",
    actions: [{ autopilot: "manual" }],
    title: "Welcome to ShelfLife",
    body: "AI answers state prices, versions and office holders with full confidence, even after they change. This tour walks through the whole system on its own. Pause, step back or skip at any time with the controls on this card.",
    duration: 7000,
  },
  {
    id: "navigation",
    route: "/",
    target: "navigation",
    title: "Everything in three groups",
    body: "Verify answers and compare apps, keep them fresh downstream with impact tracing, the dependency graph, Autopilot, policies and monitors, and see the results in the dashboard. The tour visits each of these in turn.",
    duration: 8000,
  },
  {
    id: "answer",
    route: "/",
    actions: [{ click: "example-release" }],
    target: "answer-input",
    title: "Start with any AI answer",
    body: "Here an assistant answers which Orion runtime release is current and which versions are unsupported. Paste from any model, use the bookmarklet, or call the API.",
  },
  {
    id: "policy",
    target: "policy-picker",
    title: "Freshness policies",
    body: "Different apps need different shelf lives. A developer assistant re-checks API versions weekly; a research assistant monitors history lightly. The policy sets how fast evidence ages and what holds an answer back.",
  },
  {
    id: "run",
    actions: [{ click: "check-button" }, { waitFor: "summary-done", timeout: 45000 }],
    target: "claim-list",
    title: "Every claim checked against live sources",
    body: "The answer is split into self-contained claims. Each time-sensitive one is searched, every source's stance is judged with a verified quote, and a freshness score is calculated in code.",
  },
  {
    id: "guard",
    target: "summary-done",
    title: "A score, and advice for the app",
    body: "The answer gets a freshness score and a guard decision: show it, show it with a warning, or hold it back. Apps can act on this before a user ever sees a stale answer.",
  },
  {
    id: "coupled",
    actions: [{ click: "[data-claim-id=\"c2\"]" }, { pause: 400 }],
    target: "claim-detail",
    title: "Details that ride on a changed value",
    body: "“Orion 4.2 was launched on March 4, 2025” is true forever on its own. But this answer wrote it beside “the latest release”, so once the version becomes 4.4 the date must describe 4.4. ShelfLife re-checked it as “Orion 4.4 was launched on March 4, 2025” and found the real date.",
    duration: 11000,
  },
  {
    id: "corrected",
    actions: [{ click: "#tab-corrected" }, { pause: 300 }],
    target: "answer-panel",
    title: "One consistent correction",
    body: "The version and its release date are corrected together, each with its source, and the list of unsupported versions grows to include 3.x. Everything else stays word for word.",
    duration: 10000,
  },
  {
    id: "timeline",
    actions: [
      { click: "back" },
      { click: "example-history" },
      { pause: 300 },
      { click: "check-button" },
      { waitFor: "summary-done", timeout: 45000 },
      { click: "[data-claim-id=\"c1\"]" },
      { pause: 400 },
    ],
    target: "claim-detail",
    title: "Every claim on its own timeline",
    body: "This answer is about June 2025. “In June 2025 the latest Orion release was 4.2” is judged as of June 2025, so it is correct for its time even though 4.4 is out now. The same fact claimed for today is stale, and a June 2025 price that was wrong even then is corrected for that time.",
    duration: 12000,
  },
  {
    id: "cloud",
    actions: [
      { click: "back" },
      { click: "example-cloud" },
      { pause: 300 },
      { click: "check-button" },
      { waitFor: "summary-done", timeout: 45000 },
      { click: "#tab-dependencies" },
      { pause: 300 },
    ],
    target: "answer-panel",
    title: "Answers build on facts",
    body: "This answer recommends a cloud host from two prices, a calculated total, an unstated seat-limit assumption and an API call. When a price changes, the total is recalculated in code and the recommendation is re-judged.",
    duration: 10000,
  },
  {
    id: "links",
    actions: [{ click: "#tab-links" }, { pause: 1500 }],
    target: "answer-panel",
    title: "Link rot",
    body: "Sources go away too. ShelfLife revisits every page it relied on and flags pages that moved, were deleted, or no longer contain the quoted evidence.",
  },
  {
    id: "metrics",
    target: "metrics",
    title: "Every model call through Bifrost",
    body: "Model tiering, automatic fallbacks, response caching and a budget. Each stage's calls, tokens, cost and cache hits are shown live.",
  },
  {
    id: "impact",
    route: "/impact",
    target: "impact-list",
    title: "Downstream impact",
    body: "A stale fact rarely stays in one answer. The old $20 price was also used in a proposal, a budget projection and a customer email. Each stale claim is traced to every claim, answer and document built on it.",
    duration: 10000,
  },
  {
    id: "documents",
    target: "document-detail",
    title: "Affected documents, corrected",
    body: "Each document gets a corrected version with sources: prices replaced, the yearly total recalculated, and advice re-judged. Apply it by hand, or let Autopilot do it.",
    duration: 9000,
  },
  {
    id: "graph",
    route: "/graph",
    actions: [{ waitFor: "graph-canvas" }],
    target: "graph-canvas",
    title: "The dependency freshness graph",
    body: "Claims, what they rely on, and the documents built on them, across every answer. Dashed links are declared dependencies, such as an SDK version that relies on a runtime version.",
  },
  {
    id: "blast",
    actions: [{ click: "[data-tour=\"hot-claims\"] button", optional: true }, { pause: 600 }],
    target: "graph-canvas",
    title: "Blast radius",
    body: "Selecting a load-bearing claim lights up everything downstream of it: what may be wrong if it changes.",
  },
  {
    id: "policies",
    route: "/policies",
    target: "policies",
    title: "Policies per app",
    body: "Presets for developer assistants, production APIs, business intelligence and research. Each sets half-lives, fixed re-check intervals and what holds an answer back. Save your own and pick a default.",
    duration: 9000,
  },
  {
    id: "autopilot",
    route: "/autopilot",
    target: "autopilot-mode",
    title: "Manual or fully autonomous",
    body: "In manual mode checks run when asked. In auto mode ShelfLife runs end to end on its own.",
  },
  {
    id: "autopilot-on",
    actions: [
      { click: "[data-tour=\"autopilot-mode\"] [role=\"radio\"][aria-checked=\"false\"]" },
      { waitFor: "activity", timeout: 30000 },
      { pause: 2500 },
    ],
    target: "activity",
    title: "Autopilot at work",
    body: "Re-verifying due claims, revisiting sources, verifying new documents, tracing each newly stale claim, correcting the documents built on it, and running regression tests. Every action is logged.",
    duration: 12000,
  },
  {
    id: "toggle",
    target: "mode-toggle",
    title: "Always one click away",
    body: "The same Manual and Auto switch sits at the bottom of the sidebar on every page, next to a link to this activity log.",
  },
  {
    id: "compare",
    route: "/compare",
    actions: [
      { click: "load-example" },
      { pause: 300 },
      { click: "compare-run" },
      { waitFor: "compare-result", timeout: 45000 },
    ],
    target: "compare-result",
    title: "Compare AI apps",
    body: "Three assistants gave different numbers for the same question. Each fact is searched once and every version is judged against the same sources, so you see which app is current.",
    duration: 9000,
  },
  {
    id: "dashboard",
    route: "/dashboard",
    target: "main dl",
    title: "Dashboard",
    body: "Checks over time, verdicts by kind of fact, answers held back, claims due for a re-check, and usage.",
  },
  {
    id: "claims",
    route: "/claims",
    target: "main",
    title: "Verification passports",
    body: "Every claim gets a stable ID and a record of every check: when it was confirmed, by which sources, and how its verdict changed.",
  },
  {
    id: "monitors",
    route: "/monitors",
    target: "main [role=\"tablist\"]",
    title: "Monitors",
    body: "Regression tests that re-ask a model and fail when its answer goes stale, link checks, batch checks and context profiles.",
  },
  {
    id: "integrations",
    route: "/system",
    actions: [{ waitFor: "integrations", timeout: 20000 }],
    target: "integrations",
    title: "Plugs into any agent",
    body: "ShelfLife is a tool server for AI agents over MCP, a guard in front of any app's answers, a webhook source, and an autonomous agent of its own.",
    duration: 9000,
  },
  {
    id: "done",
    route: "/",
    title: "That's ShelfLife",
    body: "Find what went stale, fix it consistently, follow it downstream, and keep everything fresh on its own. Replay the tour from the button in the bottom corner whenever you like.",
    duration: 8000,
  },
];

/** A `data-tour` name becomes an attribute selector; anything that looks like CSS is kept. */
export function targetSelector(target: string): string {
  return /[#.[\s]/.test(target) || target === "main" ? target : `[data-tour="${target}"]`;
}

export function readingTime(step: TourStep): number {
  if (step.duration) return step.duration;
  return Math.min(Math.max(4500, (step.title.length + step.body.length) * 45), 10000);
}
