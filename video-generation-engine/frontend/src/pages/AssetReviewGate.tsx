import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Copy,
  Download,
  Film,
  ImagePlus,
  Lock,
  Play,
  RefreshCw,
  Sparkles,
  Volume2,
  VolumeX,
} from "lucide-react";
import {
  useProgress,
  useTimeline,
  useApproveTimeline,
  useApproveScene,
  useOverrideShot,
  useGenerateShotImage,
  useGenerateShotVideo,
  useRenderDraft,
  useRegenerateFailedInScene,
  useSceneShots,
  useClearShotSfxCue,
} from "@/lib/queries";
import {
  shotAssetUrl,
  shotClipUrl,
  draftVideoUrl,
  pollShotVideo,
  promptExportUrl,
  fetchPromptExportText,
  ApiError,
} from "@/lib/api";
import { formatCostCents, formatDuration } from "@/lib/format";
import { translateError } from "@/lib/errors";
import { assetSourceFromDetail } from "@/lib/asset-source";
import { CAMERA_LABEL, TRANSITION_LABEL } from "@/lib/styles";
import { AssetSourceBadge } from "@/components/AssetSourceBadge";
import { ResolutionWarningBadge } from "@/components/ResolutionWarning";
import { computeResolutionWarning, frameAspectClass } from "@/lib/resolution";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { OverrideDialog } from "@/components/OverrideDialog";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import {
  SCENE_GROUP_SHOT_THRESHOLD,
  type Camera,
  type SceneProgress,
  type Shot,
  type ShotAssetDetail,
  type ShotClipDetail,
  type ShotProgress,
} from "@/lib/types";

// P3a: which half of a `split_frame` shot a control acts on. Every OTHER
// shot only ever has a `"primary"` — this union exists so a caller can
// never accidentally construct `"secondary"` for a shot whose backend
// binding has no such column meaning anything (`_OVERRIDE_PANELS`,
// `app/api/projects.py`, 400s exactly that case).
type Panel = "primary" | "secondary";

// Mirrors `_TERMINAL_SHOT_STATES` in `app/api/projects.py` exactly — a
// shot counts as filled when search found it, a human overrode it, or it
// was generated (on demand here, or by the pipeline). Approval is blocked
// server-side until every shot is in one of these two states (Task 2 of
// the one-gate redesign), so the button below mirrors that check
// client-side rather than making a human discover it via a 400.
const TERMINAL_STATES = new Set(["resolved", "generated"]);

function isFilled(shot: ShotProgress): boolean {
  return TERMINAL_STATES.has(shot.state);
}

/** P3a: the same "filled" check as `isFilled`, but for whichever panel a
 * control actually targets — the override dialog's own copy ("replaces
 * the current image" vs "locks the shot") has to describe the panel
 * being uploaded to, not the shot's primary state, or a bottom-panel
 * upload on a shot whose TOP panel already resolved would wrongly say
 * "replaces" for a bottom panel that has nothing yet. */
function isPanelFilled(shot: ShotProgress, panel: Panel): boolean {
  if (panel === "secondary") {
    return !!shot.secondary?.state && TERMINAL_STATES.has(shot.secondary.state);
  }
  return isFilled(shot);
}

function GenerateDialog({
  shot,
  open,
  onOpenChange,
  onConfirm,
  isPending,
}: {
  shot: ShotProgress;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (prompt: string) => void;
  isPending: boolean;
}) {
  const [prompt, setPrompt] = useState(shot.prompt);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {shot.state === "resolved"
              ? "Edit prompt and generate"
              : "Generate this shot"}
          </DialogTitle>
          <DialogDescription>
            The prompt is what the image is generated from — edit it if the last
            attempt (or the plan's own guess) produced the wrong picture.
            Generating creates a new image and adds to this project's spend,
            unless it's an exact repeat of a prompt already generated for this
            shot.
          </DialogDescription>
        </DialogHeader>
        <Textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          className="min-h-[120px]"
        />
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={isPending || !prompt.trim()}
            onClick={() => onConfirm(prompt.trim())}
          >
            {isPending ? "Generating…" : "Generate (may cost money)"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ShotImage({
  projectId,
  shotId,
  panel,
  asset,
  clip,
  state,
  camera,
  onExpand,
}: {
  projectId: string;
  shotId: string;
  // P3a: which panel this instance renders — `"primary"` renders and
  // behaves exactly as this component always has (same URL, same
  // props); `"secondary"` is new and only ever passed for a split_frame
  // shot's bottom panel.
  panel: Panel;
  asset: ShotAssetDetail | null;
  clip: ShotClipDetail | null;
  state: string | null;
  camera: Camera | undefined;
  onExpand: () => void;
}) {
  const { data: timeline } = useTimeline(projectId);
  const canvasWidth = timeline?.metadata.resolution?.[0];
  const canvasHeight = timeline?.metadata.resolution?.[1];
  const [errored, setErrored] = useState(false);
  const [naturalSize, setNaturalSize] = useState<{
    width: number;
    height: number;
  } | null>(null);
  const source = assetSourceFromDetail(asset, clip);
  const hasImage = (asset || clip) && !errored;
  // `shotAssetUrl` is the same URL string before and after an
  // override/regenerate — an already-mounted `<img>` has no reason to
  // re-request it, so the browser just keeps showing the old bytes it
  // already painted (the backend's `Cache-Control: no-cache` only forces
  // revalidation on a NEW request; it does nothing if no request is ever
  // made). Keying on the bound asset/clip's own path forces React to
  // unmount and remount the element whenever the actual file changes.
  const mediaVersion = asset?.local_path ?? clip?.local_path ?? state;

  if (!hasImage) {
    return (
      <div className={`flex ${frameAspectClass(canvasWidth, canvasHeight)} w-36 shrink-0 flex-col items-center justify-center gap-1.5 rounded-md border border-dashed border-warning/40 bg-warning/5 p-2 text-center`}>
        <Sparkles className="h-5 w-5 text-warning" />
        <span className="text-xs text-warning">
          {state === "pending" || state == null
            ? "Still searching…"
            : "No picture yet"}
        </span>
      </div>
    );
  }

  // P3a: `/clip` (the endpoint that actually plays a bound motion clip)
  // has no `panel` param yet — see `ImageLightbox`'s own comment. A
  // secondary panel bound to a clip is real and playable server-side via
  // `ffprobe`/`ffmpeg` directly, just not through this frontend today, so
  // the "click to play" affordance is only honest for the primary.
  const isPlayableClip = panel === "primary" && Boolean(clip);
  return (
    <div className="w-36 shrink-0 space-y-1">
      <button
        type="button"
        onClick={onExpand}
        className="block cursor-zoom-in rounded-md focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label={isPlayableClip ? "Play clip" : "View larger image"}
      >
        <img
          key={mediaVersion}
          src={shotAssetUrl(projectId, shotId, panel)}
          alt=""
          className={`${frameAspectClass(canvasWidth, canvasHeight)} w-36 rounded-md border border-border object-cover transition-opacity hover:opacity-90`}
          onError={() => setErrored(true)}
          onLoad={(e) => {
            const img = e.currentTarget;
            setNaturalSize({
              width: img.naturalWidth,
              height: img.naturalHeight,
            });
          }}
        />
      </button>
      {isPlayableClip && (
        <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground">
          <Film className="h-3 w-3" /> Motion clip — click to play
        </span>
      )}
      {source === "uploaded" && naturalSize && (
        <ResolutionWarningBadge
          warning={computeResolutionWarning(
            naturalSize.width,
            naturalSize.height,
            camera,
            canvasWidth,
            canvasHeight,
          )}
        />
      )}
    </div>
  );
}

function ImageLightbox({
  projectId,
  target,
  open,
  onOpenChange,
}: {
  projectId: string;
  target: { shot: ShotProgress; panel: Panel } | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const shot = target?.shot ?? null;
  const panel = target?.panel ?? "primary";
  const media =
    panel === "secondary"
      ? {
          asset: shot?.secondary?.asset ?? null,
          clip: shot?.secondary?.clip ?? null,
          state: shot?.secondary?.state ?? null,
        }
      : { asset: shot?.asset ?? null, clip: shot?.clip ?? null, state: shot?.state ?? null };
  // P3a: `GET .../clip` (the endpoint that streams REAL playable video
  // bytes, R10) has no `panel` param on the backend today —
  // `get_shot_clip` always resolves the PRIMARY binding
  // (`_resolve_bound_media_path(session, binding)`, no `panel=`
  // forwarded). Extending it is a backend change this frontend-only
  // slice does not make, so a motion clip bound to the BOTTOM panel is
  // shown as `/asset`'s extracted still frame (which `get_shot_asset`
  // already does for any video-typed panel) rather than played — correct
  // and never a dead end, just less rich than the primary's own lightbox
  // until `/clip` learns `panel` too (a natural follow-up, not part of
  // this slice's brief).
  const isPlayableClip = panel === "primary" && Boolean(media.clip);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl border-none bg-transparent p-0 shadow-none">
        {shot && (
          <div className="space-y-2">
            {isPlayableClip ? (
              <video
                key={media.clip?.local_path ?? shot.shot_id}
                src={shotClipUrl(projectId, shot.shot_id)}
                controls
                autoPlay
                className="mx-auto max-h-[80vh] w-auto rounded-md border border-border bg-black"
              />
            ) : (
              <img
                key={media.asset?.local_path ?? media.clip?.local_path ?? media.state}
                src={shotAssetUrl(projectId, shot.shot_id, panel)}
                alt=""
                className="mx-auto max-h-[80vh] w-auto rounded-md border border-border object-contain"
              />
            )}
            <p className="rounded-md bg-background/90 p-2 text-center text-sm text-foreground">
              {shot.says ? `"${shot.says}"` : shot.intent}
            </p>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function DraftPlayer({
  projectId,
  seekToS,
  onSeekConsumed,
}: {
  projectId: string;
  seekToS: number | null;
  onSeekConsumed: () => void;
}) {
  const renderDraft = useRenderDraft(projectId);
  const { toast } = useToast();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [draftEpoch, setDraftEpoch] = useState(0);
  const [hasDraft, setHasDraft] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch(draftVideoUrl(projectId), {
      method: "GET",
      headers: { Range: "bytes=0-0" },
    })
      .then((res) => {
        if (!cancelled && res.ok) setHasDraft(true);
      })
      .catch(() => {
        if (!cancelled) setHasDraft(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, draftEpoch]);

  useEffect(() => {
    if (seekToS == null || !videoRef.current || !hasDraft) return;
    videoRef.current.currentTime = seekToS;
    void videoRef.current.play();
    onSeekConsumed();
  }, [seekToS, hasDraft, onSeekConsumed]);

  function handleRender() {
    renderDraft.mutate(undefined, {
      onSuccess: () => {
        setHasDraft(true);
        setDraftEpoch((n) => n + 1);
        toast({
          title: "Draft ready",
          description: "A 480p preview of the current plan.",
          variant: "success",
        });
      },
      onError: (err) =>
        toast({
          title: "Could not render draft",
          description:
            err instanceof ApiError ? String(err.detail) : "Try again.",
          variant: "destructive",
        }),
    });
  }

  return (
    <Card className="space-y-3 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-medium">Draft preview</h2>
          <p className="text-xs text-muted-foreground">
            A 480p cut of the current plan — the only way to judge pacing before
            you approve.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleRender}
          disabled={renderDraft.isPending}
        >
          <Film className="h-3.5 w-3.5" />
          {renderDraft.isPending
            ? "Rendering draft…"
            : hasDraft
              ? "Re-render draft"
              : "Render 480p draft"}
        </Button>
      </div>
      {hasDraft && (
        <video
          ref={videoRef}
          key={draftEpoch}
          src={`${draftVideoUrl(projectId)}?t=${draftEpoch}`}
          controls
          className="w-full rounded-md border border-border bg-black"
        />
      )}
    </Card>
  );
}

function SceneExpandedShots({
  projectId,
  sceneId,
  planByShot,
  videoPending,
  onExpand,
  onOverride,
  onGenerate,
  onGenerateVideo,
  onClearSfxCue,
  clearingSfxCueShotId,
}: {
  projectId: string;
  sceneId: string;
  planByShot: Map<string, Shot>;
  videoPending: ReadonlySet<string>;
  onExpand: (shot: ShotProgress, panel: Panel) => void;
  onOverride: (shot: ShotProgress, panel: Panel) => void;
  onGenerate: (shot: ShotProgress) => void;
  onGenerateVideo: (shot: ShotProgress) => void;
  onClearSfxCue: (shot: ShotProgress) => void;
  clearingSfxCueShotId: string | null;
}) {
  const { data, isLoading } = useSceneShots(projectId, sceneId);
  if (isLoading || !data) {
    return <Skeleton className="h-32 w-full" />;
  }
  return (
    <ul className="space-y-3">
      {data.shots.map((shot) => (
        <li key={shot.shot_id}>
          <ShotCard
            projectId={projectId}
            shot={shot}
            plan={planByShot.get(shot.shot_id)}
            videoPending={videoPending.has(shot.shot_id)}
            onExpand={(panel) => onExpand(shot, panel)}
            onOverride={(panel) => onOverride(shot, panel)}
            onGenerate={() => onGenerate(shot)}
            onGenerateVideo={() => onGenerateVideo(shot)}
            onClearSfxCue={() => onClearSfxCue(shot)}
            clearingSfxCue={clearingSfxCueShotId === shot.shot_id}
          />
        </li>
      ))}
    </ul>
  );
}

/** P3a: a `split_frame` shot's bottom panel, additive-only — rendered
 * exclusively when `shot.secondary` is non-null, so it can never appear
 * (or be reachable) for the overwhelming majority of shots. Deliberately
 * a separate block from `ShotCard`'s existing body rather than a
 * generalised "N panels" loop over that body: the primary keeps the
 * generate/regenerate-video controls this panel does not get (P3a is
 * scoped to upload only, matching what the backend's `panel` vocabulary
 * accepts today — `POST .../generate` has no `panel` param), and folding
 * both into one shape would either invent generate-for-secondary (out of
 * scope, no backend support) or hide that asymmetry behind a prop nobody
 * reading `ShotCard` would notice. */
function SecondaryPanelBlock({
  projectId,
  shot,
  camera,
  onExpand,
  onOverride,
}: {
  projectId: string;
  shot: ShotProgress;
  camera: Camera | undefined;
  onExpand: () => void;
  onOverride: () => void;
}) {
  const secondary = shot.secondary;
  if (!secondary) return null;
  const source = assetSourceFromDetail(secondary.asset, secondary.clip);
  const filled =
    secondary.state != null && TERMINAL_STATES.has(secondary.state);
  const flag = translateError(secondary.last_error);
  return (
    <div className="flex gap-4 border-t border-border pt-3">
      <ShotImage
        projectId={projectId}
        shotId={shot.shot_id}
        panel="secondary"
        asset={secondary.asset}
        clip={secondary.clip}
        state={secondary.state}
        camera={camera}
        onExpand={onExpand}
      />
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-muted-foreground">
            Bottom panel
          </span>
          {filled && <AssetSourceBadge source={source} />}
          {!filled && secondary.state !== "failed" && (
            <span className="inline-flex items-center gap-1 rounded-full border border-warning/30 bg-warning/10 px-2 py-0.5 text-xs font-medium text-warning">
              {secondary.state === "pending" || secondary.state == null
                ? "Still searching"
                : "Headed for generation"}
            </span>
          )}
        </div>
        <p className="text-xs text-muted-foreground">{secondary.prompt}</p>
        {flag && (
          <div className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning/10 p-2 text-xs text-warning-foreground/90">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
            <span>{flag.headline}</span>
          </div>
        )}
        <div className="flex flex-wrap gap-2 pt-1">
          <Button variant="outline" size="sm" onClick={onOverride}>
            <ImagePlus className="h-3.5 w-3.5" />
            {filled ? "Replace bottom panel" : "Upload bottom panel"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function ShotCard({
  projectId,
  shot,
  plan,
  videoPending,
  onExpand,
  onOverride,
  onGenerate,
  onGenerateVideo,
  onClearSfxCue,
  clearingSfxCue,
}: {
  projectId: string;
  shot: ShotProgress;
  plan: Shot | undefined;
  videoPending: boolean;
  onExpand: (panel: Panel) => void;
  onOverride: (panel: Panel) => void;
  onGenerate: () => void;
  onGenerateVideo: () => void;
  onClearSfxCue: () => void;
  clearingSfxCue: boolean;
}) {
  const source = assetSourceFromDetail(shot.asset, shot.clip);
  const flag = translateError(shot.last_error);
  const filled = isFilled(shot);
  const camera = plan?.camera;
  const transition = plan?.transition_out;
  const textCard = plan?.text_card?.trim() || null;
  const sfxCue = plan?.sfx_cue?.trim() || null;
  const planBits = [
    camera ? (CAMERA_LABEL[camera.movement] ?? camera.movement) : null,
    transition
      ? `out: ${TRANSITION_LABEL[transition.type] ?? transition.type}`
      : null,
    textCard ? `text card: “${textCard}”` : null,
  ].filter(Boolean);
  return (
    <Card className="space-y-3 p-3">
      <div className="flex gap-4">
        <ShotImage
          projectId={projectId}
          shotId={shot.shot_id}
          panel="primary"
          asset={shot.asset}
          clip={shot.clip}
          state={shot.state}
          camera={camera}
          onExpand={() => onExpand("primary")}
        />
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            {filled && <AssetSourceBadge source={source} />}
            {!filled && shot.state !== "failed" && (
              <span className="inline-flex items-center gap-1 rounded-full border border-warning/30 bg-warning/10 px-2 py-0.5 text-xs font-medium text-warning">
                {shot.state === "pending"
                  ? "Still searching"
                  : "Headed for generation"}
              </span>
            )}
            {shot.locked && (
              <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                <Lock className="h-3 w-3" /> Locked by you
              </span>
            )}
            <span className="text-xs text-muted-foreground">
              {formatDuration(shot.starts_at_s)}–
              {formatDuration((shot.starts_at_s ?? 0) + shot.duration_s)} (
              {shot.duration_s.toFixed(1)}s)
            </span>
          </div>
          {shot.says && <p className="text-sm text-foreground">"{shot.says}"</p>}
          <p className="text-xs text-muted-foreground">
            <span className="font-medium">{shot.intent}</span> — {shot.prompt}
          </p>
          {planBits.length > 0 && (
            <p className="text-xs text-muted-foreground">{planBits.join(" · ")}</p>
          )}
          {sfxCue && (
            <div className="flex items-center gap-2 rounded-md border border-border bg-muted/40 px-2 py-1.5 text-xs">
              <Volume2 className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1 text-muted-foreground">
                Sound effect (~6¢ when approved): “{sfxCue}”
              </span>
              <Button
                variant="ghost"
                size="sm"
                className="h-6 shrink-0 px-2 text-xs"
                onClick={onClearSfxCue}
                disabled={clearingSfxCue}
              >
                <VolumeX className="h-3.5 w-3.5" />
                {clearingSfxCue ? "Clearing…" : "Clear"}
              </Button>
            </div>
          )}

          {flag && (
            <div className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning/10 p-2 text-xs text-warning-foreground/90">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
              <span>{flag.headline}</span>
            </div>
          )}

          <div className="flex flex-wrap gap-2 pt-1">
            <Button variant="outline" size="sm" onClick={() => onOverride("primary")}>
              <ImagePlus className="h-3.5 w-3.5" />
              {filled ? "Replace image" : "Upload your own"}
            </Button>
            <Button variant="outline" size="sm" onClick={onGenerate}>
              <RefreshCw className="h-3.5 w-3.5" />
              {filled ? "Edit prompt & regenerate" : "Generate now"}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={onGenerateVideo}
              disabled={!filled || videoPending}
            >
              <Film className="h-3.5 w-3.5" />
              {videoPending
                ? "Generating video…"
                : shot.clip
                  ? "Regenerate video"
                  : "Generate video"}
            </Button>
          </div>
        </div>
      </div>
      {shot.secondary && (
        <SecondaryPanelBlock
          projectId={projectId}
          shot={shot}
          camera={camera}
          onExpand={() => onExpand("secondary")}
          onOverride={() => onOverride("secondary")}
        />
      )}
    </Card>
  );
}

/**
 * P0 (docs/plans/gate_panel_overrides.md): the bulk escape hatch for §1's
 * measured workflow — copy a prompt, generate it for free in a provider
 * whose quota is already paid for (Grok), upload the result via the
 * override button above instead of paying fal.ai. That workflow already
 * existed per-shot; on a 41-shot film it was 61 one-at-a-time copies, and
 * the parallax layer prompts (`layer_styled_prompt`) were never shown in
 * this UI at all. Two actions, not one, because they serve different
 * gestures: "Copy all" is the one-click paste-everywhere case (a single
 * clipboard write, matching the existing `CopyButton` idiom elsewhere in
 * this app, just fetched first since the text lives on the server);
 * "Download .txt" is a plain `<a download>` (no JS, no fetch) for
 * actually working through 60+ prompts in an editor rather than holding
 * them all in one clipboard entry at once.
 */
function ExportPromptsButton({ projectId }: { projectId: string }) {
  const { toast } = useToast();
  const [copying, setCopying] = useState(false);

  async function handleCopyAll() {
    setCopying(true);
    try {
      const text = await fetchPromptExportText(projectId);
      await navigator.clipboard.writeText(text);
      toast({
        title: "Prompts copied",
        description:
          "Every image prompt for this project is on your clipboard, in order. Also set your image provider's own aspect-ratio control — the words alone did not hold for every provider tested.",
        variant: "success",
      });
    } catch (err) {
      toast({
        title: "Could not copy prompts",
        description:
          err instanceof ApiError ? String(err.detail) : "Try again.",
        variant: "destructive",
      });
    } finally {
      setCopying(false);
    }
  }

  return (
    <div className="flex items-center gap-1">
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={handleCopyAll}
        disabled={copying}
      >
        <Copy className="h-3.5 w-3.5" />
        {copying ? "Copying…" : "Copy all prompts"}
      </Button>
      <Button type="button" variant="outline" size="sm" asChild>
        <a href={promptExportUrl(projectId)} download>
          <Download className="h-3.5 w-3.5" />
          Download .txt
        </a>
      </Button>
    </div>
  );
}

export function AssetReviewGate() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { toast } = useToast();
  const slimQuery = useProgress(projectId);
  const slim = slimQuery.data;
  const groupedLayout =
    !!slim &&
    slim.workflow_state !== "awaiting_review" &&
    slim.total_shots >= SCENE_GROUP_SHOT_THRESHOLD &&
    (slim.scenes?.length ?? 0) > 0;
  const expandQuery = useProgress(projectId, {
    expandShots: true,
    enabled: !!projectId && !!slim && !groupedLayout,
  });
  const progress = groupedLayout ? slim : (expandQuery.data ?? slim);
  const isLoading =
    slimQuery.isLoading ||
    (!groupedLayout && !!slim && expandQuery.isLoading && !expandQuery.data);
  const { data: timeline } = useTimeline(projectId);
  const approveTimeline = useApproveTimeline(projectId ?? "");
  const approveScene = useApproveScene(projectId ?? "");
  const overrideShot = useOverrideShot(projectId ?? "");
  const generateShot = useGenerateShotImage(projectId ?? "");
  const generateVideo = useGenerateShotVideo(projectId ?? "");
  const regenerateFailed = useRegenerateFailedInScene(projectId ?? "");
  const clearSfxCue = useClearShotSfxCue(projectId ?? "");
  const [overrideTarget, setOverrideTarget] = useState<
    { shot: ShotProgress; panel: Panel } | null
  >(null);
  const [generateTarget, setGenerateTarget] = useState<ShotProgress | null>(
    null,
  );
  const [videoTarget, setVideoTarget] = useState<ShotProgress | null>(null);
  const [videoPending, setVideoPending] = useState<Set<string>>(
    () => new Set(),
  );
  const [lightboxTarget, setLightboxTarget] = useState<
    { shot: ShotProgress; panel: Panel } | null
  >(null);
  const [confirmKind, setConfirmKind] = useState<
    "spend" | "remaining" | "scene" | "regenerate" | null
  >(null);
  const [pendingScene, setPendingScene] = useState<SceneProgress | null>(null);
  const [seekToS, setSeekToS] = useState<number | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const planByShot = useMemo(() => {
    const map = new Map<string, Shot>();
    if (timeline) {
      for (const scene of timeline.scenes) {
        for (const shot of scene.shots) map.set(shot.id, shot);
      }
    }
    return map;
  }, [timeline]);

  useEffect(() => {
    if (videoPending.size === 0 || !projectId) return;
    let cancelled = false;
    const tick = async () => {
      const still = new Set<string>();
      for (const shotId of videoPending) {
        try {
          const result = await pollShotVideo(projectId, shotId);
          if (cancelled) return;
          if (result.status === "pending") {
            still.add(shotId);
          } else if (result.status === "failed") {
            toast({
              title: "Video generation failed",
              description: result.error ?? "Try again.",
              variant: "destructive",
            });
          } else {
            toast({
              title: "Motion clip ready",
              description: "Click the thumbnail to play it.",
              variant: "success",
            });
          }
        } catch (err) {
          if (cancelled) return;
          if (err instanceof ApiError && err.status === 404) {
            continue;
          }
          still.add(shotId);
        }
      }
      if (!cancelled) {
        const same =
          still.size === videoPending.size &&
          [...still].every((id) => videoPending.has(id));
        if (!same) setVideoPending(still);
      }
    };
    const id = window.setInterval(() => void tick(), 2500);
    void tick();
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [videoPending, projectId, toast]);

  // Complementary to `Progress.tsx`'s own redirect: clicking Approve fires
  // the mutation and navigates to `/progress` immediately (fire-and-forget,
  // per the trigger contract), but the very FIRST poll from there can
  // legitimately still read `workflow_state: "awaiting_approval"` for one
  // beat if it lands before the approve call has actually been processed
  // server-side — bouncing straight back here. Without this effect,
  // nothing then ever notices the workflow has since moved on (this page
  // only reacts to props/queries, it never re-checks on its own), so a
  // human could be stuck looking at a stale review gate for an entire
  // render. This self-corrects within one more poll cycle instead.
  useEffect(() => {
    if (!progress || !projectId) return;
    if (progress.workflow_state === "completed") {
      navigate(`/projects/${projectId}/result`, { replace: true });
    } else if (
      progress.workflow_state &&
      progress.workflow_state !== "awaiting_approval" &&
      progress.workflow_state !== "awaiting_review"
    ) {
      navigate(`/projects/${projectId}/progress`, { replace: true });
    }
  }, [progress, projectId, navigate]);

  if (isLoading || !progress || !projectId) {
    return (
      <div className="mx-auto max-w-4xl space-y-3">
        <Skeleton className="h-8 w-64" />
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-32 w-full" />
        ))}
      </div>
    );
  }

  // Once the plan is already approved, `AwaitReviewStep`'s backstop is why
  // we're here — the pipeline paused only because some shot ended
  // `failed` after approval. There is nothing left to "approve" (that
  // already happened), and no separate "continue" button: fixing the
  // shot (override or generate) already resumes the workflow on its own.
  //
  // Deliberately `workflow_state`, not `progress.status`: nothing resets
  // `project.status` away from AWAITING_REVIEW when a fix resumes the
  // workflow (only a later terminal state like COMPLETED overwrites it),
  // so it would keep reporting the backstop for the entire
  // resolve_assets_generate/render window that follows a fix — hiding the
  // Approve button and filtering to failed-only shots long after there
  // are none left. `workflow_state` correctly flips back to "running" the
  // instant the resume begins (same fix as `Progress.tsx`'s redirect).
  const isBackstop = progress.workflow_state === "awaiting_review";
  const visibleShots = isBackstop
    ? progress.shots.filter((s) => s.state === "failed")
    : progress.shots;
  const unfilledShots = progress.shots.filter((s) => !isFilled(s));
  const canApprove = unfilledShots.length === 0;
  const confirmTotalCents =
    progress.spent_cost_cents + progress.estimated_cost_cents;
  const scenes = progress.scenes ?? [];
  const grouped =
    !isBackstop &&
    progress.total_shots >= SCENE_GROUP_SHOT_THRESHOLD &&
    scenes.length > 0;
  const remainingScenes = scenes.filter((s) => !s.approved);

  function submitApprove() {
    setConfirmKind(null);
    approveTimeline.mutate(
      confirmTotalCents > 0 ? confirmTotalCents : undefined,
      {
        onError: (err) =>
          toast({
            title: "Could not approve",
            description:
              err instanceof ApiError ? String(err.detail) : "Try again.",
            variant: "destructive",
          }),
      },
    );
    toast({
      title: "Approved",
      description: "Generating remaining images, then rendering.",
    });
    navigate(`/projects/${projectId}/progress`);
  }

  function handleApprove() {
    if (grouped && remainingScenes.length > 0) {
      setConfirmKind("remaining");
      return;
    }
    if (confirmTotalCents > 0) {
      setConfirmKind("spend");
      return;
    }
    submitApprove();
  }

  function handleRemainingConfirmed() {
    if (confirmTotalCents > 0) {
      setConfirmKind("spend");
      return;
    }
    submitApprove();
  }

  function handleApproveScene(scene: SceneProgress) {
    setPendingScene(scene);
    setConfirmKind("scene");
  }

  function submitSceneApprove() {
    if (!pendingScene) return;
    const sceneId = pendingScene.id;
    setConfirmKind(null);
    setPendingScene(null);
    approveScene.mutate(sceneId, {
      onSuccess: () =>
        toast({
          title: "Scene approved",
          description: "This cannot be undone.",
          variant: "success",
        }),
      onError: (err) =>
        toast({
          title: "Could not approve scene",
          description:
            err instanceof ApiError ? String(err.detail) : "Try again.",
          variant: "destructive",
        }),
    });
  }

  function handleRegenerateFailed(scene: SceneProgress) {
    setPendingScene(scene);
    setConfirmKind("regenerate");
  }

  function submitRegenerateFailed() {
    if (!pendingScene) return;
    const scene = pendingScene;
    setConfirmKind(null);
    setPendingScene(null);
    regenerateFailed.mutate(
      {
        sceneId: scene.id,
        confirmedCostCents: scene.regenerate_failed_cost_cents,
      },
      {
        onSuccess: (result) =>
          toast({
            title: "Regenerated",
            description: `${result.shot_ids.length} shot${result.shot_ids.length === 1 ? "" : "s"} · ${formatCostCents(result.estimated_cost_cents)}`,
            variant: "success",
          }),
        onError: (err) =>
          toast({
            title: "Could not regenerate",
            description:
              err instanceof ApiError ? String(err.detail) : "Try again.",
            variant: "destructive",
          }),
      },
    );
  }

  function toggleExpanded(sceneId: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(sceneId)) next.delete(sceneId);
      else next.add(sceneId);
      return next;
    });
  }

  function handleOverrideSubmit(
    shotId: string,
    file: File,
    description: string,
    panel: Panel,
  ) {
    overrideShot.mutate(
      { shotId, file, description: description || undefined, panel },
      {
        onSuccess: () => {
          toast({
            title: "Image saved",
            description:
              panel === "secondary"
                ? "This shot's bottom panel is locked to your image."
                : "This shot is locked to your image.",
            variant: "success",
          });
          setOverrideTarget(null);
        },
        onError: (err) =>
          toast({
            title: "Could not save image",
            description:
              err instanceof ApiError ? String(err.detail) : "Try again.",
            variant: "destructive",
          }),
      },
    );
  }

  function handleClearSfxCue(shot: ShotProgress) {
    clearSfxCue.mutate(shot.shot_id, {
      onSuccess: () =>
        toast({
          title: "Sound effect cleared",
          description: "This shot will get no diegetic sound.",
          variant: "success",
        }),
      onError: (err) =>
        toast({
          title: "Could not clear the sound effect",
          description:
            err instanceof ApiError ? String(err.detail) : "Try again.",
          variant: "destructive",
        }),
    });
  }

  function handleGenerateVideoConfirm() {
    if (!videoTarget) return;
    const shotId = videoTarget.shot_id;
    setVideoTarget(null);
    generateVideo.mutate(shotId, {
      onSuccess: (result) => {
        if (result.status === "pending") {
          setVideoPending((prev) => new Set(prev).add(shotId));
          toast({
            title: "Video generation started",
            description: "This takes a few minutes. The row will update.",
          });
        } else if (result.status === "completed") {
          toast({
            title: "Motion clip ready",
            description: "This shot already had a completed clip.",
            variant: "success",
          });
        } else {
          toast({
            title: "Video generation failed",
            description: result.error ?? "Try again.",
            variant: "destructive",
          });
        }
      },
      onError: (err) =>
        toast({
          title: "Could not generate video",
          description:
            err instanceof ApiError ? String(err.detail) : "Try again.",
          variant: "destructive",
        }),
    });
  }

  function handleGenerateConfirm(shot: ShotProgress, prompt: string) {
    generateShot.mutate(
      {
        shotId: shot.shot_id,
        prompt: prompt !== shot.prompt ? prompt : undefined,
      },
      {
        onSuccess: (result) => {
          toast({
            title: "Generated",
            description: result.cache_hit
              ? "Reused an image already generated for this exact prompt — free."
              : `Cost: ${formatCostCents(result.cost_cents)}`,
            variant: "success",
          });
          setGenerateTarget(null);
        },
        onError: (err) =>
          toast({
            title: "Could not generate",
            description:
              err instanceof ApiError ? String(err.detail) : "Try again.",
            variant: "destructive",
          }),
      },
    );
  }

  const approveButtonLabel =
    grouped && remainingScenes.length > 0
      ? "Approve all remaining"
      : "Approve and continue";

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div className="sticky top-14 z-30 -mx-4 flex flex-wrap items-center justify-between gap-3 border-b border-border bg-background/95 px-4 py-3 backdrop-blur">
        <div>
          <h1 className="text-lg font-semibold">
            {isBackstop ? "Fix what failed" : "Review the pictures"}
          </h1>
          <p className="text-sm text-muted-foreground">
            {isBackstop ? (
              <>
                {visibleShots.length} shot{visibleShots.length === 1 ? "" : "s"}{" "}
                need
                {visibleShots.length === 1 ? "s" : ""} a fix before the video
                can finish
              </>
            ) : grouped ? (
              <>
                {scenes.length} scenes · {progress.total_shots} shots ·{" "}
                {remainingScenes.length} still to approve ·{" "}
                <span className="font-medium text-success">
                  {formatCostCents(progress.spent_cost_cents)} spent so far
                </span>
                {progress.estimated_cost_cents > 0 && (
                  <>
                    {" "}
                    · ≈ {formatCostCents(progress.estimated_cost_cents)} to fill
                    the rest
                  </>
                )}
                {progress.budget_cap_cents > 0 && (
                  <> · cap {formatCostCents(progress.budget_cap_cents)}</>
                )}
              </>
            ) : (
              <>
                {progress.total_shots} shots · {unfilledShots.length} still{" "}
                {unfilledShots.length === 1 ? "needs" : "need"} a picture ·{" "}
                <span className="font-medium text-success">
                  {formatCostCents(progress.spent_cost_cents)} spent so far
                </span>
                {progress.estimated_cost_cents > 0 && (
                  <>
                    {" "}
                    · ≈ {formatCostCents(progress.estimated_cost_cents)} to fill
                    the rest
                  </>
                )}
                {progress.budget_cap_cents > 0 && (
                  <> · cap {formatCostCents(progress.budget_cap_cents)}</>
                )}
              </>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <ExportPromptsButton projectId={projectId} />
          {!isBackstop && (
            <Button
              size="lg"
              onClick={handleApprove}
              disabled={!canApprove}
              variant={
                grouped && remainingScenes.length > 0 ? "secondary" : "default"
              }
            >
              <CheckCircle2 className="h-4 w-4" />
              {approveButtonLabel}
            </Button>
          )}
        </div>
      </div>

      {!isBackstop && (
        <DraftPlayer
          projectId={projectId}
          seekToS={seekToS}
          onSeekConsumed={() => setSeekToS(null)}
        />
      )}

      {!isBackstop && unfilledShots.length > 0 && (
        <Card className="border-warning/30 bg-warning/5 p-3 text-sm">
          <span className="font-medium text-warning">
            {unfilledShots.length} shot{unfilledShots.length === 1 ? "" : "s"}{" "}
            still {unfilledShots.length === 1 ? "needs" : "need"} a picture
          </span>{" "}
          <span className="text-muted-foreground">
            before you can approve. Upload your own image, or generate one now,
            for each one below.
          </span>
        </Card>
      )}

      {grouped ? (
        <ul className="space-y-3">
          {scenes.map((scene) => {
            const open = expanded.has(scene.id);
            const canApproveScene =
              scene.unfilled_shots === 0 && !scene.approved;
            return (
              <li key={scene.id}>
                <Card className="space-y-3 p-3">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                    <button
                      type="button"
                      className="flex min-w-0 items-start gap-2 text-left sm:flex-1"
                      onClick={() => toggleExpanded(scene.id)}
                    >
                      <ChevronRight
                        className={`mt-0.5 h-4 w-4 shrink-0 transition-transform ${open ? "rotate-90" : ""}`}
                      />
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium">
                            {scene.title || scene.id}
                          </span>
                          {scene.approved && (
                            <span className="inline-flex items-center gap-1 rounded-full border border-success/30 bg-success/10 px-2 py-0.5 text-xs font-medium text-success">
                              Approved
                            </span>
                          )}
                          {scene.failed_shots > 0 && (
                            <span className="inline-flex items-center gap-1 rounded-full border border-destructive/30 bg-destructive/10 px-2 py-0.5 text-xs font-medium text-destructive">
                              {scene.failed_shots} failed
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground">
                          {scene.total_shots} shot
                          {scene.total_shots === 1 ? "" : "s"} ·{" "}
                          {formatDuration(scene.starts_at_s)}
                          {scene.unfilled_shots > 0 &&
                            ` · ${scene.unfilled_shots} still need a picture`}
                        </p>
                      </div>
                    </button>
                    <div className="flex flex-wrap gap-2 sm:justify-end">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setSeekToS(scene.starts_at_s ?? 0)}
                        disabled={scene.starts_at_s == null}
                      >
                        <Play className="h-3.5 w-3.5" />
                        Watch from here
                      </Button>
                      {scene.failed_shots > 0 && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleRegenerateFailed(scene)}
                        >
                          <RefreshCw className="h-3.5 w-3.5" />
                          Regenerate failed (
                          {formatCostCents(scene.regenerate_failed_cost_cents)})
                        </Button>
                      )}
                      <Button
                        size="sm"
                        disabled={!canApproveScene}
                        onClick={() => handleApproveScene(scene)}
                      >
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        {scene.approved ? "Approved" : "Approve scene"}
                      </Button>
                    </div>
                  </div>
                  {open && (
                    <SceneExpandedShots
                      projectId={projectId}
                      sceneId={scene.id}
                      planByShot={planByShot}
                      videoPending={videoPending}
                      onExpand={(shot, panel) => setLightboxTarget({ shot, panel })}
                      onOverride={(shot, panel) => setOverrideTarget({ shot, panel })}
                      onGenerate={setGenerateTarget}
                      onGenerateVideo={setVideoTarget}
                      onClearSfxCue={handleClearSfxCue}
                      clearingSfxCueShotId={
                        clearSfxCue.isPending
                          ? (clearSfxCue.variables ?? null)
                          : null
                      }
                    />
                  )}
                </Card>
              </li>
            );
          })}
        </ul>
      ) : (
        <ul className="space-y-3">
          {visibleShots.map((shot) => (
            <li key={shot.shot_id}>
              <ShotCard
                projectId={projectId}
                shot={shot}
                plan={planByShot.get(shot.shot_id)}
                videoPending={videoPending.has(shot.shot_id)}
                onExpand={(panel) => setLightboxTarget({ shot, panel })}
                onOverride={(panel) => setOverrideTarget({ shot, panel })}
                onGenerate={() => setGenerateTarget(shot)}
                onGenerateVideo={() => setVideoTarget(shot)}
                onClearSfxCue={() => handleClearSfxCue(shot)}
                clearingSfxCue={
                  clearSfxCue.isPending &&
                  clearSfxCue.variables === shot.shot_id
                }
              />
            </li>
          ))}
        </ul>
      )}

      {!isBackstop && (
        <div className="flex justify-end border-t border-border pt-4">
          <Button
            size="lg"
            onClick={handleApprove}
            disabled={!canApprove}
            variant={
              grouped && remainingScenes.length > 0 ? "secondary" : "default"
            }
          >
            <CheckCircle2 className="h-4 w-4" />
            {approveButtonLabel}
          </Button>
        </div>
      )}

      <Dialog
        open={confirmKind === "scene"}
        onOpenChange={(o) => !o && setConfirmKind(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Approve this scene?</DialogTitle>
            <DialogDescription>
              Scene approval is final — there is no un-approve. If you notice a
              mistake later, replace or regenerate the shot from this row.
            </DialogDescription>
          </DialogHeader>
          <p className="text-sm">
            {pendingScene?.title || pendingScene?.id} ·{" "}
            {pendingScene?.total_shots} shot
            {pendingScene?.total_shots === 1 ? "" : "s"}
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmKind(null)}>
              Back
            </Button>
            <Button onClick={submitSceneApprove}>
              <CheckCircle2 className="h-4 w-4" />
              Approve scene
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={confirmKind === "remaining"}
        onOpenChange={(o) => !o && setConfirmKind(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Approve all remaining scenes?</DialogTitle>
            <DialogDescription>
              This marks every scene you have not reviewed as approved. You
              cannot un-approve. It is the last reversible moment before
              generation can start.
            </DialogDescription>
          </DialogHeader>
          <p className="text-sm font-medium text-warning">
            {remainingScenes.length} scene
            {remainingScenes.length === 1 ? "" : "s"} will be approved without a
            per-scene look.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmKind(null)}>
              Back
            </Button>
            <Button variant="destructive" onClick={handleRemainingConfirmed}>
              Approve remaining scenes
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={confirmKind === "regenerate"}
        onOpenChange={(o) => !o && setConfirmKind(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Regenerate failed shots?</DialogTitle>
            <DialogDescription>
              This spends money and can be retried if it fails again. It does
              not approve the scene.
            </DialogDescription>
          </DialogHeader>
          <p className="text-sm">
            {pendingScene?.failed_shots} failed shot
            {pendingScene?.failed_shots === 1 ? "" : "s"} in{" "}
            {pendingScene?.title || pendingScene?.id}
          </p>
          <p className="text-sm font-medium">
            About{" "}
            {formatCostCents(pendingScene?.regenerate_failed_cost_cents ?? 0)}
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmKind(null)}>
              Back
            </Button>
            <Button
              variant="outline"
              onClick={submitRegenerateFailed}
              disabled={regenerateFailed.isPending}
            >
              <RefreshCw className="h-4 w-4" />
              {regenerateFailed.isPending
                ? "Regenerating…"
                : `Regenerate (${formatCostCents(pendingScene?.regenerate_failed_cost_cents ?? 0)})`}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={confirmKind === "spend"}
        onOpenChange={(o) => !o && setConfirmKind(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirm spend and continue</DialogTitle>
            <DialogDescription>
              Approving locks this plan and continues the pipeline. The
              remaining estimate is least accurate for shots that have not been
              searched yet — it falls back to the plan&apos;s primary strategy.
            </DialogDescription>
          </DialogHeader>
          <p className="text-sm">
            Spent so far:{" "}
            <span className="font-medium">
              {formatCostCents(progress.spent_cost_cents)}
            </span>
            {progress.estimated_cost_cents > 0 && (
              <>
                {" "}
                · remaining ≈ {formatCostCents(progress.estimated_cost_cents)}
              </>
            )}
            {progress.budget_cap_cents > 0 && (
              <> · cap {formatCostCents(progress.budget_cap_cents)}</>
            )}
          </p>
          <p className="text-sm font-medium">
            Confirm {formatCostCents(confirmTotalCents)}
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmKind(null)}>
              Back
            </Button>
            <Button onClick={submitApprove}>
              <CheckCircle2 className="h-4 w-4" />
              Confirm and approve
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {overrideTarget && (
        <OverrideDialog
          open={!!overrideTarget}
          onOpenChange={(o) => !o && setOverrideTarget(null)}
          // P3a: a split_frame shot's title/copy names which panel is
          // being supplied; every other shot's copy is BYTE-IDENTICAL to
          // before this change (`overrideTarget.shot.secondary` is only
          // non-null for a split_frame shot — see `ShotSecondaryPanel`'s
          // own docstring in lib/types.ts).
          title={
            overrideTarget.shot.secondary
              ? overrideTarget.panel === "secondary"
                ? "Supply this shot's bottom panel"
                : "Supply this shot's top panel"
              : "Supply this shot's image"
          }
          description={
            overrideTarget.shot.secondary
              ? isPanelFilled(overrideTarget.shot, overrideTarget.panel)
                ? "This replaces this panel's current image. It's free and instant."
                : "This locks this panel to your image — generation never runs for it, so it costs nothing."
              : isFilled(overrideTarget.shot)
                ? "This replaces the current image. It's free and instant."
                : "This locks the shot to your image — generation never runs for it, so it costs nothing."
          }
          camera={planByShot.get(overrideTarget.shot.shot_id)?.camera}
          isPending={overrideShot.isPending}
          onSubmit={(file, description) =>
            handleOverrideSubmit(
              overrideTarget.shot.shot_id,
              file,
              description,
              overrideTarget.panel,
            )
          }
        />
      )}

      {generateTarget && (
        <GenerateDialog
          shot={generateTarget}
          open={!!generateTarget}
          onOpenChange={(o) => !o && setGenerateTarget(null)}
          isPending={generateShot.isPending}
          onConfirm={(prompt) => handleGenerateConfirm(generateTarget, prompt)}
        />
      )}

      <Dialog
        open={!!videoTarget}
        onOpenChange={(o) => !o && setVideoTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {videoTarget?.clip ? "Regenerate this shot's video?" : "Generate a motion clip?"}
            </DialogTitle>
            <DialogDescription>
              Image-to-video from the current still. Takes a few minutes and
              costs money. Not available in dry-run. A still must already
              exist for this shot.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setVideoTarget(null)}>
              Cancel
            </Button>
            <Button
              onClick={handleGenerateVideoConfirm}
              disabled={generateVideo.isPending || !videoTarget}
            >
              <Film className="h-4 w-4" />
              {generateVideo.isPending ? "Starting…" : "Generate video"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ImageLightbox
        projectId={projectId}
        target={lightboxTarget}
        open={!!lightboxTarget}
        onOpenChange={(o) => !o && setLightboxTarget(null)}
      />

      <p className="pb-6 text-center">
        <Link
          to="/"
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          Back to projects
        </Link>
      </p>
    </div>
  );
}
