import { describe, expect, it } from "vitest";

import { downstream, forceLayout } from "@/lib/graph-layout";

describe("forceLayout", () => {
  const nodes = ["a", "b", "c", "d"].map((id) => ({ id, weight: 1 }));
  const edges = [
    { source: "a", target: "b" },
    { source: "b", target: "c" },
  ];

  it("is deterministic and keeps every node inside the box", () => {
    const first = forceLayout(nodes, edges, 400);
    const second = forceLayout(nodes, edges, 400);
    expect([...first.entries()]).toEqual([...second.entries()]);
    for (const point of first.values()) {
      expect(point.x).toBeGreaterThanOrEqual(0);
      expect(point.x).toBeLessThanOrEqual(400);
      expect(point.y).toBeGreaterThanOrEqual(0);
      expect(point.y).toBeLessThanOrEqual(400);
    }
  });

  it("puts linked nodes closer than unlinked ones", () => {
    const layout = forceLayout(nodes, edges, 400);
    const gap = (x: string, y: string) => Math.hypot(layout.get(x)!.x - layout.get(y)!.x, layout.get(x)!.y - layout.get(y)!.y);
    expect(gap("a", "b")).toBeLessThan(gap("a", "d") + gap("b", "d"));
  });
});

describe("downstream", () => {
  it("follows edges transitively and ignores cycles back to the start", () => {
    const edges = [
      { source: "os", target: "python" },
      { source: "python", target: "library" },
      { source: "library", target: "doc" },
      { source: "doc", target: "os" },
    ];
    expect([...downstream("os", edges)].sort()).toEqual(["doc", "library", "python"]);
    expect(downstream("doc", [])).toEqual(new Set());
  });
});
