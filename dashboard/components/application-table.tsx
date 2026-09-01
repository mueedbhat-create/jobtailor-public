"use client"

import * as React from "react"
import { Download, ExternalLink } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { TrackingBadge } from "@/components/tracking-timeline"
import type { ApplicationEntry } from "@/lib/api"
import { resumePdfUrl, statusVariant, formatDate } from "@/lib/api"
import { cn } from "@/lib/utils"

function Avatar({ name }: { name: string }) {
  const letter = (name || "?").trim().charAt(0).toUpperCase()
  return (
    <span
      aria-hidden
      className="grid size-7 shrink-0 place-items-center rounded-full bg-muted text-xs font-semibold text-muted-foreground"
    >
      {letter}
    </span>
  )
}

function RowCells({ app }: { app: ApplicationEntry }) {
  return (
    <>
      <TableCell>
        <div className="flex min-w-0 items-center gap-2.5">
          <Avatar name={app.company} />
          <div className="min-w-0">
            <p className="truncate font-medium leading-snug">{app.title}</p>
            <p className="truncate text-xs text-muted-foreground">
              {app.company}
              {app.location ? ` · ${app.location}` : ""}
            </p>
          </div>
        </div>
      </TableCell>
      <TableCell>
        <Badge variant="outline">{app.source || "—"}</Badge>
      </TableCell>
      <TableCell className="whitespace-nowrap tabular-nums">
        {formatDate(app.applied_at || app.opened_at)}
      </TableCell>
      <TableCell>
        <Badge variant={statusVariant(app.status)}>{app.status}</Badge>
      </TableCell>
      <TableCell>
        {app.tracking ? (
          <TrackingBadge status={app.tracking.status} />
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        )}
      </TableCell>
      <TableCell className="text-right">
        <div className="flex items-center justify-end gap-1">
          {app.branch && (
            <a
              href={resumePdfUrl(app.branch)}
              download
              onClick={(e) => e.stopPropagation()}
              aria-label={`Download PDF for ${app.title}`}
              className="rounded-xs p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 outline-none"
            >
              <Download className="size-4" />
            </a>
          )}
          <a
            href={app.url}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            aria-label={`Open posting for ${app.title}`}
            className="rounded-xs p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 outline-none"
          >
            <ExternalLink className="size-4" />
          </a>
        </div>
      </TableCell>
    </>
  )
}

export function ApplicationTable({
  apps,
  onOpen,
}: {
  apps: ApplicationEntry[]
  onOpen: (app: ApplicationEntry) => void
}) {
  if (!apps.length) return null

  return (
    <>
      <div className="hidden rounded-lg border bg-card md:block">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Job</TableHead>
              <TableHead>Source</TableHead>
              <TableHead>Applied</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Tracking</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {apps.map((app) => (
              <TableRow
                key={app.url}
                role="button"
                tabIndex={0}
                aria-label={`Open details for ${app.title} at ${app.company}`}
                onClick={() => onOpen(app)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault()
                    onOpen(app)
                  }
                }}
                className="cursor-pointer outline-none focus-visible:bg-muted/60 focus-visible:ring-[3px] focus-visible:ring-ring/40"
              >
                <RowCells app={app} />
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <ul className="flex flex-col gap-2.5 md:hidden" aria-label="Applications">
        {apps.map((app) => (
          <li key={app.url}>
            <div
              role="button"
              tabIndex={0}
              aria-label={`Open details for ${app.title} at ${app.company}`}
              onClick={() => onOpen(app)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault()
                  onOpen(app)
                }
              }}
              className={cn(
                "w-full cursor-pointer rounded-lg border bg-card p-3.5 text-left outline-none transition-colors",
                "focus-visible:ring-[3px] focus-visible:ring-ring/50 hover:border-foreground/20"
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex min-w-0 items-start gap-2.5">
                  <Avatar name={app.company} />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium leading-snug">{app.title}</p>
                    <p className="truncate text-xs text-muted-foreground">{app.company}</p>
                  </div>
                </div>
                {app.tracking ? <TrackingBadge status={app.tracking.status} /> : null}
              </div>
              <div className="mt-2.5 flex flex-wrap items-center gap-1.5 pl-[42px]">
                <Badge variant={statusVariant(app.status)}>{app.status}</Badge>
                <Badge variant="outline">{app.source || "—"}</Badge>
                <span className="ml-auto text-xs tabular-nums text-muted-foreground">
                  {formatDate(app.applied_at || app.opened_at)}
                </span>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </>
  )
}
