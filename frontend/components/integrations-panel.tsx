"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Panel, Tabs } from "@/components/ui-kit";
import { API_URL } from "@/lib/api";

type Way = "mcp" | "stdio" | "guard" | "webhook";

const WAYS: { id: Way; label: string }[] = [
  { id: "mcp", label: "MCP (HTTP)" },
  { id: "stdio", label: "MCP (stdio)" },
  { id: "guard", label: "Answer guard" },
  { id: "webhook", label: "Webhook" },
];

function snippet(way: Way): { intro: string; code: string } {
  switch (way) {
    case "mcp":
      return {
        intro:
          "Any MCP client (Claude, IDE agents, agent frameworks) can discover ShelfLife's tools: verify_answer, impact_of_claim, stale_claims, register_document, link_claims, get_claim, watchlist, autopilot and list_policies. The agent checks its own answer before replying.",
        code: JSON.stringify({ mcpServers: { shelflife: { type: "http", url: `${API_URL}/mcp` } } }, null, 2),
      };
    case "stdio":
      return {
        intro: "For clients that launch tool servers themselves. Same tools, run in-process against the same workspace.",
        code: JSON.stringify(
          {
            mcpServers: {
              shelflife: { command: "uv", args: ["run", "--directory", "backend", "python", "-m", "app.mcp_stdio"] },
            },
          },
          null,
          2,
        ),
      };
    case "guard":
      return {
        intro:
          "Put ShelfLife between your model and your users: one call returns the advice (show, warn or withhold) and a corrected answer with sources.",
        code: `const result = await fetch("${API_URL}/api/verify", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ answer, question, policy_id: "developer" }),
}).then((r) => r.json());

const shown = result.guard.action === "show" ? answer : result.corrected_answer;`,
      };
    case "webhook":
      return {
        intro:
          "Set ALERT_WEBHOOK_URL and every stale finding is pushed to your system, including what each newly stale claim affects downstream (stale_claim_impact).",
        code: `{
  "event": "stale_claim_impact",
  "claim": { "passport_id": "CLM-…", "text": "…", "current_value": "…" },
  "severity": "high",
  "counts": { "claims": 3, "documents": 2, "answers": 1, "total": 6 },
  "documents": [{ "id": "…", "title": "Hosting proposal", "kind": "proposal" }]
}`,
      };
  }
}

export function IntegrationsPanel() {
  const [way, setWay] = useState<Way>("mcp");
  const [copied, setCopied] = useState(false);
  const { intro, code } = snippet(way);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  return (
    <Panel
      title="Use ShelfLife from other apps and agents"
      description="ShelfLife runs as a service with three faces: a tool server for AI agents (MCP), a guard in front of any app's answers, and an autonomous agent that keeps everything current on its own."
      className="lg:col-span-2"
      data-tour="integrations"
    >
      <Tabs tabs={WAYS} value={way} onChange={setWay} label="Integration" />
      <p className="text-sm leading-6 text-muted-foreground">{intro}</p>
      <div className="relative">
        <pre className="overflow-x-auto rounded-lg bg-muted px-3 py-2.5 pr-20 font-mono text-xs leading-5">{code}</pre>
        <Button size="sm" variant="outline" className="absolute top-2 right-2" onClick={copy}>
          {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
    </Panel>
  );
}
