"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  Activity,
  Bot,
  CircleCheck,
  FileText,
  FlaskConical,
  GitBranch,
  Link2,
  LoaderCircle,
  Play,
  RefreshCw,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";

import { announceAutopilot, AUTOPILOT_EVENT } from "@/components/autopilot-toggle";
import { PageContainer } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { ErrorNote, Loading, NativeSelect, PageHeader, Panel, Stat } from "@/components/ui-kit";
import { ApiError } from "@/lib/api";
import type { AgentEvent, AutopilotStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { workspaceApi } from "@/lib/workspace-api";

const KIND_ICON: Record<AgentEvent["kind"], LucideIcon> = {
  cycle: Activity,
  links: Link2,
  recheck: RefreshCw,
  document: FileText,
  impact: GitBranch,
  test: FlaskConical,
};

const INTERVALS = [
  { seconds: 20, label: "Every 20 seconds" },
  { seconds: 60, label: "Every minute" },
  { seconds: 300, label: "Every 5 minutes" },
  { seconds: 3600, label: "Every hour" },
  { seconds: 86400, label: "Every day" },
];

function eventHref(event: AgentEvent): string | null {
  if (!event.ref) return null;
  if (event.ref.type === "check") return `/?check=${event.ref.id}`;
  if (event.ref.type === "claim") return `/graph?focus=${event.ref.id}`;
  if (event.ref.type === "document") return "/impact";
  return "/monitors";
}

function EventItem({ event }: { event: AgentEvent }) {
  const Icon = KIND_ICON[event.kind] ?? Activity;
  const href = eventHref(event);
  return (
    <li className="flex gap-3 py-2.5">
      <span
        className={cn(
          "mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full",
          event.level === "warning" ? "bg-stale-soft text-stale" : event.level === "success" ? "bg-fresh-soft text-fresh" : "bg-muted text-muted-foreground",
        )}
      >
        <Icon className="size-3.5" aria-hidden />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <p className="flex flex-wrap items-baseline gap-x-2 text-sm font-medium">
          {href ? <Link href={href} className="underline-offset-4 hover:underline">{event.title}</Link> : event.title}
          <span className="text-xs font-normal text-muted-foreground">{new Date(event.at).toLocaleTimeString()}</span>
        </p>
        {event.detail && <p className="text-sm leading-6 text-muted-foreground">{event.detail}</p>}
      </div>
    </li>
  );
}

export function AutopilotPage() {
  const [status, setStatus] = useState<AutopilotStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const refresh = useCallback(() => {
    workspaceApi
      .autopilot()
      .then((value) => {
        setStatus(value);
        setError(null);
      })
      .catch((exc) => setError(exc instanceof ApiError ? exc.message : "Autopilot status is unavailable."));
  }, []);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 3000);
    const onChange = (event: Event) => setStatus((event as CustomEvent<AutopilotStatus>).detail);
    window.addEventListener(AUTOPILOT_EVENT, onChange);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener(AUTOPILOT_EVENT, onChange);
    };
  }, [refresh]);

  async function update(body: Parameters<typeof workspaceApi.setAutopilot>[0]) {
    try {
      const next = await workspaceApi.setAutopilot(body);
      setStatus(next);
      announceAutopilot(next);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "The setting couldn't be saved.");
    }
  }

  async function runNow() {
    setRunning(true);
    try {
      setStatus(await workspaceApi.runAutopilot());
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "The cycle couldn't run.");
    } finally {
      setRunning(false);
    }
  }

  const auto = status?.mode === "auto";

  return (
    <PageContainer wide>
      <PageHeader
        title="Autopilot"
        description="In auto mode ShelfLife runs itself end to end. It re-verifies claims as they come due, revisits the sources each answer relied on, verifies new documents, traces every newly stale claim downstream, corrects the documents built on it, and runs regression tests. Manual mode does each of these only when you ask."
        actions={
          <Button onClick={runNow} disabled={running || status?.running} variant="outline" data-tour="run-cycle">
            {running || status?.running ? <LoaderCircle className="motion-safe:animate-spin" aria-hidden /> : <Play aria-hidden />}
            Run a cycle now
          </Button>
        }
      />
      <ErrorNote message={error} />
      {!status && !error && <Loading />}
      {status && (
        <div className="grid gap-6 lg:grid-cols-[20rem_minmax(0,1fr)]">
          <div className="flex flex-col gap-4">
            <Panel title="Mode" data-tour="autopilot-mode">
              <div role="radiogroup" aria-label="Operating mode" className="grid grid-cols-2 gap-2">
                {(["manual", "auto"] as const).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    role="radio"
                    aria-checked={status.mode === mode}
                    onClick={() => update({ mode })}
                    className={cn(
                      "flex flex-col items-start gap-1 rounded-lg border p-3 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      status.mode === mode ? "border-foreground bg-muted/60" : "hover:bg-muted/40",
                    )}
                  >
                    <span className="flex items-center gap-1.5 text-sm font-medium">
                      {mode === "auto" ? <Bot className="size-4" aria-hidden /> : <CircleCheck className="size-4" aria-hidden />}
                      {mode === "auto" ? "Auto" : "Manual"}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {mode === "auto" ? "Everything runs on its own" : "Runs when you ask"}
                    </span>
                  </button>
                ))}
              </div>
              <label className="flex flex-col gap-1.5 text-sm">
                <span className="text-xs text-muted-foreground">How often a cycle runs</span>
                <NativeSelect value={status.interval_seconds} onChange={(e) => update({ interval_seconds: Number(e.target.value) })}>
                  {INTERVALS.some((item) => item.seconds === status.interval_seconds) ? null : (
                    <option value={status.interval_seconds}>Every {status.interval_seconds} seconds</option>
                  )}
                  {INTERVALS.map((item) => <option key={item.seconds} value={item.seconds}>{item.label}</option>)}
                </NativeSelect>
              </label>
              <label className="flex flex-col gap-1.5 text-sm">
                <span className="text-xs text-muted-foreground">Most checks per cycle (bounds spend)</span>
                <NativeSelect value={status.max_checks_per_cycle} onChange={(e) => update({ max_checks_per_cycle: Number(e.target.value) })}>
                  {[1, 2, 3, 5, 10].map((value) => <option key={value} value={value}>{value}</option>)}
                </NativeSelect>
              </label>
              <p className="text-xs text-muted-foreground">
                {auto
                  ? status.next_cycle_at
                    ? `Next cycle at ${new Date(status.next_cycle_at).toLocaleTimeString()}.`
                    : "Starting a cycle…"
                  : "Nothing runs on its own in manual mode."}
                {status.last_cycle && ` Last cycle: ${status.last_cycle.actions} actions, at ${new Date(status.last_cycle.finished_at).toLocaleTimeString()}.`}
              </p>
            </Panel>
            <Panel title="Waiting for the next cycle">
              <dl className="grid grid-cols-2 gap-3" data-tour="autopilot-pending">
                <Stat label="Answers due" value={status.pending.due_answers} />
                <Stat label="Sources to revisit" value={status.pending.links_to_visit} />
                <Stat label="Documents to correct" value={status.pending.documents_to_update} />
                <Stat label="Documents to verify" value={status.pending.documents_to_verify} />
                <Stat label="Tests due" value={status.pending.tests_due} />
              </dl>
            </Panel>
          </div>
          <Panel
            title="Activity"
            description={auto ? "Live: updates every few seconds." : "Every action the autopilot has taken."}
            actions={status.running ? <span className="flex items-center gap-1 text-xs text-muted-foreground"><LoaderCircle className="size-3.5 motion-safe:animate-spin" aria-hidden /> Working</span> : null}
          >
            {status.events.length === 0 ? (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <TriangleAlert className="size-4" aria-hidden /> No activity yet. Switch to Auto, or run a cycle now.
              </p>
            ) : (
              <ol className="flex flex-col divide-y" data-tour="activity">
                {status.events.map((event) => <EventItem key={event.id} event={event} />)}
              </ol>
            )}
          </Panel>
        </div>
      )}
    </PageContainer>
  );
}
