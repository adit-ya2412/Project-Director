import { useEffect } from "react";
import {
  useNavigate,
  useParams,
  useSearchParams,
  Link,
} from "react-router-dom";
import { CheckCircle2, Circle, LoaderCircle, RotateCcw } from "lucide-react";
import { useProgress, useProject, useRenderProject } from "@/lib/queries";
import { stepLabel, stepIndex, isPreApproval, STEP_ORDER } from "@/lib/steps";
import { formatCostCents, formatDuration } from "@/lib/format";
import { translateError } from "@/lib/errors";
import { ErrorNotice } from "@/components/ErrorNotice";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Progress as ProgressBar } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { AssetSourceBadge } from "@/components/AssetSourceBadge";
import { shotAssetSource } from "@/lib/asset-source";
import { useToast } from "@/components/ui/toast";
import type { ShotBindingState } from "@/lib/types";

const PRE_APPROVAL_STEPS = STEP_ORDER.slice(
  0,
  STEP_ORDER.indexOf("await_approval") + 1,
);
const POST_APPROVAL_STEPS = STEP_ORDER.slice(
  STEP_ORDER.indexOf("resolve_assets_generate"),
);

const SHOT_STATE_LABEL: Record<string, string> = {
  pending: "Pending",
  awaiting_generation: "Generating…",
  resolved: "Found",
  generated: "Generated",
  failed: "Failed",
};

const SHOT_STATE_VARIANT: Record<
  string,
  "secondary" | "success" | "destructive" | "warning"
> = {
  pending: "secondary",
  awaiting_generation: "warning",
  resolved: "success",
  generated: "success",
  failed: "destructive",
};

function StageList({
  steps,
  currentStep,
}: {
  steps: readonly string[];
  currentStep: string | null;
}) {
  const currentIdx = stepIndex(currentStep);
  return (
    <ol className="space-y-3">
      {steps.map((step) => {
        const idx = stepIndex(step);
        const done = currentIdx !== -1 && currentIdx > idx;
        const current = idx === currentIdx;
        return (
          <li key={step} className="flex items-center gap-3">
            {done && <CheckCircle2 className="h-5 w-5 shrink-0 text-success" />}
            {current && (
              <LoaderCircle className="h-5 w-5 shrink-0 animate-spin text-primary" />
            )}
            {!done && !current && (
              <Circle className="h-5 w-5 shrink-0 text-muted-foreground/40" />
            )}
            <span
              className={
                current
                  ? "font-medium text-foreground"
                  : done
                    ? "text-foreground"
                    : "text-muted-foreground"
              }
            >
              {stepLabel(step)}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

export function Progress() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { toast } = useToast();
  const { data: project } = useProject(projectId);
  const { data: progress, isLoading } = useProgress(projectId);
  const renderProject = useRenderProject(projectId ?? "");
  // Carries which correction (voice/music/render) sent us here, if any -
  // see `Result.tsx`'s own `CORRECTION_LABEL` for why: a trigger is
  // fire-and-forget, so the only place that can show a truthful "done"
  // confirmation is wherever the human actually lands once it's real.
  const pendingCorrection = searchParams.get("pending");

  // The approval/review/result screens are where a human acts; once the
  // backend reaches one of those states, move there automatically rather
  // than leaving them stranded on a progress screen with nothing to poll
  // toward.
  //
  // Deliberately `workflow_state`, not `progress.status`: `project.status`
  // is set to AWAITING_APPROVAL/AWAITING_REVIEW the moment either gate is
  // first hit, but nothing resets it away again until the run reaches a
  // LATER terminal state (RenderStep only sets RENDERING at the very end,
  // after the slow ffmpeg work) - so it stays stuck reporting the gate a
  // human already approved/fixed for the entire narration/generate/render
  // window that follows. `workflow_state` (the workflow run's own state)
  // doesn't have this gap: it flips back to "running" the instant a
  // resume begins (`app/workflow/trigger.py`'s `_claim_or_join`), which is
  // exactly why the engine's own code calls it "the source of truth in
  // /progress" in its comment beside where AWAITING_APPROVAL is set.
  // Without this fix, clicking Approve bounced straight back to /review
  // (status still said "awaiting_approval") for the whole render.
  useEffect(() => {
    if (!progress || !projectId) return;
    if (
      progress.workflow_state === "awaiting_approval" ||
      progress.workflow_state === "awaiting_review"
    )
      navigate(`/projects/${projectId}/review`, { replace: true });
    else if (progress.workflow_state === "completed")
      navigate(
        `/projects/${projectId}/result${pendingCorrection ? `?corrected=${pendingCorrection}` : ""}`,
        { replace: true },
      );
  }, [progress, projectId, navigate, pendingCorrection]);

  if (isLoading || !progress) {
    return (
      <div className="mx-auto max-w-2xl space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  const preApproval = isPreApproval(progress.current_step);
  // Same reasoning as the redirect effect above: `workflow_state`, not the
  // lagging `project.status`, is what actually reflects "still failed
  // right now" once a human has resumed a fix.
  const isFailed = progress.workflow_state === "failed";

  function handleRetry() {
    renderProject.mutate(undefined, {
      onError: () =>
        toast({
          title: "Retry failed to start",
          description: "Check the connection and try again.",
          variant: "destructive",
        }),
    });
    toast({
      title: "Retrying…",
      description: "Resuming from the failed stage.",
    });
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold">{project?.name ?? "Project"}</h1>
        <p className="text-sm text-muted-foreground">
          {preApproval ? "Planning your video" : "Generating your video"}
        </p>
      </div>

      {isFailed && (
        <ErrorNotice
          message={project?.error || "The pipeline stopped unexpectedly."}
          extraAction={
            <Button size="sm" className="mt-2" onClick={handleRetry}>
              <RotateCcw className="h-3.5 w-3.5" />
              Retry from where it stopped
            </Button>
          }
        />
      )}

      {preApproval ? (
        <Card>
          <CardHeader>
            <CardTitle>Building the plan</CardTitle>
            <CardDescription>
              Shots don't exist yet, so progress is stage-by-stage. This usually
              takes 5-15 minutes.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <StageList
              steps={PRE_APPROVAL_STEPS}
              currentStep={progress.current_step}
            />
            <div className="rounded-md border border-success/30 bg-success/10 p-3 text-sm">
              <span className="font-medium text-success">
                $0.00 spent so far.
              </span>{" "}
              <span className="text-muted-foreground">
                Nothing is generated and nothing is paid for until you approve
                the plan — that's the whole point of the review gate coming up
                next.
              </span>
            </div>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>Generating shots</CardTitle>
            <CardDescription>
              Narration is recorded, then any missing images are generated.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <StageList
              steps={POST_APPROVAL_STEPS}
              currentStep={progress.current_step}
            />

            <div>
              <div className="mb-1.5 flex items-center justify-between text-sm">
                <span>
                  {progress.completed_shots} / {progress.total_shots} shots done
                  {progress.failed_shots > 0 && (
                    <span className="text-destructive">
                      {" "}
                      ({progress.failed_shots} failed)
                    </span>
                  )}
                </span>
                <span className="font-medium">
                  {formatCostCents(progress.spent_cost_cents)} spent
                </span>
              </div>
              <ProgressBar value={(progress.progress ?? 0) * 100} />
            </div>

            {(progress.scenes?.length ?? 0) > 0 &&
              progress.shots.length === 0 && (
                <ul className="divide-y divide-border rounded-md border border-border">
                  {progress.scenes!.map((scene) => (
                    <li
                      key={scene.id}
                      className="flex items-start gap-3 p-2.5 text-sm"
                    >
                      <Badge
                        variant={
                          scene.failed_shots > 0
                            ? "destructive"
                            : scene.completed_shots === scene.total_shots
                              ? "success"
                              : "secondary"
                        }
                      >
                        {scene.completed_shots}/{scene.total_shots}
                      </Badge>
                      <p className="min-w-0 flex-1 truncate text-foreground">
                        {scene.title || scene.id}
                      </p>
                      {scene.failed_shots > 0 && (
                        <span className="text-xs text-destructive">
                          {scene.failed_shots} failed
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              )}

            {progress.shots.length > 0 && (
              <ul className="divide-y divide-border rounded-md border border-border">
                {progress.shots.map((shot) => {
                  const translated = translateError(shot.last_error);
                  return (
                    <li
                      key={shot.shot_id}
                      className="flex items-start gap-3 p-2.5 text-sm"
                    >
                      <Badge
                        variant={
                          SHOT_STATE_VARIANT[shot.state as ShotBindingState] ??
                          "secondary"
                        }
                      >
                        {SHOT_STATE_LABEL[shot.state as ShotBindingState] ??
                          shot.state}
                      </Badge>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-foreground">
                          {shot.says ?? shot.intent}
                        </p>
                        {translated && (
                          <p className="text-xs text-destructive">
                            {translated.headline}
                          </p>
                        )}
                      </div>
                      {(shot.asset || shot.clip) && (
                        <AssetSourceBadge source={shotAssetSource(shot)} />
                      )}
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {formatDuration(shot.duration_s)}
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </CardContent>
        </Card>
      )}

      <div className="flex justify-between">
        <Button asChild variant="ghost" size="sm">
          <Link to="/">Back to projects</Link>
        </Button>
        {progress.workflow_state === "awaiting_review" && (
          <Button asChild size="sm">
            <Link to={`/projects/${projectId}/review`}>Review now</Link>
          </Button>
        )}
      </div>
    </div>
  );
}
