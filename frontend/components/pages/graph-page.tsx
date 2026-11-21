"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Flame, Link2, Trash2 } from "lucide-react";

import { PageContainer } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorNote, Field, Loading, NativeSelect, PageHeader, Panel, Stat } from "@/components/ui-kit";
import { VerdictBadge } from "@/components/verdict-badge";
import { useApi } from "@/hooks/use-api";
import { ApiError } from "@/lib/api";
import { downstream, forceLayout } from "@/lib/graph-layout";
import type { GraphData, GraphNode, Verdict } from "@/lib/types";
import { cn } from "@/lib/utils";
import { workspaceApi } from "@/lib/workspace-api";

const SIZE = 640;

const NODE_FILL: Record<string, string> = {
  stale: "var(--verdict-stale-line)",
  fresh: "var(--verdict-fresh-line)",
  uncertain: "var(--verdict-uncertain-line)",
  document: "var(--foreground)",
};

const RELATION_TEXT = {
  relies_on: "relies on",
  describes: "describes",
  declared: "declared",
  used_in: "used in",
};

function isVerdict(status: GraphNode["status"]): status is Verdict {
  return status !== "unknown" && status !== "document";
}

function shortLabel(text: string, limit = 34): string {
  return text.length <= limit ? text : `${text.slice(0, limit - 1)}…`;
}

function GraphCanvas({
  data,
  selected,
  onSelect,
}: {
  data: GraphData;
  selected: string | null;
  onSelect: (id: string | null) => void;
}) {
  const layout = useMemo(
    () => forceLayout(data.nodes.map((node) => ({ id: node.id, weight: node.reach ?? 0 })), data.edges, SIZE),
    [data],
  );
  const blast = useMemo(() => (selected ? downstream(selected, data.edges) : new Set<string>()), [selected, data]);
  const hubs = useMemo(() => new Set(data.hot.slice(0, 6).map((node) => node.id)), [data]);
  const neighbours = useMemo(() => {
    const found = new Set<string>();
    if (!selected) return found;
    for (const edge of data.edges) {
      if (edge.source === selected) found.add(edge.target);
      if (edge.target === selected) found.add(edge.source);
    }
    return found;
  }, [selected, data]);

  return (
    <svg
      viewBox={`0 0 ${SIZE} ${SIZE}`}
      className="mx-auto h-auto max-h-[68vh] w-full touch-manipulation"
      role="img"
      aria-label={`Dependency graph with ${data.nodes.length} nodes and ${data.edges.length} links`}
      onClick={() => onSelect(null)}
    >
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="16" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill="var(--muted-foreground)" />
        </marker>
      </defs>
      {data.edges.map((edge, index) => {
        const from = layout.get(edge.source);
        const to = layout.get(edge.target);
        if (!from || !to) return null;
        const hot = selected !== null && (edge.source === selected || blast.has(edge.source)) && blast.has(edge.target);
        return (
          <line
            key={index}
            x1={from.x}
            y1={from.y}
            x2={to.x}
            y2={to.y}
            stroke={hot ? "var(--verdict-stale-line)" : "var(--border)"}
            strokeWidth={hot ? 2 : 1}
            strokeDasharray={edge.relation === "declared" ? "4 3" : undefined}
            markerEnd="url(#arrow)"
            opacity={selected && !hot ? 0.35 : 1}
          />
        );
      })}
      {data.nodes.map((node) => {
        const point = layout.get(node.id);
        if (!point) return null;
        const radius = node.type === "document" ? 7 : 5 + Math.min(node.reach ?? 0, 10) * 0.9;
        const active = node.id === selected;
        const lit = !selected || active || blast.has(node.id) || neighbours.has(node.id);
        const fill = NODE_FILL[node.status] ?? "var(--verdict-unknown-line)";
        // Few labels, so they can be read: the selection and what it touches, or the hubs.
        const showLabel = selected ? active || neighbours.has(node.id) : hubs.has(node.id);
        return (
          <g
            key={node.id}
            transform={`translate(${point.x},${point.y})`}
            opacity={lit ? 1 : 0.25}
            className="cursor-pointer"
            onClick={(event) => {
              event.stopPropagation();
              onSelect(node.id);
            }}
            role="button"
            aria-label={node.label}
          >
            {node.type === "document" ? (
              <rect x={-radius} y={-radius} width={radius * 2} height={radius * 2} rx={2} fill="var(--background)" stroke={fill} strokeWidth={2} />
            ) : (
              <circle r={radius} fill={fill} stroke={active ? "var(--foreground)" : blast.has(node.id) ? "var(--verdict-stale)" : "none"} strokeWidth={2.5} />
            )}
            {showLabel && (
              <text
                x={radius + 5}
                y={4}
                fontSize={11}
                fontWeight={active ? 600 : 500}
                fill={active ? "var(--foreground)" : "var(--muted-foreground)"}
                stroke="var(--card)"
                strokeWidth={4}
                paintOrder="stroke"
                className="pointer-events-none select-none"
              >
                {shortLabel(node.label)}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

function DeclareEdge({ claims, onDone }: { claims: GraphNode[]; onDone: () => void }) {
  const edges = useApi(workspaceApi.edges);
  const [open, setOpen] = useState(false);
  const [upstream, setUpstream] = useState("");
  const [downstreamId, setDownstreamId] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function add(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await workspaceApi.addEdge({ upstream, downstream: downstreamId, note: note.trim() });
      setNote("");
      edges.reload();
      onDone();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "That link couldn't be saved.");
    }
  }

  const label = (id: string) => claims.find((claim) => claim.id === id)?.label ?? id;

  return (
    <Panel
      title="Declared dependencies"
      description="Link claims from different answers: a library recommendation relies on a Python version, which relies on an OS release."
      actions={
        <Button size="sm" variant={open ? "ghost" : "outline"} onClick={() => setOpen((value) => !value)}>
          {open ? "Cancel" : <><Link2 aria-hidden /> Add</>}
        </Button>
      }
    >
      {open && (
      <form onSubmit={add} className="flex flex-col gap-3">
        <Field label="Relies on (upstream)" htmlFor="edge-up">
          <NativeSelect id="edge-up" value={upstream} onChange={(e) => setUpstream(e.target.value)} required>
            <option value="">Choose a claim</option>
            {claims.map((claim) => <option key={claim.id} value={claim.id}>{shortLabel(claim.label, 70)}</option>)}
          </NativeSelect>
        </Field>
        <Field label="Affected claim (downstream)" htmlFor="edge-down">
          <NativeSelect id="edge-down" value={downstreamId} onChange={(e) => setDownstreamId(e.target.value)} required>
            <option value="">Choose a claim</option>
            {claims.map((claim) => <option key={claim.id} value={claim.id}>{shortLabel(claim.label, 70)}</option>)}
          </NativeSelect>
        </Field>
        <Field label="Why (optional)" htmlFor="edge-note">
          <Input id="edge-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} />
        </Field>
        <ErrorNote message={error} />
        <div>
          <Button size="sm" type="submit" disabled={!upstream || !downstreamId}>
            <Link2 aria-hidden /> Link claims
          </Button>
        </div>
      </form>
      )}
      {(edges.data?.edges.length ?? 0) > 0 && (
        <ul className="flex flex-col gap-1.5 border-t pt-3 text-xs">
          {edges.data!.edges.map((edge) => (
            <li key={edge.id} className="flex items-start gap-2">
              <span className="min-w-0 flex-1 leading-5">
                {shortLabel(label(edge.downstream), 50)} <span className="text-muted-foreground">relies on</span>{" "}
                {shortLabel(label(edge.upstream), 50)}
                {edge.note && <span className="text-muted-foreground"> · {edge.note}</span>}
              </span>
              <button
                type="button"
                aria-label="Remove link"
                className="text-muted-foreground hover:text-foreground"
                onClick={async () => {
                  await workspaceApi.deleteEdge(edge.id);
                  edges.reload();
                  onDone();
                }}
              >
                <Trash2 className="size-3.5" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

export function GraphPage() {
  const { data, error, loading, reload } = useApi(workspaceApi.graph);
  const [selected, setSelected] = useState<string | null>(null);

  // Open on a claim from a link such as /graph?focus=CLM-123456.
  useEffect(() => {
    const focus = new URLSearchParams(window.location.search).get("focus");
    if (focus) Promise.resolve().then(() => setSelected(focus));
  }, []);

  const node = data?.nodes.find((item) => item.id === selected) ?? null;
  const impact = useApi(
    () => (node && node.type === "claim" ? workspaceApi.impact(node.id) : Promise.resolve(null)),
    node?.id ?? "",
  );
  const claims = (data?.nodes ?? []).filter((item) => item.type === "claim");
  const edgesOf = (id: string) => (data?.edges ?? []).filter((edge) => edge.source === id || edge.target === id);

  return (
    <PageContainer wide>
      <PageHeader
        title="Dependency freshness graph"
        description="Every checked claim, what it relies on, and the documents built on it. Click a claim to light up its blast radius: everything that may be wrong if it changed."
      />
      {loading && !data && <Loading />}
      <ErrorNote message={error} />
      {data && data.nodes.length === 0 && <EmptyState>The graph fills in as answers are checked.</EmptyState>}
      {data && data.nodes.length > 0 && (
        <>
        <dl className="grid grid-cols-2 gap-x-8 gap-y-6 rounded-2xl border bg-card p-6 sm:grid-cols-4">
          <Stat label="Claims" value={data.stats.claims} />
          <Stat label="Documents" value={data.stats.documents} />
          <Stat label="Links" value={data.stats.edges} />
          <Stat label="Stale" value={data.stats.stale} />
        </dl>
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="rounded-2xl border bg-card p-3" data-tour="graph-canvas">
            <GraphCanvas data={data} selected={selected} onSelect={setSelected} />
            <p className="flex flex-wrap gap-x-4 gap-y-1 px-2 pb-1 text-xs text-muted-foreground">
              <span className="flex items-center gap-1"><span className="size-2.5 rounded-full bg-stale-line" /> stale</span>
              <span className="flex items-center gap-1"><span className="size-2.5 rounded-full bg-uncertain-line" /> uncertain</span>
              <span className="flex items-center gap-1"><span className="size-2.5 rounded-full bg-fresh-line" /> fresh</span>
              <span className="flex items-center gap-1"><span className="size-2.5 rounded-sm border-2 border-foreground" /> document</span>
              <span>dashed: declared dependency</span>
            </p>
          </div>
          <div className="flex flex-col gap-4">
            <Panel title={node ? (node.type === "document" ? "Document" : "Claim") : "Nothing selected"}>
              {!node ? (
                <p className="text-sm text-muted-foreground">Select a node in the graph, or a load-bearing claim below.</p>
              ) : (
                <div className="flex flex-col gap-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    {isVerdict(node.status) && <VerdictBadge verdict={node.status} />}
                    {node.type === "claim" && (
                      <Link href={`/claims?id=${node.id}`} className="font-mono text-xs text-muted-foreground underline-offset-4 hover:underline">
                        {node.id}
                      </Link>
                    )}
                  </div>
                  <p className="leading-6 font-medium">{node.label}</p>
                  {node.current_value && node.status === "stale" && (
                    <p className="text-xs text-muted-foreground">Sources now say: <span className="text-foreground">{node.current_value}</span></p>
                  )}
                  <ul className="flex flex-col gap-1 border-t pt-2 text-xs">
                    {edgesOf(node.id).map((edge, index) => {
                      const other = data.nodes.find((n) => n.id === (edge.source === node.id ? edge.target : edge.source));
                      return (
                        <li key={index} className="leading-5">
                          <span className="text-muted-foreground">
                            {edge.source === node.id ? `→ ${RELATION_TEXT[edge.relation]} by` : `← ${RELATION_TEXT[edge.relation]}`}
                          </span>{" "}
                          <button type="button" className="text-left underline-offset-4 hover:underline" onClick={() => setSelected(other?.id ?? null)}>
                            {shortLabel(other?.label ?? "", 60)}
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                  {impact.data && (
                    <p className="rounded-lg border px-3 py-2 text-xs" data-tour="blast-radius">
                      Blast radius: <span className="font-medium">{impact.data.counts.claims}</span> claims,{" "}
                      <span className="font-medium">{impact.data.counts.documents}</span> documents,{" "}
                      <span className="font-medium">{impact.data.counts.answers}</span> answers.{" "}
                      <Link href="/impact" className="underline underline-offset-4">Impact report</Link>
                    </p>
                  )}
                </div>
              )}
            </Panel>
            <Panel title="Load-bearing claims" description="The most downstream reach">
              <ul className="flex flex-col gap-1" data-tour="hot-claims">
                {data.hot.map((item) => (
                  <li key={item.id}>
                    <button
                      type="button"
                      onClick={() => setSelected(item.id)}
                      className={cn(
                        "flex w-full items-start gap-2 rounded-md px-1.5 py-1 text-left text-xs outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring",
                        selected === item.id && "bg-muted",
                      )}
                    >
                      <Flame className={cn("mt-0.5 size-3.5 shrink-0", item.status === "stale" ? "text-stale" : "text-muted-foreground")} aria-hidden />
                      <span className="min-w-0 flex-1 leading-5">{shortLabel(item.label, 60)}</span>
                      <span className="font-mono tabular-nums text-muted-foreground">{item.reach}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </Panel>
            <DeclareEdge claims={claims} onDone={reload} />
          </div>
        </div>
        </>
      )}
    </PageContainer>
  );
}
