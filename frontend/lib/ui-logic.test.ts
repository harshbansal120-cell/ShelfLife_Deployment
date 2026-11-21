import { describe, expect, it } from "vitest";

import { errorMessage, exportUrl } from "@/lib/api";
import { buildDiff, splitCitation } from "@/lib/diff";
import {
  checkProgress,
  checkReducer,
  initialCheckState,
  preferredClaimId,
  type CheckState,
} from "@/lib/check-state";
import {
  confidenceLabel,
  formatAge,
  formatCost,
  formatDate,
  formatDuration,
  formatResetPeriod,
  safeHref,
} from "@/lib/format";
import { buildSegments, nextClaimInSegment } from "@/lib/segments";
import type {
  Claim,
  ClaimResult,
  CheckResult,
  CheckStreamEvent,
  Verdict,
} from "@/lib/types";
import { strongestTone, toneForScore } from "@/lib/verdicts";

function claim(id: string, overrides: Partial<Claim> = {}): Claim {
  return {
    id,
    text: `Claim ${id}`,
    span: null,
    category: "pricing",
    entities: [],
    time_sensitive: true,
    search_queries: [],
    kind: "fact",
    depends_on: [],
    formula: null,
    number: null,
    passport_id: null,
    ...overrides,
  };
}

function scored(item: Claim, verdict: Verdict): ClaimResult {
  return {
    claim: item,
    verdict,
    freshness_score: verdict === "stale" ? 10 : 90,
    confidence: 0.8,
    current_value: null,
    explanation: "",
    evidence: [],
    score_breakdown: null,
    llm: null,
    recheck_by: null,
    change: null,
    affected_by: [],
    recalculation: null,
    decision: null,
    context_note: null,
  };
}

function reduce(events: CheckStreamEvent[], from?: CheckState): CheckState {
  const start =
    from ??
    checkReducer(
      checkReducer(initialCheckState, { type: "start", answer: "A", deep: false, useCache: true }),
      { type: "started", checkId: "id" },
    );
  return events.reduce(
    (state, event) => checkReducer(state, { type: "event", event }),
    start,
  );
}

const extracted: CheckStreamEvent = {
  type: "claims_extracted",
  data: {
    claims: [
      claim("c1"),
      claim("c2", { category: "static", time_sensitive: false }),
      claim("c3"),
    ],
  },
};

describe("buildSegments", () => {
  const text = (answer: string, spans: [string, [number, number] | null][]) =>
    buildSegments(answer, spans.map(([id, span]) => ({ id, span }))).map((s) => [
      s.text,
      s.claimIds,
    ]);

  it("keeps the whole answer when nothing is highlighted", () => {
    expect(text("Hello", [])).toEqual([["Hello", []]]);
  });

  it("splits around a claim", () => {
    expect(text("aa bb cc", [["c1", [3, 5]]])).toEqual([
      ["aa ", []],
      ["bb", ["c1"]],
      [" cc", []],
    ]);
  });

  it("handles overlapping claims", () => {
    expect(
      text("abcdef", [
        ["c1", [0, 4]],
        ["c2", [2, 6]],
      ]),
    ).toEqual([
      ["ab", ["c1"]],
      ["cd", ["c1", "c2"]],
      ["ef", ["c2"]],
    ]);
  });

  it("ignores missing and out-of-range spans", () => {
    expect(
      text("abc", [
        ["c1", null],
        ["c2", [1, 99]],
        ["c3", [2, 2]],
      ]),
    ).toEqual([["abc", []]]);
  });

  it("always rebuilds the original text", () => {
    const answer = "One two three four";
    const segments = buildSegments(answer, [
      { id: "a", span: [0, 7] },
      { id: "b", span: [4, 13] },
    ]);
    expect(segments.map((segment) => segment.text).join("")).toBe(answer);
  });
});

describe("nextClaimInSegment", () => {
  it("steps through overlapping claims and wraps around", () => {
    expect(nextClaimInSegment(["a", "b"], null)).toBe("a");
    expect(nextClaimInSegment(["a", "b"], "a")).toBe("b");
    expect(nextClaimInSegment(["a", "b"], "b")).toBe("a");
    expect(nextClaimInSegment([], "a")).toBeNull();
  });
});

describe("checkReducer", () => {
  it("moves each claim through its stages", () => {
    let state = reduce([extracted]);
    expect(state.claims[0].stage).toBe("searching");
    expect(checkProgress(state)).toEqual({ finished: 0, total: 2 });

    state = reduce(
      [{ type: "claim_evidence", data: { claim_id: "c1", sources: [{}, {}] } }],
      state,
    );
    expect(state.claims[0]).toMatchObject({ stage: "judging", sourceCount: 2 });

    state = reduce([{ type: "claim_scored", data: scored(claim("c1"), "fresh") }], state);
    expect(state.claims[0].stage).toBe("finished");
    expect(checkProgress(state)).toEqual({ finished: 1, total: 2 });
  });

  it("does not count facts that never change as progress", () => {
    const state = reduce([
      extracted,
      {
        type: "claim_scored",
        data: scored(claim("c2", { time_sensitive: false }), "not_time_sensitive"),
      },
    ]);
    expect(checkProgress(state)).toEqual({ finished: 0, total: 2 });
  });

  it("survives replayed events after a reconnect", () => {
    const result = scored(claim("c1"), "stale");
    const state = reduce([
      extracted,
      { type: "claim_scored", data: result },
      extracted,
      { type: "claim_evidence", data: { claim_id: "c1", sources: [] } },
    ]);
    expect(state.claims[0].stage).toBe("finished");
    expect(state.claims[0].result).toBe(result);
  });

  it("opens the first stale claim but never overrides the reader's choice", () => {
    let state = reduce([
      extracted,
      { type: "claim_scored", data: scored(claim("c3"), "stale") },
    ]);
    expect(state.selectedClaimId).toBe("c3");

    state = checkReducer(state, { type: "select", claimId: "c1" });
    state = reduce([{ type: "claim_scored", data: scored(claim("c1"), "stale") }], state);
    expect(state.selectedClaimId).toBe("c1");
  });

  it("uses the final result when the check is done", () => {
    const result = {
      claims: [scored(claim("c1"), "fresh"), scored(claim("c3"), "uncertain")],
    } as CheckResult;
    const state = reduce([extracted, { type: "done", data: result }]);
    expect(state.phase).toBe("done");
    expect(state.claims.map((view) => view.claim.id)).toEqual(["c1", "c3"]);
    expect(state.selectedClaimId).toBe("c3");
  });

  it("shows live metrics while running and the final ones when done", () => {
    const live = { llm_calls: 1 } as CheckResult["metrics"];
    const final = { llm_calls: 3 } as CheckResult["metrics"];
    let state = reduce([extracted, { type: "metrics", data: live }]);
    expect(state.liveMetrics).toBe(live);

    state = reduce([{ type: "done", data: { claims: [], metrics: final } as unknown as CheckResult }], state);
    expect(state.liveMetrics).toBe(final);
  });

  it("keeps the last run's metrics only when the same answer runs again", () => {
    const metrics = { llm_calls: 3 } as CheckResult["metrics"];
    const done = reduce([
      extracted,
      { type: "done", data: { claims: [], metrics } as unknown as CheckResult },
    ]);

    const again = checkReducer(done, { type: "start", answer: "A", deep: false, useCache: true });
    expect(again.previousMetrics).toBe(metrics);
    expect(again.liveMetrics).toBeNull();

    const other = checkReducer(done, { type: "start", answer: "B", deep: false, useCache: false });
    expect(other).toMatchObject({ previousMetrics: null, useCache: false });
  });

  it("opens a saved check straight into its finished result", () => {
    const saved = {
      id: "old",
      answer: "Saved answer",
      claims: [scored(claim("c1"), "stale")],
      corrected_answer: "Fixed answer",
      edits: [],
      citations: [],
      metrics: { llm_calls: 2 },
    } as unknown as CheckResult;

    const state = checkReducer(initialCheckState, { type: "loaded", result: saved });

    expect(state).toMatchObject({ phase: "done", checkId: "old", answer: "Saved answer" });
    expect(state.rewrite?.corrected_answer).toBe("Fixed answer");
    expect(state.selectedClaimId).toBe("c1");
  });

  it("stores the corrected answer when it arrives", () => {
    const rewrite = { corrected_answer: "B", edits: [], citations: [] };
    const state = reduce([extracted, { type: "rewrite_ready", data: rewrite }]);
    expect(state.rewrite).toBe(rewrite);
  });

  it("records failures and clears them on the next start", () => {
    const failed = reduce([
      { type: "error", data: { code: "x", message: "Went wrong" } },
    ]);
    expect(failed).toMatchObject({ phase: "failed", error: "Went wrong" });

    const restarted = checkReducer(failed, { type: "start", answer: "B", deep: true, useCache: true });
    expect(restarted).toMatchObject({ phase: "starting", error: null, answer: "B", deep: true });
  });
});

describe("preferredClaimId", () => {
  const view = (id: string, verdict: Verdict) => ({
    claim: claim(id),
    stage: "finished" as const,
    sourceCount: 0,
    result: scored(claim(id), verdict),
  });

  it("prefers stale, then uncertain, then any checked claim", () => {
    expect(preferredClaimId([view("a", "fresh"), view("b", "stale")])).toBe("b");
    expect(preferredClaimId([view("a", "fresh"), view("b", "uncertain")])).toBe("b");
    expect(preferredClaimId([view("a", "not_time_sensitive"), view("b", "fresh")])).toBe("b");
    expect(preferredClaimId([view("a", "not_time_sensitive")])).toBeNull();
  });
});

describe("verdict tones", () => {
  it("matches the score bands", () => {
    expect([100, 70, 69, 40, 39, 0].map(toneForScore)).toEqual([
      "fresh",
      "fresh",
      "uncertain",
      "uncertain",
      "stale",
      "stale",
    ]);
  });

  it("shows the most important tone where claims overlap", () => {
    expect(strongestTone(["fresh", "stale"])).toBe("stale");
    expect(strongestTone(["fresh", "pending"])).toBe("pending");
    expect(strongestTone(["fresh"])).toBe("fresh");
  });
});

describe("buildDiff", () => {
  const answer = "Acme costs $10. Bo runs Acme. It has 40 staff.";
  const edits = [
    {
      claim_id: "c2",
      kind: "flag" as const,
      start: 16,
      end: 28,
      before: "Bo runs Acme",
      after: "Bo runs Acme (could not verify)",
      citation: null,
    },
    {
      claim_id: "c1",
      kind: "replace" as const,
      start: 0,
      end: 14,
      before: "Acme costs $10",
      after: "Acme costs $25 [1]",
      citation: 1,
    },
    {
      claim_id: "c3",
      kind: "note" as const,
      start: null,
      end: null,
      before: "",
      after: "Out of date: Claim c3. [2]",
      citation: 2,
    },
  ];

  it("lays out unchanged text and edits in answer order", () => {
    const { parts, notes } = buildDiff(answer, edits);
    expect(parts).toEqual([
      { type: "replace", removed: "Acme costs $10", added: "Acme costs $25", citations: [1], claimIds: ["c1"] },
      { type: "same", text: ". " },
      { type: "flag", text: "Bo runs Acme", flag: "(could not verify)", citations: [], claimIds: ["c2"] },
      { type: "same", text: ". It has 40 staff." },
    ]);
    expect(notes.map((note) => note.claim_id)).toEqual(["c3"]);
  });

  it("keeps every citation and claim of a merged edit", () => {
    const merged = {
      claim_id: "c1",
      kind: "replace" as const,
      start: 0,
      end: 14,
      before: "Acme costs $10",
      after: "Acme costs $25 [1][2]",
      citation: 1,
      claim_ids: ["c1", "c4"],
      citations: [1, 2],
    };
    const { parts } = buildDiff(answer, [merged]);
    expect(parts[0]).toEqual({
      type: "replace",
      removed: "Acme costs $10",
      added: "Acme costs $25",
      citations: [1, 2],
      claimIds: ["c1", "c4"],
    });
  });

  it("rebuilds the original text from its unchanged and removed parts", () => {
    const { parts } = buildDiff(answer, edits);
    const original = parts
      .map((part) => (part.type === "same" ? part.text : part.type === "replace" ? part.removed : part.text))
      .join("");
    expect(original).toBe(answer);
  });

  it("skips edits that overlap or fall outside the answer", () => {
    const bad = [
      { ...edits[1] },
      { ...edits[1], claim_id: "c9", start: 5, end: 10 },
      { ...edits[1], claim_id: "c8", start: 40, end: 99 },
    ];
    expect(buildDiff(answer, bad).parts.filter((p) => p.type !== "same")).toHaveLength(1);
  });

  it("strips the citation marker so it can be shown as a link", () => {
    expect(splitCitation("Acme costs $25 [12]")).toBe("Acme costs $25");
    expect(splitCitation("No marker")).toBe("No marker");
  });
});

describe("exportUrl", () => {
  it("points at the export endpoint", () => {
    expect(exportUrl("abc", "md")).toMatch(/\/api\/checks\/abc\/export\?format=md$/);
  });
});

describe("formatResetPeriod", () => {
  it("names budget periods in words", () => {
    expect(formatResetPeriod("1M")).toBe("month");
    expect(formatResetPeriod("1d")).toBe("day");
    expect(formatResetPeriod("3h")).toBe("3h");
    expect(formatResetPeriod(null)).toBeNull();
  });
});

describe("formatting", () => {
  it("does not shift dates across time zones", () => {
    expect(formatDate("2026-03-01", "en-GB")).toBe("1 Mar 2026");
  });

  it.each([
    ["2026-03-10", "today"],
    ["2026-03-11", "today"],
    ["2026-03-09", "yesterday"],
    ["2026-03-01", "9 days ago"],
    ["2025-09-10", "6 months ago"],
    ["2023-03-10", "3 years ago"],
  ])("describes the age of %s", (date, expected) => {
    expect(formatAge(date, "2026-03-10")).toBe(expected);
  });

  it("matches the confidence bands", () => {
    expect([0.39, 0.4, 0.69, 0.7].map(confidenceLabel)).toEqual([
      "Low",
      "Medium",
      "Medium",
      "High",
    ]);
  });

  it("is honest about unknown costs", () => {
    expect(formatCost(0.0123, 0)).toBe("$0.0123");
    expect(formatCost(0.0123, 2)).toBe("$0.0123 + 2 unpriced");
    expect(formatCost(0, 3)).toBe("Not reported");
    expect(formatCost(0, 0)).toBe("$0.0000");
  });

  it("formats durations", () => {
    expect(formatDuration(450)).toBe("450 ms");
    expect(formatDuration(1640)).toBe("1.6 s");
  });

  it("only links to web addresses", () => {
    expect(safeHref("https://example.test/a")).toBe("https://example.test/a");
    expect(safeHref("http://example.test")).toBe("http://example.test");
    expect(safeHref("javascript:alert(1)")).toBeNull();
    expect(safeHref("data:text/html,x")).toBeNull();
    expect(safeHref("not a url")).toBeNull();
  });
});

describe("errorMessage", () => {
  it("uses the server's explanation when it has one", () => {
    expect(errorMessage({ detail: "Missing settings" }, 503)).toBe("Missing settings");
  });

  it("explains validation errors without showing their raw form", () => {
    expect(errorMessage({ detail: [{ loc: ["body"] }] }, 422)).toContain("isn't valid");
  });

  it("copes with an empty body", () => {
    expect(errorMessage(null, 500)).toContain("500");
  });
});
