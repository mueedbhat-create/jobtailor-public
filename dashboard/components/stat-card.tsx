"use client"

import type { LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"
import { Skeleton } from "@/components/ui/skeleton"

export function StatCard({
  label,
  value,
  icon: Icon,
  tone = "neutral",
  loading,
}: {
  label: string
  value: number | string
  icon: LucideIcon
  tone?: "neutral" | "sky" | "violet" | "emerald" | "red"
  loading?: boolean
}) {
  const tones: Record<string, string> = {
    neutral: "text-muted-foreground",
    sky: "text-sky-400",
    violet: "text-violet-400",
    emerald: "text-emerald-400",
    red: "text-red-400",
  }
  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
        <Icon className={cn("size-4", tones[tone])} />
      </div>
      {loading ? (
        <Skeleton className="mt-2 h-7 w-12" />
      ) : (
        <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      )}
    </div>
  )
}
