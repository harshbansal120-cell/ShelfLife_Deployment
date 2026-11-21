import { describe, expect, it } from "vitest";

import { parseBatchCsv, parseBatchText, parseCsvRows } from "./batch";

describe("parseBatchText", () => {
  it("splits answers on lines of dashes", () => {
    expect(parseBatchText("First answer.\n---\nSecond answer.\n\n-----\n")).toEqual([
      { answer: "First answer." },
      { answer: "Second answer." },
    ]);
  });

  it("reads a Q: line as the question", () => {
    expect(parseBatchText("Q: What does it cost?\nIt costs $5.\n---\nNo question here.")).toEqual([
      { question: "What does it cost?", answer: "It costs $5." },
      { answer: "No question here." },
    ]);
  });

  it("keeps a lone Q: line as the answer rather than dropping it", () => {
    expect(parseBatchText("Q: only a question")).toEqual([{ answer: "Q: only a question" }]);
  });

  it("ignores dashes inside a line", () => {
    expect(parseBatchText("A --- B")).toEqual([{ answer: "A --- B" }]);
  });
});

describe("parseCsvRows", () => {
  it("handles quotes, escaped quotes, commas and newlines in fields", () => {
    expect(parseCsvRows('a,"b, c","say ""hi""\nthere"\r\nd,e,f\n')).toEqual([
      ["a", "b, c", 'say "hi"\nthere'],
      ["d", "e", "f"],
    ]);
  });

  it("drops blank rows", () => {
    expect(parseCsvRows("a,b\n\n,\nc,d")).toEqual([
      ["a", "b"],
      ["c", "d"],
    ]);
  });
});

describe("parseBatchCsv", () => {
  it("uses question and answer columns by name", () => {
    const csv = '﻿id,answer,question\n1,"It costs $5, monthly.",Price?\n2,No question,\n3,,Empty answer';
    expect(parseBatchCsv(csv)).toEqual([
      { question: "Price?", answer: "It costs $5, monthly." },
      { question: undefined, answer: "No question" },
    ]);
  });

  it("falls back to question first and answer last without a header", () => {
    expect(parseBatchCsv("Price?,It costs $5.")).toEqual([{ question: "Price?", answer: "It costs $5." }]);
    expect(parseBatchCsv("Just an answer")).toEqual([{ question: undefined, answer: "Just an answer" }]);
  });
});
