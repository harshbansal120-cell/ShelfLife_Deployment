export interface ClaimSpan {
  id: string;
  span: [number, number] | null;
}

export interface Segment {
  start: number;
  end: number;
  text: string;
  claimIds: string[];
}

/** Cut the answer into runs of text, each covered by the same set of claims. */
export function buildSegments(answer: string, claims: ClaimSpan[]): Segment[] {
  const valid = claims.flatMap((claim) => {
    if (!claim.span) return [];
    const [start, end] = claim.span;
    return start >= 0 && start < end && end <= answer.length
      ? [{ id: claim.id, start, end }]
      : [];
  });

  const edges = [
    ...new Set([0, answer.length, ...valid.flatMap((c) => [c.start, c.end])]),
  ].sort((a, b) => a - b);

  const segments: Segment[] = [];
  for (let index = 0; index < edges.length - 1; index += 1) {
    const start = edges[index];
    const end = edges[index + 1];
    segments.push({
      start,
      end,
      text: answer.slice(start, end),
      claimIds: valid
        .filter((claim) => claim.start <= start && claim.end >= end)
        .map((claim) => claim.id),
    });
  }
  return segments;
}

/** Clicking overlapping highlights steps through the claims they cover. */
export function nextClaimInSegment(
  claimIds: string[],
  selectedClaimId: string | null,
): string | null {
  if (claimIds.length === 0) return null;
  const index = selectedClaimId ? claimIds.indexOf(selectedClaimId) : -1;
  return claimIds[(index + 1) % claimIds.length];
}
