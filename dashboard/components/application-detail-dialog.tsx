"use client"

import * as React from "react"
import { Download, ExternalLink, FileText } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { TrackingBadge, TrackingTimeline } from "@/components/tracking-timeline"
import type { ApplicationEntry } from "@/lib/api"
import { apiGet, resumePdfUrl, statusVariant, formatDate, type JobDescription } from "@/lib/api"

const FIELD_LABELS: Record<string, string> = {
  full_name: "Full name",
  email: "Email",
  phone: "Phone",
  location: "Location",
  linkedin: "LinkedIn",
  website: "Website",
  headline: "Headline",
}

function FieldList({ fields }: { fields: Record<string, string> }) {
  const entries = Object.entries(fields)
  if (!entries.length) {
    return (
      <p className="rounded-md border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
        No form fields were recorded for this application.
      </p>
    )
  }
  return (
    <dl className="divide-y rounded-md border">
      {entries.map(([key, value]) => (
        <div key={key} className="grid grid-cols-[110px_1fr] gap-3 px-3 py-2 sm:grid-cols-[140px_1fr]">
          <dt className="truncate text-xs font-medium text-muted-foreground pt-0.5">
            {FIELD_LABELS[key] ?? key}
          </dt>
          <dd className="min-w-0 truncate text-sm" title={value}>
            {value}
          </dd>
        </div>
      ))}
    </dl>
  )
}

export function ApplicationDetailDialog({
  app,
  open,
  onOpenChange,
}: {
  app: ApplicationEntry | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [jdState, setJdState] = React.useState<{ url: string; data: JobDescription | null }>({
    url: "",
    data: null,
  })

  React.useEffect(() => {
    if (!app || !open) return
    let cancelled = false
    apiGet<JobDescription>(`/api/jd?url=${encodeURIComponent(app.url)}`)
      .then((data) => {
        if (!cancelled) setJdState({ url: app.url, data })
      })
      .catch(() => {
        if (!cancelled) setJdState({ url: app.url, data: null })
      })
    return () => {
      cancelled = true
    }
  }, [app, open])

  const jd = jdState.url === app?.url ? jdState.data : null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        aria-modal="true"
        className="flex max-h-[calc(100dvh-2rem)] w-full flex-col gap-0 overflow-hidden p-0 sm:max-w-3xl"
      >
        {app && (
          <>
            <DialogHeader className="shrink-0 gap-1.5 border-b px-5 py-4 pr-12 text-left">
              <DialogTitle className="flex items-center gap-2 text-base leading-snug">
                <span className="min-w-0 truncate">{app.title || "Untitled role"}</span>
                <a
                  href={app.url}
                  target="_blank"
                  rel="noreferrer"
                  aria-label={`Open job posting for ${app.company}`}
                  className="shrink-0 text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 outline-none rounded-xs"
                >
                  <ExternalLink className="size-4" />
                </a>
              </DialogTitle>
              <DialogDescription className="text-xs">
                {app.company}
                {app.location ? ` · ${app.location}` : ""} · applied{" "}
                {formatDate(app.applied_at || app.opened_at)}
              </DialogDescription>
              <div className="flex flex-wrap items-center gap-1.5 pt-1">
                <Badge variant={statusVariant(app.status)}>{app.status}</Badge>
                {app.source && <Badge variant="outline">{app.source}</Badge>}
                {app.tracking && <TrackingBadge status={app.tracking.status} />}
              </div>
            </DialogHeader>

            <div className="min-h-0 flex-1 overflow-y-auto scrollbar-thin">
              <div className="grid gap-5 p-5 lg:grid-cols-[320px_1fr]">
                <section aria-label="Tailored resume" className="flex flex-col gap-2">
                  <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                    Tailored PDF
                  </h3>
                  {app.pdf_url ? (
                    <>
                      <iframe
                        src={resumePdfUrl(app.branch)}
                        title={`Resume for ${app.title} at ${app.company}`}
                        className="h-64 w-full rounded-md border bg-muted lg:h-80"
                      />
                      <a href={resumePdfUrl(app.branch)} download className="block">
                        <Button variant="outline" size="sm" className="w-full">
                          <Download className="size-4" /> Download PDF
                        </Button>
                      </a>
                    </>
                  ) : (
                    <div className="flex h-32 flex-col items-center justify-center gap-2 rounded-md border border-dashed text-muted-foreground">
                      <FileText className="size-5" />
                      <p className="text-xs">No PDF was exported for this job.</p>
                    </div>
                  )}
                </section>

                <div className="flex min-w-0 flex-col gap-5">
                  <section aria-label="Form fields filled">
                    <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                      Fields you filled in
                    </h3>
                    <FieldList fields={app.fields} />
                  </section>

                  <section aria-label="Gmail tracking timeline">
                    <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                      Gmail activity
                    </h3>
                    {app.tracking ? (
                      <TrackingTimeline tracking={app.tracking} />
                    ) : (
                      <p className="rounded-md border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
                        Not tracked yet. Run a Gmail sync to look for company replies.
                      </p>
                    )}
                  </section>

                  {jd?.description && (
                    <section aria-label="Job description">
                      <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                        Job description
                      </h3>
                      <p className="max-h-56 overflow-y-auto whitespace-pre-wrap rounded-md border p-3 text-sm leading-relaxed scrollbar-thin">
                        {jd.description}
                      </p>
                    </section>
                  )}
                </div>
              </div>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
