"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { Briefcase, LayoutGrid, RefreshCw, Radio, X, AlertCircle } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useAppState } from "@/components/app-provider"
import { cn } from "@/lib/utils"

const NAV = [
  { href: "/", label: "Overview", icon: LayoutGrid },
  { href: "/applications", label: "Applications", icon: Briefcase },
  { href: "/pipeline", label: "Pipeline", icon: Radio },
] as const

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname()
  return (
    <nav aria-label="Primary" className="flex flex-col gap-1">
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = pathname === href
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
              active
                ? "bg-accent text-accent-foreground"
                : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
            )}
          >
            <Icon className="size-4" />
            {label}
          </Link>
        )
      })}
    </nav>
  )
}

function RunBadge() {
  const { run } = useAppState()
  return (
    <Badge variant={run.running ? "default" : run.status === "error" ? "destructive" : "outline"} className="gap-1.5">
      <span
        className={cn(
          "size-1.5 rounded-full",
          run.running ? "animate-pulse bg-primary-foreground" : run.status === "error" ? "bg-destructive" : "bg-muted-foreground"
        )}
      />
      {run.running ? "Running" : run.status === "error" ? "Error" : run.status === "done" ? "Done" : "Idle"}
    </Badge>
  )
}

function StatusBanner() {
  const { error, mock } = useAppState()
  const [dismissed, setDismissed] = React.useState(false)
  if (!mock && !error) return null
  if (dismissed && mock) return null
  return (
    <div className="mx-auto w-full max-w-6xl px-4 pt-4 sm:px-6">
      {mock ? (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-primary/30 bg-primary/10 px-4 py-2.5 text-sm text-foreground">
          <span className="flex items-center gap-2">
            <span className="size-1.5 rounded-full bg-primary animate-pulse" />
            Viewing sample data — start the API with <code className="font-mono text-xs">jobtailor serve</code> for live data.
          </span>
          <button
            onClick={() => setDismissed(true)}
            aria-label="Dismiss sample data notice"
            className="rounded-xs p-1 text-muted-foreground hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 outline-none"
          >
            <X className="size-3.5" />
          </button>
        </div>
      ) : (
        <div className="flex items-center gap-2 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-2.5 text-sm text-destructive">
          <AlertCircle className="size-4 shrink-0" />
          {error}
        </div>
      )}
    </div>
  )
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { refresh, loading, mock } = useAppState()
  const [navOpen, setNavOpen] = React.useState(false)

  return (
    <div className="flex min-h-dvh">
      <aside className="sticky top-0 hidden h-dvh w-56 shrink-0 flex-col border-r bg-card/40 px-3 py-4 lg:flex">
        <Link href="/" className="mb-6 flex items-center gap-2.5 rounded-md px-2 py-1 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50">
          <span className="grid size-8 place-items-center rounded-lg bg-primary font-bold text-primary-foreground text-sm">JT</span>
          <span className="leading-tight">
            <span className="block text-sm font-semibold">JobTailor</span>
            <span className="block text-xs text-muted-foreground">application pipeline</span>
          </span>
        </Link>
        <NavLinks />
        <div className="mt-auto px-2 text-xs text-muted-foreground">
          <p>{mock ? "sample data" : "local API"}</p>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 border-b bg-background/80 backdrop-blur">
          <div className="mx-auto flex w-full max-w-6xl items-center gap-3 px-4 py-3 sm:px-6">
            <Link href="/" className="flex items-center gap-2 lg:hidden">
              <span className="grid size-7 place-items-center rounded-md bg-primary font-bold text-primary-foreground text-xs">JT</span>
              <span className="text-sm font-semibold">JobTailor</span>
            </Link>
            <div className="ml-auto flex items-center gap-2">
              <RunBadge />
              <Button variant="outline" size="sm" onClick={refresh} disabled={loading} aria-label="Refresh data">
                <RefreshCw className={cn("size-4", loading && "animate-spin")} />
                <span className="sr-only sm:not-sr-only">Refresh</span>
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="lg:hidden"
                aria-expanded={navOpen}
                aria-label="Toggle navigation"
                onClick={() => setNavOpen((o) => !o)}
              >
                Menu
              </Button>
            </div>
          </div>
          {navOpen && (
            <div className="border-t px-4 pb-3 pt-2 lg:hidden">
              <NavLinks onNavigate={() => setNavOpen(false)} />
            </div>
          )}
        </header>

        <StatusBanner />

        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6 sm:py-8">{children}</main>

        <footer className="border-t py-4 text-center text-xs text-muted-foreground">
          JobTailor — local dashboard. Run <code className="font-mono">jobtailor serve</code> to start the API.
        </footer>
      </div>
    </div>
  )
}
