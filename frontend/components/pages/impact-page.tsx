"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowRight, FileText, GitBranch, History, Plus, Trash2, Wand2 } from "lucide-react";

import { PageContainer } from "@/components/app-shell";
import { CorrectedAnswer } from "@/components/corrected-answer";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  EmptyState,
  ErrorNote,
  Field,
  Loading,
  NativeSelect,
  PageHeader,
  Panel,
  SectionTitle,
  Tabs,
} from "@/components/ui-kit";
import { VerdictBadge } from "@/components/verdict-badge";
import { useApi } from "@/hooks/use-api";
import { ApiError } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { DocumentKind, DocumentStatus, DocumentView, ImpactReport, LinkStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { KIND_LABELS } from "@/lib/verdicts";
import { workspaceApi } from "@/lib/workspace-api";

export const DOCUMENT_KIND_LABELS: Record<DocumentKind, string> = {
  proposal: "Proposal",
  projection: "Financial projection",
  email: "Email",
  report: "Report",
  recommendation: "Recommendation",
  other: "Document",
};

const STATUS_INFO: Record<DocumentStatus, { label: string; className: string }> = {
  current: { label: "Current", className: "bg-fresh-soft text-fresh" },
  needs_update: { label: "Needs update", className: "bg-stale-soft text-stale" },
  unverified: { label: "Not verified yet", className: "bg-unknown-soft text-unknown" },
};

const SEVERITY_CLASS: Record<ImpactReport["severity"], string> = {
  high: "bg-stale-soft text-stale",
  medium: "bg-uncertain-soft text-uncertain",
  low: "bg-unknown-soft text-unknown",
  none: "bg-muted text-muted-foreground",
};

const RELATION_LABEL = {
  relies_on: "relies on it",
  describes: "describes its value",
  declared: "declared dependency",
};

function StatusPill({ status }: { status: DocumentStatus }) {
  const info = STATUS_INFO[status];
  return <span className={cn("inline-flex h-6 items-center rounded-md px-2 text-xs font-medium", info.className)}>{info.label}</span>;
}

function LinkBadge({ status }: { status: LinkStatus }) {
  if (status === "unchecked") {
    return <span className="inline-flex h-6 items-center rounded-md bg-muted px-2 text-xs text-muted-foreground">Not checked</span>;
  }
  return <VerdictBadge verdict={status} />;
}

function ImpactCard({ report, open, onToggle }: { report: ImpactReport; open: boolean; onToggle: () => void }) {
  const { claim, counts } = report;
  return (
    <li className="rounded-2xl border bg-card" data-tour="impact-card">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full flex-col gap-2 p-4 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <div className="flex flex-wrap items-center gap-2">
          <span className={cn("inline-flex h-6 items-center rounded-md px-2 text-xs font-medium capitalize", SEVERITY_CLASS[report.severity])}>
            {report.severity} impact
          </span>
          <span className="font-mono text-xs text-muted-foreground">{claim.passport_id}</span>
          <span className="ml-auto text-xs text-muted-foreground">
            {counts.claims} claims · {counts.documents} documents · {counts.answers} answers
          </span>
        </div>
        <p className="text-sm leading-6 font-medium">{claim.text}</p>
        {claim.change && (
          <p className="flex flex-wrap items-center gap-1.5 text-sm">
            <span className="text-stale line-through decoration-stale-line">{claim.change.old_value ?? "old value"}</span>
            <ArrowRight className="size-3.5 text-muted-foreground" aria-hidden />
            <span className="font-medium">{claim.change.new_value}</span>
          </p>
        )}
      </button>
      {open && (
        <div className="flex flex-col gap-4 border-t p-4">
          {report.dependents.length > 0 && (
            <section className="flex flex-col gap-2">
              <h3 className="text-xs font-medium text-muted-foreground uppercase">Claims built on it</h3>
              <ul className="flex flex-col gap-1.5">
                {report.dependents.map((item) => (
                  <li key={item.passport_id} className="flex flex-wrap items-start gap-2 text-sm" style={{ paddingLeft: `${(item.depth - 1) * 16}px` }}>
                    {item.status !== "unknown" && <VerdictBadge verdict={item.status} />}
                    <span className="min-w-0 flex-1 leading-6">
                      {item.text ?? item.passport_id}
                      <span className="text-xs text-muted-foreground">
                        {" "}· {item.kind ? KIND_LABELS[item.kind] : "Claim"}, {RELATION_LABEL[item.relation]}
                        {item.note && ` (${item.note})`}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {report.documents.length > 0 && (
            <section className="flex flex-col gap-2">
              <h3 className="text-xs font-medium text-muted-foreground uppercase">Documents to update</h3>
              <ul className="flex flex-col gap-2">
                {report.documents.map((doc) => (
                  <li key={doc.id} className="flex flex-col gap-1 rounded-lg border p-2.5 text-sm">
                    <span className="flex items-center gap-2 font-medium">
                      <FileText className="size-4 text-muted-foreground" aria-hidden />
                      {doc.title}
                      <span className="text-xs font-normal text-muted-foreground">
                        {DOCUMENT_KIND_LABELS[doc.kind]} · {doc.direct ? "uses this claim" : `through ${doc.via}`}
                      </span>
                    </span>
                    {doc.passages.map((passage) => (
                      <q key={passage} className="text-xs text-muted-foreground">{passage}</q>
                    ))}
                  </li>
                ))}
              </ul>
            </section>
          )}
          {report.answers.length > 0 && (
            <section className="flex flex-col gap-2">
              <h3 className="text-xs font-medium text-muted-foreground uppercase">Answers that state it</h3>
              <ul className="flex flex-col gap-1">
                {report.answers.map((answer) => (
                  <li key={answer.check_id} className="text-sm">
                    <Link href={`/?check=${answer.check_id}`} className="underline-offset-4 hover:underline">
                      {answer.question ?? answer.answer_excerpt}
                    </Link>
                    <span className="text-xs text-muted-foreground"> · {formatDate(answer.checked_at.slice(0, 10))}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
          <Link href={`/graph?focus=${claim.passport_id}`} className="inline-flex items-center gap-1 text-xs underline-offset-4 hover:underline">
            <GitBranch className="size-3.5" aria-hidden /> See it on the dependency graph
          </Link>
        </div>
      )}
    </li>
  );
}

function DocumentDetail({ document, onChanged }: { document: DocumentView; onChanged: () => void }) {
  const [tab, setTab] = useState<"corrected" | "claims" | "history">(document.stale ? "corrected" : "claims");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function apply() {
    setBusy(true);
    setError(null);
    try {
      await workspaceApi.applyDocument(document.id);
      onChanged();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "The correction couldn't be applied.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    await workspaceApi.deleteDocument(document.id);
    onChanged();
  }

  return (
    <Panel
      data-tour="document-detail"
      title={document.title}
      description={`${DOCUMENT_KIND_LABELS[document.kind]} · ${document.links.length} linked claims · updated ${formatDate(document.updated_at.slice(0, 10))}`}
      actions={
        <div className="flex items-center gap-1">
          {document.stale > 0 && (
            <Button size="sm" onClick={apply} disabled={busy} data-tour="apply-correction">
              <Wand2 aria-hidden /> Apply correction
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={remove} aria-label="Delete document">
            <Trash2 aria-hidden />
          </Button>
        </div>
      }
    >
      <ErrorNote message={error} />
      <Tabs
        label="Document view"
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "corrected", label: "Corrected version" },
          { id: "claims", label: "Linked claims" },
          { id: "history", label: `Revisions (${document.revisions.length})` },
        ]}
      />
      {tab === "corrected" && (
        <CorrectedAnswer
          answer={document.text}
          rewrite={{ corrected_answer: document.corrected_text, edits: document.edits, citations: document.citations }}
          running={false}
          idPrefix={`doc-${document.id}`}
        />
      )}
      {tab === "claims" && (
        <ul className="flex flex-col divide-y">
          {document.links.map((link) => (
            <li key={link.claim_id} className="flex flex-col gap-1 py-2.5">
              <div className="flex flex-wrap items-center gap-2">
                <LinkBadge status={link.status} />
                {link.kind !== "fact" && <span className="rounded-md border px-1.5 py-0.5 text-xs">{KIND_LABELS[link.kind]}</span>}
                {link.declared && <span className="text-xs text-muted-foreground">declared by the app</span>}
                {link.passport_id && (
                  <Link href={`/claims?id=${link.passport_id}`} className="ml-auto font-mono text-xs text-muted-foreground underline-offset-4 hover:underline">
                    {link.passport_id}
                  </Link>
                )}
              </div>
              <p className="text-sm leading-6">{link.text}</p>
              {link.status === "stale" && link.current_value && (
                <p className="text-xs text-muted-foreground">Sources now say: <span className="text-foreground">{link.current_value}</span></p>
              )}
              {link.status === "unchecked" && (
                <p className="text-xs text-muted-foreground">No check has covered this claim yet. Autopilot verifies it in auto mode.</p>
              )}
            </li>
          ))}
          {document.links.length === 0 && <EmptyState>No claims were found in this document.</EmptyState>}
        </ul>
      )}
      {tab === "history" && (
        <ol className="flex flex-col gap-3">
          {document.revisions.slice().reverse().map((revision) => (
            <li key={revision.at} className="flex flex-col gap-1.5 rounded-lg border p-3 text-sm">
              <p className="flex items-center gap-2 text-xs text-muted-foreground">
                <History className="size-3.5" aria-hidden />
                {new Date(revision.at).toLocaleString()} · {revision.by === "autopilot" ? "corrected by Autopilot" : "corrected by hand"}
              </p>
              <ul className="text-sm">
                {revision.changes.map((change, index) => (
                  <li key={index}>
                    {change.old ?? change.claim} <ArrowRight className="inline size-3" aria-hidden /> <span className="font-medium">{change.new}</span>
                  </li>
                ))}
              </ul>
              <details className="text-xs text-muted-foreground">
                <summary className="cursor-pointer">Previous text</summary>
                <p className="mt-1 leading-5 whitespace-pre-wrap">{revision.previous_text}</p>
              </details>
            </li>
          ))}
          {document.revisions.length === 0 && <EmptyState>No corrections yet.</EmptyState>}
        </ol>
      )}
    </Panel>
  );
}

function NewDocument({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<DocumentKind>("proposal");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await workspaceApi.createDocument({ title: title.trim(), kind, text: text.trim() });
      setTitle("");
      setText("");
      setOpen(false);
      onCreated();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "The document couldn't be saved.");
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <Button variant="outline" className="self-start" onClick={() => setOpen(true)}>
        <Plus aria-hidden /> Register a document
      </Button>
    );
  }

  return (
    <Panel
      title="Register a document"
      description="Anything built from AI answers: its claims are found and linked, so it is flagged when one goes stale."
      actions={
        <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      }
    >
      <form onSubmit={submit} className="flex flex-col gap-3">
        <div className="grid gap-3 sm:grid-cols-[1fr_12rem]">
          <Field label="Title" htmlFor="doc-title">
            <Input id="doc-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} required />
          </Field>
          <Field label="Kind" htmlFor="doc-kind">
            <NativeSelect id="doc-kind" value={kind} onChange={(e) => setKind(e.target.value as DocumentKind)}>
              {Object.entries(DOCUMENT_KIND_LABELS).map(([id, label]) => (
                <option key={id} value={id}>{label}</option>
              ))}
            </NativeSelect>
          </Field>
        </div>
        <Field label="Text" htmlFor="doc-text">
          <Textarea id="doc-text" value={text} onChange={(e) => setText(e.target.value)} rows={4} required />
        </Field>
        <ErrorNote message={error} />
        <div>
          <Button type="submit" size="sm" disabled={busy || !title.trim() || !text.trim()}>
            <Plus aria-hidden /> {busy ? "Linking claims…" : "Register"}
          </Button>
        </div>
      </form>
    </Panel>
  );
}

export function ImpactPage() {
  const [version, setVersion] = useState(0);
  const impacts = useApi(workspaceApi.impacts, `i${version}`);
  const documents = useApi(workspaceApi.documents, `d${version}`);
  const [openClaim, setOpenClaim] = useState<string | null>(null);
  const [selectedDoc, setSelectedDoc] = useState<string | null>(null);
  const refresh = () => setVersion((value) => value + 1);

  const items = impacts.data?.items ?? [];
  const docs = documents.data?.documents ?? [];
  const firstOpen = openClaim ?? items.find((item) => item.counts.documents > 0)?.claim.passport_id ?? null;
  const selected = docs.find((doc) => doc.id === selectedDoc) ?? docs.find((doc) => doc.status === "needs_update") ?? docs[0] ?? null;

  return (
    <PageContainer wide>
      <PageHeader
        title="Downstream impact"
        description="A stale fact rarely stays in one answer. It ends up in proposals, projections and emails. Each claim here is traced through everything built on it, and every affected document gets a corrected version with sources."
      />
      <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
        <section className="flex min-w-0 flex-col gap-4" aria-label="Stale claims" data-tour="impact-list">
          <SectionTitle hint="Biggest blast radius first">Stale claims</SectionTitle>
          {impacts.loading && !impacts.data && <Loading />}
          <ErrorNote message={impacts.error} />
          {impacts.data && items.length === 0 && <EmptyState>No stale claims yet. Check an answer to start.</EmptyState>}
          <ul className="flex flex-col gap-3">
            {items.map((report) => (
              <ImpactCard
                key={report.claim.passport_id}
                report={report}
                open={firstOpen === report.claim.passport_id}
                onToggle={() => setOpenClaim(firstOpen === report.claim.passport_id ? "" : report.claim.passport_id)}
              />
            ))}
          </ul>
        </section>
        <section className="flex min-w-0 flex-col gap-4" aria-label="Documents" data-tour="documents">
          <SectionTitle hint={docs.length ? `${docs.length} registered` : undefined}>Documents</SectionTitle>
          {documents.loading && !documents.data && <Loading />}
          <ErrorNote message={documents.error} />
          <ul className="flex flex-col gap-1.5">
            {docs.map((doc) => (
              <li key={doc.id}>
                <button
                  type="button"
                  onClick={() => setSelectedDoc(doc.id)}
                  aria-pressed={selected?.id === doc.id}
                  className={cn(
                    "flex w-full flex-wrap items-center gap-2 rounded-lg border px-3 py-2 text-left text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    selected?.id === doc.id ? "border-foreground/40 bg-muted/60" : "hover:bg-muted/40",
                  )}
                >
                  <FileText className="size-4 text-muted-foreground" aria-hidden />
                  <span className="min-w-0 flex-1 truncate font-medium">{doc.title}</span>
                  <span className="text-xs text-muted-foreground">{DOCUMENT_KIND_LABELS[doc.kind]}</span>
                  {doc.revisions.length > 0 && (
                    <span className="text-xs text-muted-foreground">· {doc.revisions.length} revision{doc.revisions.length === 1 ? "" : "s"}</span>
                  )}
                  <StatusPill status={doc.status} />
                </button>
              </li>
            ))}
          </ul>
          {documents.data && docs.length === 0 && <EmptyState>No documents yet. Register one below.</EmptyState>}
          {selected && <DocumentDetail key={`${selected.id}-${selected.updated_at}`} document={selected} onChanged={refresh} />}
          <NewDocument onCreated={refresh} />
        </section>
      </div>
    </PageContainer>
  );
}
