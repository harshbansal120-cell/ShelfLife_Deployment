"use client";

import { useState, type FormEvent, type ReactNode } from "react";
import { CircleAlert, History, LoaderCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, generateStaleAnswer } from "@/lib/api";

const MAX_ANSWER_CHARS = 20_000;
const MAX_QUESTION_CHARS = 2_000;

// Questions only. The answers come from the model, so no facts are stored here.
const EXAMPLES = [
  {
    label: "AI pricing and leadership",
    question:
      "How much does ChatGPT Plus cost per month, who is the CEO of OpenAI, and what is its newest model?",
  },
  {
    label: "Software versions",
    question:
      "What is the latest stable version of Python, and which older versions are no longer supported?",
  },
  {
    label: "Laws and officials",
    question:
      "What is the US federal minimum wage, and who chairs the Federal Reserve right now?",
  },
];

function OptionSwitch({
  id,
  label,
  help,
  checked,
  onChange,
}: {
  id: string;
  label: string;
  help: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <div className="flex items-start gap-2.5">
      <Switch
        id={id}
        className="mt-0.5"
        checked={checked}
        aria-labelledby={`${id}-label`}
        aria-describedby={`${id}-help`}
        onCheckedChange={(value) => onChange(value)}
      />
      <div className="flex flex-col gap-0.5">
        <Label id={`${id}-label`} htmlFor={id}>
          {label}
        </Label>
        <span id={`${id}-help`} className="max-w-sm text-xs text-muted-foreground">
          {help}
        </span>
      </div>
    </div>
  );
}

interface CheckFormProps {
  question: string;
  answer: string;
  deep: boolean;
  useCache: boolean;
  error: string | null;
  submitting: boolean;
  onQuestionChange: (value: string) => void;
  onAnswerChange: (value: string) => void;
  onDeepChange: (value: boolean) => void;
  onUseCacheChange: (value: boolean) => void;
  // Replaces the example questions, e.g. with demo scenarios.
  examples?: ReactNode;
  // Shown under the answer box, e.g. the context picker.
  extra?: ReactNode;
  onSubmit: () => void;
}

export function CheckForm({
  question,
  answer,
  deep,
  useCache,
  error,
  submitting,
  onQuestionChange,
  onAnswerChange,
  onDeepChange,
  onUseCacheChange,
  onSubmit,
  examples,
  extra,
}: CheckFormProps) {
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [generatedBy, setGeneratedBy] = useState<string | null>(null);

  async function generate(text: string) {
    setGenerating(true);
    setGenerateError(null);
    setGeneratedBy(null);
    try {
      const generated = await generateStaleAnswer(text.trim());
      onAnswerChange(generated.answer);
      setGeneratedBy(
        generated.is_fallback ? `${generated.model} (fallback)` : generated.model,
      );
    } catch (caught) {
      setGenerateError(
        caught instanceof ApiError ? caught.message : "The answer couldn't be generated.",
      );
    } finally {
      setGenerating(false);
    }
  }

  function runExample(text: string) {
    onQuestionChange(text);
    void generate(text);
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (answer.trim()) onSubmit();
  }

  const shownError = error ?? generateError;
  const nearLimit = answer.length > MAX_ANSWER_CHARS * 0.9;

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-col gap-7 rounded-2xl border bg-card p-5 shadow-[0_1px_2px_oklch(0_0_0/0.04)] sm:p-7"
    >
      <div className="flex flex-col gap-2">
        <Label htmlFor="question">
          Question <span className="font-normal text-muted-foreground">(optional)</span>
        </Label>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input
            id="question"
            value={question}
            maxLength={MAX_QUESTION_CHARS}
            placeholder="What was the AI asked?"
            className="h-9"
            onChange={(event) => onQuestionChange(event.target.value)}
          />
          <Button
            type="button"
            variant="outline"
            size="lg"
            disabled={!question.trim() || generating}
            onClick={() => generate(question)}
          >
            {generating ? (
              <LoaderCircle className="motion-safe:animate-spin" aria-hidden />
            ) : (
              <History aria-hidden />
            )}
            Generate with old model
          </Button>
        </div>
        {examples ?? <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="mr-1 text-muted-foreground">Try an example:</span>
          {EXAMPLES.map((example) => (
            <Button
              key={example.label}
              type="button"
              variant="ghost"
              size="sm"
              disabled={generating}
              className="rounded-full border bg-surface px-3 text-foreground/85 hover:border-brand/50 hover:bg-brand-soft hover:text-foreground"
              onClick={() => runExample(example.question)}
            >
              {example.label}
            </Button>
          ))}
        </div>}
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex items-baseline justify-between gap-3">
          <Label htmlFor="answer">AI answer</Label>
          {generatedBy && (
            <span className="truncate text-xs text-muted-foreground">
              Written from memory by {generatedBy}
            </span>
          )}
        </div>
        <Textarea
          id="answer"
          data-tour="answer-input"
          value={answer}
          maxLength={MAX_ANSWER_CHARS}
          placeholder="Paste an answer from any AI model."
          aria-busy={generating}
          className="min-h-56 resize-y text-base leading-7 md:text-[15px]"
          onChange={(event) => {
            setGeneratedBy(null);
            onAnswerChange(event.target.value);
          }}
        />
        {nearLimit && (
          <p className="text-right text-xs text-muted-foreground">
            {answer.length.toLocaleString()} of {MAX_ANSWER_CHARS.toLocaleString()} characters
          </p>
        )}
      </div>

      {extra}

      {shownError && (
        <p
          role="alert"
          className="flex items-start gap-2 rounded-lg border bg-muted/50 px-3 py-2.5 text-sm"
        >
          <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          {shownError}
        </p>
      )}

      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="flex flex-col gap-3">
          <OptionSwitch
            id="deep"
            label="Deep verify"
            help="Searches more thoroughly and uses twice the Tavily credits."
            checked={deep}
            onChange={onDeepChange}
          />
          <OptionSwitch
            id="use-cache"
            label="Use Bifrost cache"
            help="Repeat calls are answered from the cache. Turn off to make every call reach a provider."
            checked={useCache}
            onChange={onUseCacheChange}
          />
        </div>
        <Button
          type="submit"
          size="lg"
          data-tour="check-button"
          className="h-10 px-5"
          disabled={!answer.trim() || submitting || generating}
        >
          {submitting && (
            <LoaderCircle className="motion-safe:animate-spin" aria-hidden />
          )}
          Check freshness
        </Button>
      </div>
    </form>
  );
}
