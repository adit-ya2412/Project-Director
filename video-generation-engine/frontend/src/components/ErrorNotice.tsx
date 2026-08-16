import { translateError } from '@/lib/errors'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Disclosure } from '@/components/Disclosure'
import { AlertTriangle } from 'lucide-react'
import type { ReactNode } from 'react'

/** F3: plain-language headline, action when one exists, raw text always
 * available but never load-bearing for reading the error. Used for
 * project-level failures, per-stage failures, and per-shot failures. */
export function ErrorNotice({
  message,
  variant = 'destructive',
  extraAction,
}: {
  message: string | null | undefined
  variant?: 'destructive' | 'warning'
  extraAction?: ReactNode
}) {
  const translated = translateError(message)
  if (!translated) return null

  return (
    <Alert variant={variant}>
      <AlertTriangle className="h-4 w-4" />
      <AlertTitle>{translated.headline}</AlertTitle>
      <AlertDescription>
        {translated.action && <p>{translated.action}</p>}
        {extraAction}
        <Disclosure summary="Technical detail">{translated.raw}</Disclosure>
      </AlertDescription>
    </Alert>
  )
}
