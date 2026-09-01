"use client"

import { Mail, XCircle, CalendarClock, Trophy } from "lucide-react"

import type { TrackingInfo, TrackingStatus } from "@/lib/api"
import { trackingClass, trackingLabel, formatDateTime } from "@/lib/api"
import { cn } from "@/lib/utils"

const KIND_ICON: Record<TrackingStatus | "other", typeof Mail> = {
  confirmation: Mail,
  interview: CalendarClock,
  offer: Trophy,
  rejected: XCircle,
  no_response: Mail,
  other: Mail,
}

export function TrackingTimeline({ tracking }: { tracking: TrackingInfo }) {
  if (!tracking.emails.length) {
    return (
      <p className="rounded-md border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
        No emails matched yet. Run a Gmail sync to look for replies.
      </p>
    )
  }
  return (
    <ol className="relative space-y-4 pl-5">
      <span aria-hidden className="absolute top-2 bottom-2 left-[7px] w-px bg-border" />
      {tracking.emails.map((email) => {
        const Icon = KIND_ICON[email.kind] ?? Mail
        return (
          <li key={email.id} className="relative">
            <span
              aria-hidden
              className={cn(
                "absolute top-1 -left-5 grid size-[15px] place-items-center rounded-full border bg-card",
                email.kind === "other" ? "border-border" : "border-current"
              )}
            >
              <Icon className={cn("size-2.5", trackingClass(email.kind).split(" ").find((c) => c.startsWith("text-")))} />
            </span>
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <span
                className={cn(
                  "inline-flex items-center rounded-full border border-transparent px-2 py-0.5 text-xs font-medium",
                  trackingClass(email.kind)
                )}
              >
                {email.kind === "no_response" ? "awaiting" : email.kind}
              </span>
              <span className="truncate text-sm font-medium">{email.subject || "(no subject)"}</span>
            </div>
            <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
              {email.from ? `${email.from} · ` : ""}
              {email.snippet}
            </p>
            <time className="mt-0.5 block text-[11px] text-muted-foreground/70">
              {formatDateTime(email.date)}
            </time>
          </li>
        )
      })}
    </ol>
  )
}

export function TrackingBadge({ status }: { status: TrackingStatus }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border border-transparent px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        trackingClass(status)
      )}
    >
      {trackingLabel[status]}
    </span>
  )
}
