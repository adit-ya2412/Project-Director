import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Info, Trash2, Upload, AlertTriangle } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { ResolutionWarningBadge } from '@/components/ResolutionWarning'
import { useCreateProject } from '@/lib/queries'
import { wordCount } from '@/lib/format'
import { computeResolutionWarning, readImageDimensions, type ResolutionWarning } from '@/lib/resolution'
import { useToast } from '@/components/ui/toast'
import { cn } from '@/lib/utils'
import * as api from '@/lib/api'
import { ApiError } from '@/lib/api'
import { useQueryClient } from '@tanstack/react-query'
import { qk } from '@/lib/queries'

const MIN_WORDS = 10
const MAX_WORDS = 15

interface AssetRow {
  key: string
  file: File
  description: string
  previewUrl: string
  resolution: ResolutionWarning | null
}

function descriptionIssue(desc: string): string | null {
  const n = wordCount(desc)
  if (n === 0) return 'A description is required.'
  if (n < MIN_WORDS) return `Too short (${n} word${n === 1 ? '' : 's'}) — aim for ${MIN_WORDS}-${MAX_WORDS}.`
  if (n > MAX_WORDS) return `Too long (${n} words) — aim for ${MIN_WORDS}-${MAX_WORDS}.`
  return null
}

export function NewProject() {
  const navigate = useNavigate()
  const { toast } = useToast()
  const [name, setName] = useState('')
  const [script, setScript] = useState('')
  const [assets, setAssets] = useState<AssetRow[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const createProject = useCreateProject()
  const queryClient = useQueryClient()

  async function handleFilesSelected(fileList: FileList | null) {
    if (!fileList || fileList.length === 0) return
    const newRows: AssetRow[] = []
    for (const file of Array.from(fileList)) {
      let resolution: ResolutionWarning | null = null
      try {
        const { width, height } = await readImageDimensions(file)
        // No shot is bound yet at upload time, so this assumes 1x (no Ken
        // Burns zoom) — a provisional check, refined again per-shot at
        // Gate 1 once a specific shot (and its camera move) is known (F7).
        resolution = computeResolutionWarning(width, height)
      } catch {
        resolution = null
      }
      newRows.push({
        key: `${file.name}-${file.size}-${Math.random()}`,
        file,
        description: '',
        previewUrl: URL.createObjectURL(file),
        resolution,
      })
    }
    setAssets((prev) => [...prev, ...newRows])
  }

  function updateDescription(key: string, description: string) {
    setAssets((prev) => prev.map((a) => (a.key === key ? { ...a, description } : a)))
  }

  function removeAsset(key: string) {
    setAssets((prev) => prev.filter((a) => a.key !== key))
  }

  const descriptionIssues = assets.map((a) => descriptionIssue(a.description))
  const hasInvalidDescriptions = descriptionIssues.some(Boolean)
  const scriptLines = script.split('\n').filter((l) => l.trim().length > 0)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setFormError(null)

    if (!name.trim()) {
      setFormError('Give the project a name.')
      return
    }
    if (!script.trim()) {
      setFormError('Paste a script before creating the project.')
      return
    }
    if (hasInvalidDescriptions) {
      setFormError('Fix the upload descriptions flagged below (10-15 words each) before continuing.')
      return
    }

    setSubmitting(true)
    try {
      const project = await createProject.mutateAsync(name.trim())
      await api.uploadScript(project.id, script)

      if (assets.length > 0) {
        try {
          await api.uploadAssets(
            project.id,
            assets.map((a) => ({ file: a.file, description: a.description.trim() })),
          )
        } catch (err) {
          // Uploads failing shouldn't strand the project in limbo — the
          // pipeline works fine with zero human-supplied assets (it just
          // searches/generates for every shot). Surface it and continue.
          toast({
            title: 'Some uploads failed',
            description:
              err instanceof ApiError
                ? String(err.detail)
                : 'Check the files and try uploading again from the review screen.',
            variant: 'destructive',
          })
        }
      }

      // Per the brief: trigger endpoints are moving to 202 + poll — fire
      // this and navigate immediately rather than waiting for it to
      // settle, whatever that takes on this backend build.
      api.renderProject(project.id).catch(() => {
        // A failure here still surfaces normally: the project lands on
        // `failed` status and the progress screen (which polls
        // independently) shows it with a retry action.
      })
      queryClient.invalidateQueries({ queryKey: qk.projects })
      navigate(`/projects/${project.id}/progress`)
    } catch (err) {
      setFormError(err instanceof ApiError ? String(err.detail) : 'Something went wrong creating the project.')
      setSubmitting(false)
    }
  }

  return (
    <div className="mx-auto max-w-3xl">
      <h1 className="mb-1 text-xl font-semibold">New project</h1>
      <p className="mb-6 text-sm text-muted-foreground">
        Paste a script, optionally add your own photos, then generate. Nothing is spent until you approve the plan.
      </p>

      <form onSubmit={handleSubmit} className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle>Name</CardTitle>
          </CardHeader>
          <CardContent>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Why Germany Ran Out of Oil"
              maxLength={200}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Script</CardTitle>
            <CardDescription>Narration is the script, verbatim — the pipeline never rewrites it.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Alert>
              <Info className="h-4 w-4" />
              <AlertTitle>Line breaks become cuts</AlertTitle>
              <AlertDescription>
                <p>
                  Each line becomes a shot boundary. Short, single-thought lines give clean one-line-per-shot cuts —
                  long paragraphs make the planner guess where to cut.
                </p>
                <p className="mt-1">
                  Writing Hindi/Hinglish? Mixed script (Devanagari for Hindi words, Latin for English loanwords, e.g.
                  <span className="font-mono"> "Germany ke paas oil tha hi nahi"</span>) measurably sounds better than
                  fully Romanised Hindi when read aloud by the narrator.
                </p>
              </AlertDescription>
            </Alert>
            <Textarea
              value={script}
              onChange={(e) => setScript(e.target.value)}
              placeholder={'One idea per line.\nGermany ke paas oil tha hi nahi.\nSo they built synthetic fuel plants instead.'}
              className="min-h-[220px] font-mono text-sm"
            />
            <p className="text-xs text-muted-foreground">
              {scriptLines.length} non-empty line{scriptLines.length === 1 ? '' : 's'} → roughly that many shots.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Voice</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              This project narrates with the server's configured default voice. Voice selection isn't offered here —
              audition and switch to a different voice after narration finishes, for free, from the result screen.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Your own photos (optional)</CardTitle>
            <CardDescription>
              Speeds up the shots they match and costs nothing when generation would otherwise be needed.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Alert variant="warning">
              <AlertTriangle className="h-4 w-4" />
              <AlertTitle>Descriptions are matched by literal word overlap — not by an AI</AlertTitle>
              <AlertDescription>
                <p>
                  A shot picks this photo only if your description's words overlap with the shot's own search terms.
                  There's no understanding of meaning at all — write concrete nouns in English (places, objects,
                  period), even if the script itself is in Hindi or Hinglish, because English is what the search
                  terms are written in.
                </p>
                <div className="mt-2 overflow-x-auto rounded-md border border-border">
                  <table className="w-full text-xs">
                    <thead className="bg-secondary/60 text-left">
                      <tr>
                        <th className="px-2 py-1 font-medium">Description</th>
                        <th className="px-2 py-1 font-medium">Result</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr className="border-t border-border">
                        <td className="px-2 py-1 font-mono">Leuna-Werke synthetic fuel plant, distillation towers, 1943 archival</td>
                        <td className="px-2 py-1 text-success">matches</td>
                      </tr>
                      <tr className="border-t border-border">
                        <td className="px-2 py-1 font-mono">my grandfather's old factory in East Germany</td>
                        <td className="px-2 py-1 text-warning">~ nothing</td>
                      </tr>
                      <tr className="border-t border-border">
                        <td className="px-2 py-1 font-mono">franz</td>
                        <td className="px-2 py-1 text-destructive">nothing — silently discarded</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <p className="mt-2">
                  Write 10-15 words of concrete nouns. A photo whose description scores too low is discarded before
                  anyone sees it — you won't get an error, it will simply never be offered to any shot.
                </p>
              </AlertDescription>
            </Alert>

            <div>
              <Label htmlFor="asset-files" className="mb-2 block">
                Add photos
              </Label>
              <Input
                id="asset-files"
                type="file"
                accept="image/*"
                multiple
                onChange={(e) => {
                  void handleFilesSelected(e.target.files)
                  e.target.value = ''
                }}
              />
            </div>

            {assets.length > 0 && (
              <ul className="space-y-3">
                {assets.map((a, i) => {
                  const issue = descriptionIssues[i]
                  const n = wordCount(a.description)
                  return (
                    <li key={a.key} className="flex gap-3 rounded-md border border-border p-3">
                      <img
                        src={a.previewUrl}
                        alt=""
                        className="h-24 w-16 shrink-0 rounded object-cover"
                      />
                      <div className="flex-1 space-y-1.5">
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate text-xs text-muted-foreground">{a.file.name}</span>
                          <button
                            type="button"
                            onClick={() => removeAsset(a.key)}
                            className="text-muted-foreground hover:text-destructive"
                            aria-label={`Remove ${a.file.name}`}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                        <Textarea
                          value={a.description}
                          onChange={(e) => updateDescription(a.key, e.target.value)}
                          placeholder="Leuna-Werke synthetic fuel plant, distillation towers, industrial complex, 1943 archival photograph"
                          className={cn('min-h-[52px] text-sm', issue && 'border-destructive/60')}
                        />
                        <div className="flex items-center justify-between text-xs">
                          <span className={issue ? 'text-destructive' : 'text-success'}>
                            {issue ?? `${n} words — good`}
                          </span>
                        </div>
                        {a.resolution && <ResolutionWarningBadge warning={a.resolution} />}
                      </div>
                    </li>
                  )
                })}
              </ul>
            )}
          </CardContent>
        </Card>

        {formError && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>{formError}</AlertDescription>
          </Alert>
        )}

        <div className="flex justify-end gap-2">
          <Button type="submit" disabled={submitting} size="lg">
            <Upload className="h-4 w-4" />
            {submitting ? 'Creating…' : 'Create and start generating'}
          </Button>
        </div>
      </form>
    </div>
  )
}
