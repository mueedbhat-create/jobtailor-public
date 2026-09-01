"use client"

import * as React from "react"
import Link from "next/link"
import {
  ArrowRight,
  Inbox,
  RefreshCw,
} from "lucide-react"

import { useAppState } from "@/components/app-provider"
import { ApplicationDetailDialog } from "@/components/application-detail-dialog"
import { EmptyState } from "@/components/empty-state"
import { RunPipelineCard } from "@/components/run-pipeline-card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { TrackingBadge } from "@/components/tracking-timeline"
import type { ApplicationEntry } from "@/lib/api"
import { statusVariant, formatDate, formatDateTime } from "@/lib/api"

export default function OverviewPage() {
  const { apps, internships, totals, loading, mock, syncTracking } = useAppState()
  const [selected, setSelected] = React.useState<ApplicationEntry | null>(null)
  const [syncMsg, setSyncMsg] = React.useState<string | null>(null)
  const [syncing, setSyncing] = React.useState(false)

  const recent = apps.slice(0, 6)

  const trackCounts = React.useMemo(() => {
    const count = (list: ApplicationEntry[]) => {
      const submitted = list.filter((a) => a.status === "submitted").length
      const prepared = list.filter((a) => a.status === "prepared").length
      const skipped = list.filter((a) => a.status === "skipped").length
      const failed = list.filter((a) => a.status === "failed").length
      const confirmation = list.filter((a) => a.tracking?.status === "confirmation").length
      const rejected = list.filter((a) => a.tracking?.status === "rejected").length
      const interview = list.filter((a) => a.tracking?.status === "interview").length
      const offer = list.filter((a) => a.tracking?.status === "offer").length
      const awaiting = submitted
      const applied = submitted + prepared
      return { submitted, prepared, skipped, failed, confirmation, rejected, interview, offer, awaiting, applied, total: list.length }
    }
    return { jobs: count(apps), internships: count(internships) }
  }, [apps, internships])

  const COLS = ["Applied", "Awaiting", "Submitted", "Rejected", "Interview", "Offer"] as const

  const getVal = (track: typeof trackCounts.jobs, col: string) => {
    switch (col) {
      case "Applied": return track.applied
      case "Awaiting": return track.awaiting
      case "Submitted": return track.submitted
      case "Rejected": return track.rejected
      case "Interview": return track.interview
      case "Offer": return track.offer
      default: return 0
    }
  }

  const runSync = async () => {
    setSyncing(true)
    const result = await syncTracking()
    setSyncMsg(result ? result.message : "Could not reach the API.")
    setSyncing(false)
  }

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Overview</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Your application lifecycle at a glance.
          {totals.last_synced && (
            <span className="ml-2 inline-flex items-center gap-1 text-xs">
              <RefreshCw className="size-3" /> synced {formatDateTime(totals.last_synced)}
            </span>
          )}
        </p>
      </header>

      <section aria-label="Pipeline summary" className="rounded-lg border bg-card">
        <div className="border-b px-4 py-3">
          <h2 className="text-sm font-semibold">Pipeline summary</h2>
        </div>
        {loading && !trackCounts.jobs.total && !trackCounts.internships.total ? (
          <div className="space-y-3 p-4">
            {Array.from({ length: 2 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  <th className="px-4 py-2.5">Track</th>
                  {COLS.map((col) => (
                    <th key={col} className="px-4 py-2.5 text-right tabular-nums">{col}</th>
                  ))}
                  <th className="px-4 py-2.5 text-right tabular-nums">Total</th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-b last:border-0">
                  <td className="px-4 py-2.5 font-medium">Jobs</td>
                  {COLS.map((col) => (
                    <td key={col} className="px-4 py-2.5 text-right tabular-nums">
                      {getVal(trackCounts.jobs, col)}
                    </td>
                  ))}
                  <td className="px-4 py-2.5 text-right tabular-nums font-medium">{trackCounts.jobs.total}</td>
                </tr>
                <tr className="last:border-0">
                  <td className="px-4 py-2.5 font-medium">Internships</td>
                  {COLS.map((col) => (
                    <td key={col} className="px-4 py-2.5 text-right tabular-nums">
                      {getVal(trackCounts.internships, col)}
                    </td>
                  ))}
                  <td className="px-4 py-2.5 text-right tabular-nums font-medium">{trackCounts.internships.total}</td>
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[1fr_300px]">
        <section aria-label="Recent applications" className="rounded-lg border bg-card">
          <div className="flex items-center justify-between border-b px-4 py-3">
            <h2 className="text-sm font-semibold">Recent applications</h2>
            <Link
              href="/applications"
              className="inline-flex items-center gap-1 rounded-xs text-xs font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 outline-none"
            >
              View all <ArrowRight className="size-3.5" />
            </Link>
          </div>
          {loading && !recent.length ? (
            <div className="space-y-3 p-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-11 w-full" />
              ))}
            </div>
          ) : recent.length === 0 ? (
            <EmptyState
              icon={Inbox}
              title="No applications yet"
              description="Run the pipeline to fetch leads and prepare your first tailored application."
              className="m-4 border-0 py-10"
            />
          ) : (
            <ul className="divide-y">
              {recent.map((app) => (
                <li key={app.url}>
                  <button
                    onClick={() => setSelected(app)}
                    className="flex w-full items-center gap-3 px-4 py-3 text-left outline-none transition-colors hover:bg-muted/40 focus-visible:bg-muted/60 focus-visible:ring-[3px] focus-visible:ring-ring/40"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium leading-snug">{app.title}</p>
                      <p className="truncate text-xs text-muted-foreground">{app.company}</p>
                    </div>
                    <Badge variant={statusVariant(app.status)}>{app.status}</Badge>
                    {app.tracking ? <TrackingBadge status={app.tracking.status} /> : null}
                    <span className="hidden w-12 text-right text-xs tabular-nums text-muted-foreground sm:block">
                      {formatDate(app.applied_at || app.opened_at)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <div className="flex flex-col gap-5">
          <RunPipelineCard compact />

          {!mock && (
            <section aria-label="Email tracking" className="rounded-lg border bg-card p-5">
              <h2 className="text-sm font-semibold">Gmail tracking</h2>
              <p className="mt-1 text-xs text-muted-foreground">
                Scan the inbox for confirmations, rejections, interviews, and offers.
              </p>
              <Button variant="outline" size="sm" onClick={runSync} disabled={syncing || mock} className="mt-3 w-full">
                <RefreshCw className={`size-4 ${syncing ? "animate-spin" : ""}`} />
                Sync Gmail now
              </Button>
              {(syncMsg || totals.last_synced) && (
                <p className="mt-2 text-center text-xs text-muted-foreground">
                  {syncMsg ?? `Last synced ${formatDateTime(totals.last_synced)}`}
                </p>
              )}
            </section>
          )}
        </div>
      </div>

      <ApplicationDetailDialog app={selected} open={!!selected} onOpenChange={(o) => !o && setSelected(null)} />
    </div>
  )
}
