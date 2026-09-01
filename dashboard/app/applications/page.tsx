"use client"

import * as React from "react"
import { Briefcase, Search, SlidersHorizontal } from "lucide-react"

import { useAppState } from "@/components/app-provider"
import { ApplicationDetailDialog } from "@/components/application-detail-dialog"
import { ApplicationTable } from "@/components/application-table"
import { EmptyState } from "@/components/empty-state"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import type { ApplicationEntry } from "@/lib/api"

const STATUS_FILTERS = ["all", "submitted", "prepared", "skipped", "failed"] as const

export default function ApplicationsPage() {
  const { apps, internships, loading } = useAppState()
  const [query, setQuery] = React.useState("")
  const [status, setStatus] = React.useState<string>("all")
  const [source, setSource] = React.useState<string>("all")
  const [selected, setSelected] = React.useState<ApplicationEntry | null>(null)

  const allApps = React.useMemo(() => [...apps, ...internships], [apps, internships])

  const sources = React.useMemo(
    () => Array.from(new Set(allApps.map((a) => a.source).filter(Boolean))).sort(),
    [allApps]
  )

  const filterApps = React.useCallback(
    (list: ApplicationEntry[]) => {
      const q = query.trim().toLowerCase()
      return list.filter((app) => {
        if (status !== "all" && app.status !== status) return false
        if (source !== "all" && app.source !== source) return false
        if (!q) return true
        return [app.title, app.company, app.location]
          .join(" ")
          .toLowerCase()
          .includes(q)
      })
    },
    [query, status, source]
  )

  const filteredJobs = React.useMemo(() => filterApps(apps), [apps, filterApps])
  const filteredInterns = React.useMemo(() => filterApps(internships), [internships, filterApps])
  const totalCount = filteredJobs.length + filteredInterns.length

  const renderBlock = (title: string, list: ApplicationEntry[], emptyMsg: string) => (
    <div className="flex flex-col gap-2">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">{title}</h2>
      {list.length === 0 ? (
        <EmptyState icon={Briefcase} title="Nothing here" description={emptyMsg} />
      ) : (
        <ApplicationTable apps={list} onOpen={setSelected} />
      )}
    </div>
  )

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Applications</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Every job and internship you applied for — PDFs, form fields, and Gmail-tracked outcomes.
          </p>
        </div>
        <span className="text-xs tabular-nums text-muted-foreground">
          {totalCount} of {allApps.length} applications
        </span>
      </header>

      <div className="flex flex-col gap-2.5 sm:flex-row sm:items-center">
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search title, company, location…"
            aria-label="Search applications"
            className="pl-9"
          />
        </div>
        <div className="flex items-center gap-2.5">
          <SlidersHorizontal className="hidden size-4 text-muted-foreground sm:block" aria-hidden />
          <label className="sr-only" htmlFor="filter-status">Filter by status</label>
          <select
            id="filter-status"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="h-9 rounded-md border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 [&>option]:bg-popover"
          >
            {STATUS_FILTERS.map((s) => (
              <option key={s} value={s}>{s === "all" ? "All statuses" : s}</option>
            ))}
          </select>
          <label className="sr-only" htmlFor="filter-source">Filter by source</label>
          <select
            id="filter-source"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            className="h-9 rounded-md border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 [&>option]:bg-popover"
          >
            <option value="all">All sources</option>
            {sources.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
      </div>

      {loading && !allApps.length ? (
        <div className="space-y-2.5">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-14 w-full" />
          ))}
        </div>
      ) : allApps.length === 0 ? (
        <EmptyState
          icon={Briefcase}
          title="No applications yet"
          description="Run the pipeline to fetch leads and prepare tailored applications."
        />
      ) : (
        <div className="flex flex-col gap-8">
          {renderBlock("Full-time jobs", filteredJobs, "No full-time applications yet.")}
          {renderBlock("Internships", filteredInterns, "No internships yet.")}
        </div>
      )}

      <ApplicationDetailDialog app={selected} open={!!selected} onOpenChange={(o) => !o && setSelected(null)} />
    </div>
  )
}
