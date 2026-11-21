import type { AnswerEdit } from "@/lib/types";

export type DiffPart =
  | { type: "same"; text: string }
  | {
      type: "replace";
      removed: string;
      added: string;
      citations: number[];
      claimIds: string[];
    }
  | { type: "flag"; text: string; flag: string; citations: number[]; claimIds: string[] };

const CITATION_SUFFIX = /\s(\[\d+\])+$/;

/** Split "text [2]" or "text [1][2]" into the text and its markers, so markers can be links. */
export function splitCitation(text: string): string {
  return text.replace(CITATION_SUFFIX, "");
}

/** Every source an edit cites. Checks saved before edits could merge only have `citation`. */
export function editCitations(edit: AnswerEdit): number[] {
  if (edit.citations && edit.citations.length > 0) return edit.citations;
  return edit.citation === null ? [] : [edit.citation];
}

export function editClaimIds(edit: AnswerEdit): string[] {
  return edit.claim_ids && edit.claim_ids.length > 0 ? edit.claim_ids : [edit.claim_id];
}

/** Lay the answer out as unchanged text and edits, in order. Notes are returned apart. */
export function buildDiff(
  answer: string,
  edits: AnswerEdit[],
): { parts: DiffPart[]; notes: AnswerEdit[] } {
  const placed = edits
    .filter((edit) => edit.kind !== "note" && edit.start !== null && edit.end !== null)
    .sort((a, b) => a.start! - b.start!);

  const parts: DiffPart[] = [];
  let cursor = 0;
  for (const edit of placed) {
    const start = edit.start!;
    const end = edit.end!;
    if (start < cursor || end > answer.length) continue;
    if (start > cursor) parts.push({ type: "same", text: answer.slice(cursor, start) });
    const after = splitCitation(edit.after);
    if (edit.kind === "replace") {
      parts.push({
        type: "replace",
        removed: answer.slice(start, end),
        added: after,
        citations: editCitations(edit),
        claimIds: editClaimIds(edit),
      });
    } else {
      parts.push({
        type: "flag",
        text: answer.slice(start, end),
        flag: after.slice(edit.before.length).trim(),
        citations: editCitations(edit),
        claimIds: editClaimIds(edit),
      });
    }
    cursor = end;
  }
  if (cursor < answer.length) parts.push({ type: "same", text: answer.slice(cursor) });

  return { parts, notes: edits.filter((edit) => edit.kind === "note") };
}
