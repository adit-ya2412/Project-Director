import { AlertTriangle, Check, Loader2, Scissors, Sparkles } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Disclosure } from "@/components/Disclosure";
import { formatDuration } from "@/lib/format";
import type { ScriptPreflightResponse, ScriptRewriteResponse } from "@/lib/types";

export function ScriptPreflightPanel({
  result,
  checking,
  error,
  stale,
  needsName,
  styleLabel,
  targetShotDurationS,
  onApplyAll,
  onApplyOne,
  onRewrite,
  rewriting,
  rewrite,
  rewriteError,
  onUseRewrite,
  onDismissRewrite,
}: {
  result: ScriptPreflightResponse | null;
  checking: boolean;
  error: string | null;
  stale: boolean;
  needsName: boolean;
  styleLabel: string;
  targetShotDurationS: number | null;
  onApplyAll: () => void;
  onApplyOne: (index: number) => void;
  onRewrite: () => void;
  rewriting: boolean;
  rewrite: ScriptRewriteResponse | null;
  rewriteError: string | null;
  onUseRewrite: () => void;
  onDismissRewrite: () => void;
}) {
  if (needsName) {
    return (
      <p className="text-xs text-muted-foreground">
        Name the project to check this script against {styleLabel}.
      </p>
    );
  }

  if (error && !result) {
    return (
      <Alert variant="destructive">
        <AlertTriangle className="h-4 w-4" />
        <AlertTitle>Could not check the script</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  if (!result) {
    return (
      <p className="flex items-center gap-2 text-xs text-muted-foreground">
        {checking ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
        Checking this script against {styleLabel}…
      </p>
    );
  }

  const avg = result.estimated_average_shot_duration_s;
  const stats = `${result.fragment_count} possible shot${result.fragment_count === 1 ? "" : "s"} · ~${formatDuration(result.estimated_total_duration_s)} · ${avg.toFixed(2)}s/shot`;
  const target =
    targetShotDurationS != null ? ` · ${styleLabel} wants ~${targetShotDurationS.toFixed(2)}s/shot` : "";

  return (
    <div className="space-y-3">
      {error && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Could not check the script</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        {checking ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : result.passed ? (
          <Badge variant="success">Fits {styleLabel}</Badge>
        ) : (
          <Badge variant="destructive">Won't cut as {styleLabel}</Badge>
        )}
        <span>
          {stats}
          {target}
        </span>
        {stale && <span className="text-warning">Rechecking your edits…</span>}
      </div>

      {result.warnings.map((w) => (
        <Alert key={w} variant="warning">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{w}</AlertDescription>
        </Alert>
      ))}

      {!result.passed && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>This script cannot reach {styleLabel}'s pace</AlertTitle>
          <AlertDescription>
            <ul className="list-disc space-y-1 pl-4">
              {result.violations.map((v) => (
                <li key={v}>{v}</li>
              ))}
            </ul>
            {result.punctuation_cannot_fix.length > 0 && (
              <ul className="mt-2 list-disc space-y-1 pl-4">
                {result.punctuation_cannot_fix.map((v) => (
                  <li key={v}>{v}</li>
                ))}
              </ul>
            )}
          </AlertDescription>
        </Alert>
      )}

      {result.passed && (
        <Alert variant="success">
          <Check className="h-4 w-4" />
          <AlertTitle>This script can be cut in {styleLabel}</AlertTitle>
          <AlertDescription>
            Planning will still write the shots — this only checks that the punctuation can
            physically support the pace.
          </AlertDescription>
        </Alert>
      )}

      {result.suitability && !result.suitability.suitable && (
        <Alert variant="warning">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>{styleLabel} may be a poor fit for this subject</AlertTitle>
          <AlertDescription>
            <p>{result.suitability.reason}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Advisory only — it will not block generate. Switch style if the tone is wrong.
            </p>
          </AlertDescription>
        </Alert>
      )}

      {result.suggested_breaks.length > 0 && (
        <div className="space-y-2 rounded-md border border-border p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-medium">
              {result.suggested_breaks.length} suggested break
              {result.suggested_breaks.length === 1 ? "" : "s"}
            </p>
            <Button
              type="button"
              size="sm"
              onClick={onApplyAll}
              disabled={stale || checking}
            >
              <Scissors className="h-3.5 w-3.5" />
              {result.suggestions_would_pass
                ? "Apply all — this should pass"
                : "Apply all suggested breaks"}
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Inserts punctuation only. Your words stay the same. A comma or full stop at these
            points gives Fast-cut more shots to work with.
          </p>
          {result.further_suggestions_available && (
            <p className="text-xs text-warning">
              More breaks exist past this list — apply these, then the check will propose the next round.
            </p>
          )}
          <Disclosure summary={`Preview ${result.suggested_breaks.length} insertion${result.suggested_breaks.length === 1 ? "" : "s"}`}>
            <ul className="space-y-2">
              {result.suggested_breaks.map((s, i) => (
                <li key={`${s.offset}-${s.mark}-${i}`} className="flex items-start justify-between gap-2">
                  <div>
                    <span className="text-foreground">
                      {s.preview_before}
                      <span className="rounded bg-primary/20 px-0.5 text-primary">{s.mark}</span>
                      {s.preview_after}
                    </span>
                    <div className="mt-0.5 text-[11px] text-muted-foreground">{s.reason}</div>
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    className="shrink-0"
                    disabled={stale || checking}
                    onClick={() => onApplyOne(i)}
                  >
                    Insert {s.mark === "." ? "period" : "comma"}
                  </Button>
                </li>
              ))}
            </ul>
          </Disclosure>
        </div>
      )}

      {!result.passed && (
        <div className="space-y-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={onRewrite}
            disabled={rewriting || checking || stale}
          >
            {rewriting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" />
            )}
            {rewriting ? "Rewriting…" : "Rewrite into shorter lines"}
          </Button>
          {rewriteError && <p className="text-xs text-destructive">{rewriteError}</p>}
          {rewrite?.accepted && rewrite.rewritten_script && (
            <div className="space-y-2 rounded-md border border-border p-3">
              <p className="text-sm font-medium">
                Rewrite preview · {rewrite.original_fragment_count} → {rewrite.rewritten_fragment_count} shots
                {rewrite.feasibility
                  ? rewrite.feasibility.passed
                    ? " · would pass"
                    : " · still would not pass"
                  : ""}
              </p>
              <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-md bg-black/30 p-2 font-mono text-xs">
                {rewrite.rewritten_script}
              </pre>
              <div className="flex gap-2">
                <Button type="button" size="sm" onClick={onUseRewrite}>
                  Use this version
                </Button>
                <Button type="button" size="sm" variant="ghost" onClick={onDismissRewrite}>
                  Discard
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
