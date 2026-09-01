"use client"

import * as React from "react"

import {
  apiGet,
  apiPost,
  type ApplicationEntry,
  type RunStatus,
  type SyncResult,
  type TrackingSummary,
} from "@/lib/api"
import { seedApplications } from "@/lib/seed"

export interface AppState {
  loading: boolean
  error: string | null
  mock: boolean
  apps: ApplicationEntry[]
  internships: ApplicationEntry[]
  totals: TrackingSummary
  run: RunStatus
  lastSyncAttempt: number
  refresh: () => Promise<void>
  triggerRun: (mode: string, limit: number) => Promise<void>
  syncTracking: () => Promise<SyncResult | null>
}

const IDLE_TOTALS: TrackingSummary = {
  totals: { applied: 0, no_response: 0, confirmation: 0, rejected: 0, interview: 0, offer: 0 },
  by_status: {},
  last_synced: "",
}

const AppStateContext = React.createContext<AppState | null>(null)

export function useAppState(): AppState {
  const ctx = React.useContext(AppStateContext)
  if (!ctx) throw new Error("useAppState must be used within AppProvider")
  return ctx
}

function computeTotals(apps: ApplicationEntry[]): TrackingSummary {
  const totals = {
    applied: 0,
    no_response: 0,
    confirmation: 0,
    rejected: 0,
    interview: 0,
    offer: 0,
  }
  const by_status: Record<string, number> = {}
  let last_synced = ""
  for (const app of apps) {
    by_status[app.status] = (by_status[app.status] ?? 0) + 1
    if (app.status === "submitted" || app.applied_at) {
      totals.applied += 1
      const kind = app.tracking?.status ?? "no_response"
      if (kind in totals) totals[kind as keyof typeof totals] += 1
      last_synced = app.tracking?.last_checked ?? last_synced
    }
  }
  return { totals, by_status, last_synced }
}

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [mock, setMock] = React.useState(false)
  const [apps, setApps] = React.useState<ApplicationEntry[]>([])
  const [internships, setInternships] = React.useState<ApplicationEntry[]>([])
  const [run, setRun] = React.useState<RunStatus>({ running: false, status: "idle", output: "" })
  const [lastSyncAttempt, setLastSyncAttempt] = React.useState(0)

  const loadFromApi = React.useCallback(async (): Promise<boolean> => {
    try {
      const [jobsData, internData, runStatus] = await Promise.all([
        apiGet<{ days: Record<string, Omit<ApplicationEntry, "tracking">[]> }>("/api/applications"),
        apiGet<{ days: Record<string, Omit<ApplicationEntry, "tracking">[]> }>("/api/applications?track=internships"),
        apiGet<RunStatus>("/api/run/status"),
      ])
      const flat = Object.values(jobsData.days ?? {}).flat() as ApplicationEntry[]
      const flatIntern = Object.values(internData.days ?? {}).flat() as ApplicationEntry[]
      setApps(flat)
      setInternships(flatIntern)
      setRun(runStatus)
      setError(null)
      return true
    } catch {
      return false
    }
  }, [])

  React.useEffect(() => {
    let cancelled = false
    const params = new URLSearchParams(window.location.search)
    const forcedMock =
      params.has("mock") || process.env.NEXT_PUBLIC_MOCK === "1"

    const init = async () => {
      const ok = await loadFromApi()
      if (cancelled) return
      if (!ok && forcedMock) {
        setApps(seedApplications)
        setMock(true)
        setError(null)
      } else if (!ok) {
        setError("Could not reach the JobTailor API. Is it running? Start it with `jobtailor serve`.")
      }
      setLoading(false)
    }
    init()
    return () => {
      cancelled = true
    }
  }, [loadFromApi])

  React.useEffect(() => {
    const interval = setInterval(async () => {
      const ok = await loadFromApi()
      if (ok) {
        setMock((m) => (m ? false : m))
        setError(null)
      } else if (!mock) {
        setError("Lost connection to the JobTailor API.")
        setLastSyncAttempt(Date.now())
      }
      try {
        setRun(await apiGet<RunStatus>("/api/run/status"))
      } catch {
        /* handled above */
      }
    }, 15000)
    return () => clearInterval(interval)
  }, [loadFromApi, mock])

  const refresh = React.useCallback(async () => {
    setLoading(true)
    const ok = await loadFromApi()
    if (ok) {
      setMock(false)
      setError(null)
    } else if (!mock) {
      setError("Could not reach the JobTailor API. Is it running?")
    }
    setLoading(false)
  }, [loadFromApi, mock])

  const triggerRun = React.useCallback(
    async (mode: string, limit: number) => {
      await apiPost("/api/run", { mode, limit })
      await loadFromApi()
    },
    [loadFromApi]
  )

  const syncTracking = React.useCallback(async (): Promise<SyncResult | null> => {
    try {
      return await apiPost<SyncResult>("/api/tracking/sync", {})
    } catch {
      return null
    }
  }, [])

  const totals = React.useMemo(() => computeTotals(apps), [apps])

  const value = React.useMemo<AppState>(
    () => ({
      loading,
      error,
      mock,
      apps,
      internships,
      totals,
      run,
      lastSyncAttempt,
      refresh,
      triggerRun,
      syncTracking,
    }),
    [loading, error, mock, apps, internships, totals, run, lastSyncAttempt, refresh, triggerRun, syncTracking]
  )

  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>
}

export { IDLE_TOTALS }
