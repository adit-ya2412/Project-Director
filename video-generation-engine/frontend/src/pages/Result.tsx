import { useEffect, useMemo, useState } from "react";
import {
  useNavigate,
  useParams,
  useSearchParams,
  Link,
} from "react-router-dom";
import { Download, RefreshCw, Music2, Mic } from "lucide-react";
import {
  useProject,
  useProgress,
  useTimeline,
  useRetryMusic,
  useRetryNarration,
  useRenderOnly,
} from "@/lib/queries";
import { videoUrl } from "@/lib/api";
import { formatCostCents } from "@/lib/format";
import { shotAssetSource } from "@/lib/asset-source";
import { ASSET_SOURCE_LABEL } from "@/lib/asset-source";
import type { AssetSource } from "@/lib/types";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { CopyButton } from "@/components/CopyButton";
import { useToast } from "@/components/ui/toast";
import { ApiError } from "@/lib/api";

const SOURCE_ORDER: AssetSource[] = [
  "archival",
  "entity",
  "generated",
  "uploaded",
  "unknown",
];

// A correction trigger (voice/music/render) is fire-and-forget - it
// navigates to /progress immediately, long before the actual redo
// finishes, so a toast fired at click time can only ever say "started",
// never "done". This label carries which correction is in flight as a
// `?pending=` search param through the trigger -> `/progress` ->
// (Progress.tsx's own redirect once `workflow_state` reaches `completed`)
// -> back to `/result?corrected=` hop, so THIS screen can show a clear,
// unmissable confirmation the moment the human actually lands back here
// with the real result - not a fleeting toast that fired before the work
// even started.
const CORRECTION_LABEL: Record<string, string> = {
  voice: "Narration updated with the new voice.",
  music: "New music selected.",
  render: "Re-rendered.",
};

export function Result() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { toast } = useToast();
  const { data: project } = useProject(projectId);
  const { data: progress, isLoading } = useProgress(projectId, {
    expandShots: true,
  });
  const { data: timeline } = useTimeline(projectId);
  const retryMusic = useRetryMusic(projectId ?? "");
  const retryNarration = useRetryNarration(projectId ?? "");
  const renderOnly = useRenderOnly(projectId ?? "");

  const [voiceId, setVoiceId] = useState("");
  const [musicTerms, setMusicTerms] = useState("");

  useEffect(() => {
    const corrected = searchParams.get("corrected");
    if (!corrected) return;
    toast({
      title: "Done",
      description: CORRECTION_LABEL[corrected] ?? "Your correction is applied.",
      variant: "success",
    });
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("corrected");
        return next;
      },
      { replace: true },
    );
  }, [searchParams, toast, setSearchParams]);

  const sourceMix = useMemo(() => {
    const counts: Record<AssetSource, number> = {
      archival: 0,
      entity: 0,
      generated: 0,
      uploaded: 0,
      unknown: 0,
    };
    if (progress) {
      for (const shot of progress.shots) counts[shotAssetSource(shot)] += 1;
    }
    return counts;
  }, [progress]);

  if (isLoading || !progress || !projectId) {
    return (
      <div className="mx-auto max-w-3xl space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  const track = timeline?.music_plan?.selected_track ?? null;

  function handleRetryVoice() {
    if (!voiceId.trim()) return;
    retryNarration.mutate(voiceId.trim(), {
      onSuccess: () =>
        toast({
          title: "Re-recording narration…",
          description: "Free — this voice is cached once synthesised.",
        }),
      onError: (err) =>
        toast({
          title: "Could not switch voice",
          description:
            err instanceof ApiError ? String(err.detail) : "Try again.",
          variant: "destructive",
        }),
    });
    navigate(`/projects/${projectId}/progress?pending=voice`);
  }

  function handleRetryMusic() {
    const terms = musicTerms
      .split(/[,\n]/)
      .map((t) => t.trim())
      .filter(Boolean);
    retryMusic.mutate(terms.length > 0 ? terms : undefined, {
      onSuccess: () => toast({ title: "Searching for new music…" }),
      onError: (err) =>
        toast({
          title: "Could not retry music",
          description:
            err instanceof ApiError ? String(err.detail) : "Try again.",
          variant: "destructive",
        }),
    });
    navigate(`/projects/${projectId}/progress?pending=music`);
  }

  function handleRerender() {
    renderOnly.mutate(undefined, {
      onSuccess: () =>
        toast({
          title: "Re-rendering…",
          description: "Free — this runs locally with ffmpeg.",
        }),
      onError: (err) =>
        toast({
          title: "Could not re-render",
          description:
            err instanceof ApiError ? String(err.detail) : "Try again.",
          variant: "destructive",
        }),
    });
    navigate(`/projects/${projectId}/progress?pending=render`);
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold">
          {project?.name ?? "Your video"}
        </h1>
        <p className="text-sm text-muted-foreground">
          Done — review it below, or make a correction.
        </p>
      </div>

      <Card>
        <CardContent className="p-4">
          {/* Keyed on `updated_at`, not just `videoUrl(projectId)` — the URL
              is stable per project, but a re-render (new voice/music, a
              corrected shot) overwrites the same file with different
              bytes. An already-mounted `<video>` has no reason to
              re-fetch an unchanged `src` string, so without this it kept
              showing the OLD render until a hard refresh. `updated_at`
              bumps on every project update, including the one `RenderStep`
              makes when it writes a fresh `video_path`. */}
          <video
            key={project?.updated_at}
            controls
            className={`mx-auto max-h-[70vh] w-full rounded-md bg-black ${(project?.render_width ?? 720) > (project?.render_height ?? 1280) ? "max-w-3xl" : "max-w-sm"}`}
            src={videoUrl(projectId)}
          />
          <div className="mt-3 flex justify-center gap-2">
            <Button asChild>
              <a
                href={videoUrl(projectId)}
                download={`${project?.name ?? projectId}.mp4`}
              >
                <Download className="h-4 w-4" />
                Download
              </a>
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>What it's made of</CardTitle>
          <CardDescription>
            Which shots are AI-generated is the thing most worth knowing at a
            glance.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {SOURCE_ORDER.filter((s) => sourceMix[s] > 0).map((s) => (
            <div
              key={s}
              className="rounded-md border border-border p-3 text-center"
            >
              <div className="text-2xl font-semibold">{sourceMix[s]}</div>
              <div className="text-xs text-muted-foreground">
                {ASSET_SOURCE_LABEL[s]}
              </div>
            </div>
          ))}
        </CardContent>
        <CardContent className="pt-0">
          <p className="text-sm">
            Total spend:{" "}
            <span className="font-semibold">
              {formatCostCents(progress.spent_cost_cents)}
            </span>
          </p>
        </CardContent>
      </Card>

      <Card className={track ? "border-primary/40" : undefined}>
        <CardHeader>
          <CardTitle>Music attribution</CardTitle>
          <CardDescription>
            {track
              ? "Every track the search can return is CC0 or CC-BY — CC-BY requires this credit wherever the video is published."
              : "No track selected yet."}
          </CardDescription>
        </CardHeader>
        {track && (
          <CardContent className="space-y-2">
            <div className="flex flex-wrap items-center gap-2 rounded-md bg-secondary/40 p-3">
              <p className="flex-1 font-mono text-sm">{track.attribution}</p>
              <CopyButton text={track.attribution} label="Copy attribution" />
            </div>
          </CardContent>
        )}
      </Card>

      <div className="grid gap-4 sm:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Mic className="h-4 w-4" /> Try a different voice
            </CardTitle>
            <CardDescription>
              Free after the first time — narration for a voice you've used
              before is cached.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <Label htmlFor="voice-id">ElevenLabs voice ID</Label>
            <Input
              id="voice-id"
              value={voiceId}
              onChange={(e) => setVoiceId(e.target.value)}
              placeholder="e.g. 21m00Tcm4TlvDq8ikWAM"
            />
            <Button
              size="sm"
              onClick={handleRetryVoice}
              disabled={!voiceId.trim()}
            >
              Re-record narration
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Music2 className="h-4 w-4" /> Try different music
            </CardTitle>
            <CardDescription>
              Leave blank to retry the same search terms after a fix; supply
              your own to escape a bad match.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <Label htmlFor="music-terms">
              Search terms (comma-separated, optional)
            </Label>
            <Input
              id="music-terms"
              value={musicTerms}
              onChange={(e) => setMusicTerms(e.target.value)}
              placeholder="tense, strings, documentary"
            />
            <Button size="sm" onClick={handleRetryMusic}>
              Search again
            </Button>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <RefreshCw className="h-4 w-4" /> Re-render
          </CardTitle>
          <CardDescription>
            Free — runs locally with ffmpeg. Use this after any correction above
            to bake it into the video.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button size="sm" variant="outline" onClick={handleRerender}>
            Re-render now
          </Button>
        </CardContent>
      </Card>

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
