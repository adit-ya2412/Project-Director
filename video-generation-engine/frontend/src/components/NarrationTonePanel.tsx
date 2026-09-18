/** Pick a delivery tone for a run of scenes, at the approval gate.
 *
 * See docs/plans/narration_tone_tags.md. The short version: on eleven_v3
 * tone is not a parameter, it is an inline audio tag in the request
 * text. Those tags never touch `narration_text` — the backend prefixes
 * them only when the TTS request is built and strips them back out of
 * the returned alignment, so captions and shot timings never see them.
 *
 * Why this panel lives at the gate rather than in the script: narration
 * runs BEFORE the approval gate, so by the time this is on screen the
 * first read already exists and can be listened to. Tone is chosen
 * against real audio instead of guessed up front.
 *
 * Why it reads `timeline.scenes` rather than `progress.scenes`: the
 * gate's grouped scene list only renders above SCENE_GROUP_SHOT_THRESHOLD
 * (40 shots), and a 50-second reel never reaches that — tying this to
 * the grouped layout would hide it for exactly the shortest-form case.
 * `SceneProgress` also carries no tone field; the timeline does.
 */

import { useState } from "react";
import { Mic2, TriangleAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { ApiError } from "@/lib/api";
import { useSetSceneNarrationTones } from "@/lib/queries";
import { NARRATION_TONES, type Scene, type Timeline } from "@/lib/types";

interface Props {
  projectId: string;
  timeline: Timeline | undefined;
}

/** True when the picked scenes are NOT one unbroken run in scene order.
 *
 * Worth telling the user about: the batcher refuses to group a lone
 * cache miss with anything, so a scene retoned on its own is synthesised
 * on its own and picks up a fresh performance at both of its joins. A
 * contiguous run goes out as one request and shares one performance.
 */
function isScattered(scenes: Scene[], selected: Set<string>): boolean {
  const picked = scenes
    .map((scene, index) => ({ index, on: selected.has(scene.id) }))
    .filter((entry) => entry.on)
    .map((entry) => entry.index);
  if (picked.length < 2) return false;
  return picked[picked.length - 1] - picked[0] !== picked.length - 1;
}

export function NarrationTonePanel({ projectId, timeline }: Props) {
  const { toast } = useToast();
  const setTones = useSetSceneNarrationTones(projectId);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());

  const scenes = timeline?.scenes ?? [];
  // The backend refuses with a 409 once approved, for a real reason:
  // generated clips are never regenerated when only duration moves, and
  // tone moves it. Disable rather than let the user find out by error.
  const locked = timeline?.status === "approved";
  // Cheap enough to recompute: one pass over the scene list. Memoising
  // it would need a stable `scenes` reference this component does not
  // have, since it defaults to a fresh [] whenever the timeline is still
  // loading.
  const scattered = isScattered(scenes, selected);

  if (!timeline || scenes.length === 0) return null;

  function toggle(sceneId: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(sceneId)) next.delete(sceneId);
      else next.add(sceneId);
      return next;
    });
  }

  function apply(tone: string | null) {
    const sceneIds = scenes
      .filter((scene) => selected.has(scene.id))
      .map((scene) => scene.id);
    if (sceneIds.length === 0) return;
    setTones.mutate(
      { sceneIds, tone },
      {
        onSuccess: () => {
          setSelected(new Set());
          toast({
            title: tone ? `Re-narrating as ${tone}` : "Re-narrating as default",
            description: `${sceneIds.length} scene${
              sceneIds.length === 1 ? "" : "s"
            } queued. Only the scenes you changed are re-synthesised — the rest stay cached.`,
            variant: "success",
          });
        },
        onError: (err) =>
          toast({
            title: "Could not set the narration tone",
            description:
              err instanceof ApiError ? String(err.detail) : "Try again.",
            variant: "destructive",
          }),
      },
    );
  }

  return (
    <Card className="space-y-3 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex items-start gap-2">
          <Mic2 className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
          <div>
            <p className="font-medium">Narration tone</p>
            <p className="text-xs text-muted-foreground">
              Pick the scenes that share a delivery, then choose it. Tone
              changes pace as well as character, so durations are re-measured
              from the new read.
            </p>
          </div>
        </div>
        {selected.size > 0 && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setSelected(new Set())}
          >
            Clear selection
          </Button>
        )}
      </div>

      {locked && (
        <p className="rounded-md border border-warning/30 bg-warning/10 px-2 py-1.5 text-xs text-warning">
          This timeline is approved, so tone is locked. Re-tuning it now would
          shift every shot&apos;s duration while the generated clips stay cut
          for the old timings.
        </p>
      )}

      <ul className="space-y-1">
        {scenes.map((scene) => {
          const on = selected.has(scene.id);
          return (
            <li key={scene.id}>
              <label
                className={`flex cursor-pointer items-start gap-2 rounded-md px-2 py-1.5 text-left hover:bg-accent ${
                  on ? "bg-accent" : ""
                } ${locked ? "cursor-not-allowed opacity-60" : ""}`}
              >
                <input
                  type="checkbox"
                  className="mt-1 h-3.5 w-3.5 shrink-0 accent-primary"
                  checked={on}
                  disabled={locked}
                  onChange={() => toggle(scene.id)}
                />
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium">
                      {scene.title || scene.id}
                    </span>
                    {scene.narration_tone ? (
                      <Badge variant="secondary">{scene.narration_tone}</Badge>
                    ) : (
                      <Badge variant="outline">default</Badge>
                    )}
                  </span>
                  {scene.narration_text && (
                    <span className="mt-0.5 line-clamp-1 block text-xs text-muted-foreground">
                      {scene.narration_text}
                    </span>
                  )}
                </span>
              </label>
            </li>
          );
        })}
      </ul>

      {scattered && (
        <p className="flex items-start gap-1.5 rounded-md border border-warning/30 bg-warning/10 px-2 py-1.5 text-xs text-warning">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            These scenes aren&apos;t next to each other. Each isolated one is
            re-recorded on its own, so you may hear the voice shift where it
            meets the scenes around it. Picking an unbroken run avoids that.
          </span>
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {NARRATION_TONES.map((tone) => (
          <Button
            key={tone}
            variant="outline"
            size="sm"
            disabled={locked || selected.size === 0 || setTones.isPending}
            onClick={() => apply(tone)}
          >
            {tone}
          </Button>
        ))}
        <Button
          variant="ghost"
          size="sm"
          disabled={locked || selected.size === 0 || setTones.isPending}
          onClick={() => apply(null)}
        >
          Default read
        </Button>
        {selected.size > 0 && !locked && (
          <span className="text-xs text-muted-foreground">
            {selected.size} scene{selected.size === 1 ? "" : "s"} selected
          </span>
        )}
      </div>
    </Card>
  );
}
