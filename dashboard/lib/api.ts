"use client"

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000"

export type TrackingStatus =
  | "no_response"
  | "confirmation"
  | "rejected"
  | "interview"
  | "offer"

export interface TrackedEmail {
  id: string
  from: string
  subject: string
  snippet: string
  date: string
  kind: TrackingStatus | "other"
}

export interface TrackingInfo {
  status: TrackingStatus
  last_checked?: string
  source?: string | null
  emails: TrackedEmail[]
}

export interface JobLead {
  url: string
  company: string
  title: string
  source: string
  remote: boolean
  location?: string
}

export interface JobDescription {
  url: string
  company: string
  title: string
  description: string
  keywords: string[]
}

export interface ApplicationEntry {
  url: string
  status: string
  branch: string
  pdf: string
  pdf_url: string
  opened_at: string
  applied_at: string
  note: string
  fields: Record<string, string>
  company: string
  title: string
  source: string
  location: string
  remote: boolean
  tracking: TrackingInfo | null
}

export interface RunStatus {
  running: boolean
  status: string
  started?: string
  output: string
}

export interface TrackingSummary {
  totals: {
    applied: number
    no_response: number
    confirmation: number
    rejected: number
    interview: number
    offer: number
  }
  by_status: Record<string, number>
  last_synced: string
}

export interface SyncResult {
  status: "ok" | "unconfigured" | "no_apps" | "error"
  message: string
  updated: number
  entries: unknown[]
  last_synced: string | null
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

export function resumePdfUrl(branch: string): string {
  return `${API_BASE}/api/resumes/${branch}`
}

export function statusVariant(status: string): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "submitted":
      return "default"
    case "prepared":
    case "pre_fill":
      return "secondary"
    case "failed":
      return "destructive"
    default:
      return "outline"
  }
}

export const trackingLabel: Record<TrackingStatus, string> = {
  no_response: "Awaiting",
  confirmation: "Confirmed",
  rejected: "Rejected",
  interview: "Interview",
  offer: "Offer",
}

export function trackingClass(status: TrackingStatus | "other"): string {
  switch (status) {
    case "offer":
      return "border-transparent bg-emerald-500/15 text-emerald-400 dark:bg-emerald-400/15"
    case "interview":
      return "border-transparent bg-violet-500/15 text-violet-400 dark:bg-violet-400/15"
    case "confirmation":
      return "border-transparent bg-sky-500/15 text-sky-400 dark:bg-sky-400/15"
    case "rejected":
      return "border-transparent bg-red-500/15 text-red-400 dark:bg-red-400/15"
    default:
      return "border-border text-muted-foreground"
  }
}

export function formatDate(iso: string): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" })
}

export function formatDateTime(iso: string): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  })
}
