import * as React from 'react'
import { createContext, useCallback, useContext, useState } from 'react'
import { CheckCircle2, XCircle, Info, X } from 'lucide-react'
import { cn } from '@/lib/utils'

type ToastVariant = 'default' | 'success' | 'destructive'

interface ToastItem {
  id: number
  title: string
  description?: string
  variant: ToastVariant
}

interface ToastContextValue {
  toast: (t: { title: string; description?: string; variant?: ToastVariant }) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

let nextId = 1

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])

  const toast = useCallback(
    ({
      title,
      description,
      variant = 'default',
    }: {
      title: string
      description?: string
      variant?: ToastVariant
    }) => {
      const id = nextId++
      setToasts((prev) => [...prev, { id, title, description, variant }])
      window.setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id))
      }, 6000)
    },
    [],
  )

  const dismiss = (id: number) => setToasts((prev) => prev.filter((t) => t.id !== id))

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-full max-w-sm flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={cn(
              'pointer-events-auto flex items-start gap-2 rounded-lg border p-3 shadow-lg',
              t.variant === 'success' && 'border-success/40 bg-card',
              t.variant === 'destructive' && 'border-destructive/40 bg-card',
              t.variant === 'default' && 'border-border bg-card',
            )}
          >
            {t.variant === 'success' && <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />}
            {t.variant === 'destructive' && <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />}
            {t.variant === 'default' && <Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" />}
            <div className="flex-1 text-sm">
              <div className="font-medium">{t.title}</div>
              {t.description && <div className="text-muted-foreground">{t.description}</div>}
            </div>
            <button
              onClick={() => dismiss(t.id)}
              className="text-muted-foreground hover:text-foreground"
              aria-label="Dismiss"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within ToastProvider')
  return ctx
}
