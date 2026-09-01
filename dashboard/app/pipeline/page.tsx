"use client"


import { useAppState } from "@/components/app-provider"
import { RunPipelineCard } from "@/components/run-pipeline-card"

export default function PipelinePage() {
  const { run } = useAppState()

  return (
    <div className="flex flex-col gap-6">
      <header className="flex items-center gap-2">
        <h1 className="text-xl font-semibold tracking-tight">Pipeline</h1>
      </header>

      <RunPipelineCard />

      <section aria-label="Pipeline output" className="rounded-lg border bg-card">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <h2 className="text-sm font-semibold">Live output</h2>
          <span className="text-xs text-muted-foreground">
            {run.running ? "streaming…" : "most recent run"}
          </span>
        </div>
        <pre className="max-h-[420px] overflow-auto p-4 font-mono text-xs leading-relaxed whitespace-pre-wrap scrollbar-thin">
          {run.output || "No output yet. Start a run above to see live pipeline output."}
        </pre>
      </section>
    </div>
  )
}
