import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Clapperboard, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-40 border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
          <Link to="/" className="flex items-center gap-2 font-semibold">
            <Clapperboard className="h-5 w-5 text-primary" />
            <span>Video Generation Engine</span>
          </Link>
          <Button asChild size="sm">
            <Link to="/new">
              <Plus className="h-4 w-4" />
              New project
            </Link>
          </Button>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
    </div>
  )
}
