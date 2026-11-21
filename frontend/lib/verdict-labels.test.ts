import { describe, expect, it } from "vitest";

import { timeFrameLabel, verdictLabel } from "@/lib/verdicts";

describe("verdict labels on a claim's own timeline", () => {
  it("says whether a past claim was right for its time", () => {
    expect(verdictLabel("fresh", "past")).toBe("Correct for its time");
    expect(verdictLabel("stale", "past")).toBe("Wrong for its time");
    expect(verdictLabel("unverified", "past")).toBe("Unverified");
  });

  it("keeps the usual labels for claims about now", () => {
    expect(verdictLabel("stale", "current")).toBe("Stale");
    expect(verdictLabel("fresh")).toBe("Fresh");
  });

  it("names the time a claim is about", () => {
    expect(timeFrameLabel({ time_frame: "past", as_of: "June 2025" })).toBe("As of June 2025");
    expect(timeFrameLabel({ time_frame: "future", as_of: null })).toBe("Planned or expected");
    expect(timeFrameLabel({ time_frame: "current" })).toBeNull();
    expect(timeFrameLabel({})).toBeNull();
  });
});
