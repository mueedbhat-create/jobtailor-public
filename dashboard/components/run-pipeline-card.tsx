"use client"

import * as React from "react"
import { AlertCircle, Play, RefreshCw } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useAppState } from "@/components/app-provider"
import { cn } from "@/lib/utils"

const MODES = [
  { value: "human_in_the_loop", label: "Open only", hint: "Opens each job in the browser for review." },
  { value: "pre_fill", label: "Pre-fill", hint: "Fills the form and attaches your PDF — you click submit." },
  { value: "full_auto", label: "Auto-submit", hint: "Submits applications automatically. Use with care." },
] as const

export function RunPipelineCard({ compact = false }: { compact?: boolean }) {
  const { run, triggerRun, mock } = useAppState()
  const [mode, setMode] = React.useState<string>("human_in_the_loop")
  const [starting, setStarting] = React.useState(false)
  const activeMode = MODES.find((m) => m.value === mode) ?? MODES[0]

  const start = async () => {
    setStarting(true)
    try {
      await triggerRun(mode, 15)
    } catch {
      /* surfaced via provider error banner */
    } finally {
      setStarting(false)
    }
  }

  return (
    <div className="rounded-lg border bg-card p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">Run pipeline</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Fetch leads, extract JDs, tailor resumes, prepare applications.
          </p>
        </div>
        <Badge variant={run.running ? "default" : "outline"}>
          {run.running ? "running" : run.status === "done" ? "done" : run.status === "error" ? "error" : "idle"}
        </Badge>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <div role="radiogroup" aria-label="Apply mode" className="flex overflow-hidden rounded-lg border">
          {MODES.map((m) => (
            <button
              key={m.value}
              role="radio"
              aria-checked={mode === m.value}
              onClick={() => setMode(m.value)}
              disabled={run.running || starting || mock}
              className={cn(
                "px-3.5 py-2 text-xs font-medium outline-none transition-colors focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50 sm:text-sm",
                mode === m.value ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted"
              )}
            >
              {m.label}
            </button>
          ))}
        </div>
        <Button onClick={start} disabled={run.running || starting || mock}>
          {starting || run.running ? <RefreshCw className="size-4 animate-spin" /> : <Play className="size-4" />}
          Run pipeline
        </Button>
        {mode === "full_auto" && !mock && (
          <span className="flex items-center gap-1 text-xs text-destructive">
            <AlertCircle className="size-3.5" /> Auto-submits applications.
          </span>
        )}
      </div>
      {!compact && (
        <p className="mt-3 text-xs text-muted-foreground">{activeMode.hint}</p>
      )}
    </div>
  )
}
