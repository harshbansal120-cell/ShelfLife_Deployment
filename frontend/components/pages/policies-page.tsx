"use client";

import { useState } from "react";
import { Check, Plus, Trash2 } from "lucide-react";

import { PageContainer } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ErrorNote, Field, Loading, PageHeader, Panel } from "@/components/ui-kit";
import { useApi } from "@/hooks/use-api";
import { ApiError } from "@/lib/api";
import type { FreshnessPolicy, PolicyCategory } from "@/lib/types";
import { cn } from "@/lib/utils";
import { CATEGORY_LABELS } from "@/lib/verdicts";
import { workspaceApi, type PolicyBody } from "@/lib/workspace-api";

const CATEGORIES: PolicyCategory[] = [
  "pricing", "version_api", "product_status", "statistic", "leadership_role", "law_regulation", "event_status",
];

function cadence(days: number | undefined): string {
  if (!days) return "When evidence ages";
  if (days === 1) return "Daily";
  if (days === 7) return "Weekly";
  return `Every ${days} days`;
}

function PolicyCard({
  policy,
  isDefault,
  onDefault,
  onDelete,
}: {
  policy: FreshnessPolicy;
  isDefault: boolean;
  onDefault: () => void;
  onDelete: () => void;
}) {
  return (
    <Panel
      className={cn(isDefault && "border-foreground/40")}
      title={policy.name}
      description={policy.description}
      actions={
        <div className="flex items-center gap-1">
          {isDefault ? (
            <span className="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-1 text-xs font-medium">
              <Check className="size-3.5" aria-hidden /> Default
            </span>
          ) : (
            <Button size="sm" variant="outline" onClick={onDefault}>Use by default</Button>
          )}
          {!policy.preset && (
            <Button size="sm" variant="ghost" onClick={onDelete} aria-label={`Delete ${policy.name}`}>
              <Trash2 aria-hidden />
            </Button>
          )}
        </div>
      }
    >
      <table className="w-full text-left text-xs">
        <thead className="text-muted-foreground">
          <tr>
            <th className="py-1 font-normal">Kind of fact</th>
            <th className="py-1 font-normal">Half-life</th>
            <th className="py-1 font-normal">Re-check</th>
            <th className="py-1 font-normal">Stale holds answer</th>
          </tr>
        </thead>
        <tbody>
          {CATEGORIES.map((category) => {
            const custom = policy.half_life_days[category] !== undefined;
            return (
              <tr key={category} className="border-t">
                <td className="py-1.5">{CATEGORY_LABELS[category]}</td>
                <td className={cn("py-1.5 font-mono tabular-nums", custom && "font-medium text-foreground")}>
                  {policy.effective_half_life_days[category]} d
                </td>
                <td className="py-1.5">{cadence(policy.recheck_days[category])}</td>
                <td className="py-1.5">{policy.withhold_categories.includes(category) ? "Yes" : "–"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="text-xs text-muted-foreground">
        Holds an answer back when {Math.round(policy.withhold_ratio * 100)}% of its checked claims are stale, or any
        recommendation is.
      </p>
    </Panel>
  );
}

function NewPolicy({ base, onSaved }: { base: FreshnessPolicy | undefined; onSaved: () => void }) {
  const [name, setName] = useState("");
  const [halfLife, setHalfLife] = useState<Partial<Record<PolicyCategory, string>>>({});
  const [recheck, setRecheck] = useState<Partial<Record<PolicyCategory, string>>>({});
  const [withhold, setWithhold] = useState<PolicyCategory[]>([]);
  const [ratio, setRatio] = useState("50");
  const [error, setError] = useState<string | null>(null);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    const numbers = (values: Partial<Record<PolicyCategory, string>>) =>
      Object.fromEntries(
        Object.entries(values).filter(([, value]) => value && Number(value) > 0).map(([key, value]) => [key, Number(value)]),
      ) as Partial<Record<PolicyCategory, number>>;
    const body: PolicyBody = {
      name: name.trim(),
      half_life_days: numbers(halfLife),
      recheck_days: numbers(recheck),
      withhold_categories: withhold,
      withhold_ratio: Math.min(Math.max(Number(ratio) || 50, 1), 100) / 100,
    };
    try {
      await workspaceApi.createPolicy(body);
      setName("");
      setHalfLife({});
      setRecheck({});
      setWithhold([]);
      onSaved();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "The policy couldn't be saved.");
    }
  }

  return (
    <Panel title="Your own policy" description="Leave a field empty to use the usual rate for that kind of fact.">
      <form onSubmit={save} className="flex flex-col gap-3">
        <Field label="Name" htmlFor="policy-name">
          <Input id="policy-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={60} required placeholder="Support bot" />
        </Field>
        <table className="w-full text-left text-xs">
          <thead className="text-muted-foreground">
            <tr>
              <th className="py-1 font-normal">Kind of fact</th>
              <th className="py-1 font-normal">Half-life (days)</th>
              <th className="py-1 font-normal">Re-check every (days)</th>
              <th className="py-1 font-normal">Holds answer</th>
            </tr>
          </thead>
          <tbody>
            {CATEGORIES.map((category) => (
              <tr key={category} className="border-t">
                <td className="py-1.5 pr-2">{CATEGORY_LABELS[category]}</td>
                <td className="py-1.5 pr-2">
                  <Input
                    aria-label={`${CATEGORY_LABELS[category]} half-life`}
                    type="number" min={1} max={3650} className="h-8"
                    placeholder={String(base?.effective_half_life_days[category] ?? "")}
                    value={halfLife[category] ?? ""}
                    onChange={(e) => setHalfLife({ ...halfLife, [category]: e.target.value })}
                  />
                </td>
                <td className="py-1.5 pr-2">
                  <Input
                    aria-label={`${CATEGORY_LABELS[category]} re-check interval`}
                    type="number" min={1} max={3650} className="h-8" placeholder="–"
                    value={recheck[category] ?? ""}
                    onChange={(e) => setRecheck({ ...recheck, [category]: e.target.value })}
                  />
                </td>
                <td className="py-1.5">
                  <input
                    type="checkbox"
                    aria-label={`A stale ${CATEGORY_LABELS[category]} claim holds the answer back`}
                    checked={withhold.includes(category)}
                    onChange={(e) =>
                      setWithhold(e.target.checked ? [...withhold, category] : withhold.filter((item) => item !== category))
                    }
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <Field label="Hold back when this share of claims is stale (%)" htmlFor="policy-ratio">
          <Input id="policy-ratio" type="number" min={1} max={100} value={ratio} onChange={(e) => setRatio(e.target.value)} className="w-28" />
        </Field>
        <ErrorNote message={error} />
        <div>
          <Button size="sm" type="submit" disabled={!name.trim()}>
            <Plus aria-hidden /> Save policy
          </Button>
        </div>
      </form>
    </Panel>
  );
}

export function PoliciesPage() {
  const { data, error, loading, reload } = useApi(workspaceApi.policies);
  const [actionError, setActionError] = useState<string | null>(null);

  async function run(action: () => Promise<unknown>) {
    setActionError(null);
    try {
      await action();
      reload();
    } catch (exc) {
      setActionError(exc instanceof ApiError ? exc.message : "That didn't work.");
    }
  }

  return (
    <PageContainer wide>
      <PageHeader
        title="Freshness policies"
        description="A fact has no single shelf life. A student reading history doesn't need hourly checks; a production API needs to hear about a deprecation at once. A policy sets, for each kind of fact, how fast evidence ages, how often it is re-verified, and what holds an answer back."
      />
      {loading && !data && <Loading />}
      <ErrorNote message={error ?? actionError} />
      {data && (
        <div className="grid gap-4 md:grid-cols-2" data-tour="policies">
          {data.policies.map((policy) => (
            <PolicyCard
              key={policy.id}
              policy={policy}
              isDefault={policy.id === data.default}
              onDefault={() => run(() => workspaceApi.setDefaultPolicy(policy.id))}
              onDelete={() => run(() => workspaceApi.deletePolicy(policy.id))}
            />
          ))}
          <NewPolicy base={data.policies.find((policy) => policy.id === "balanced")} onSaved={reload} />
        </div>
      )}
    </PageContainer>
  );
}
