"use client"

import type { ApplicationEntry, TrackingSummary } from "@/lib/api"

type SeedInput = Omit<ApplicationEntry, "pdf_url" | "fields" | "tracking"> & {
  fields: Record<string, string>
  tracking: ApplicationEntry["tracking"]
}

function entry(e: SeedInput): ApplicationEntry {
  return {
    ...e,
    pdf_url: e.branch ? `/api/resumes/${e.branch}` : "",
  }
}

export const seedApplications: ApplicationEntry[] = (
  [
    {
    url: "https://jobs.stripe.com/jobs/1",
    company: "Stripe",
    title: "Senior Frontend Engineer",
    source: "remoteok",
    status: "submitted",
    branch: "apply/sr-frontend-stripe",
    pdf: "/tmp/apply-sr-frontend-stripe.pdf",
    opened_at: "2026-08-19",
    applied_at: "2026-08-19",
    note: "submitted; matched fields: full_name, email; PDF uploaded: true",
    remote: true,
    location: "Remote (US)",
    fields: {
      full_name: "Mueed Bhat",
      email: "mueed@example.com",
      phone: "+91 98765 43210",
      linkedin: "linkedin.com/in/mueedbhat",
    },
    tracking: {
      status: "offer",
      last_checked: "2026-08-20T14:32:00Z",
      source: "gmail",
      emails: [
        {
          id: "s1",
          from: "recruiting@stripe.com",
          subject: "Your offer from Stripe",
          snippet: "We are pleased to extend an offer for the Senior Frontend Engineer role…",
          date: "2026-08-20T12:00:00Z",
          kind: "offer",
        },
        {
          id: "s2",
          from: "no-reply@stripe.com",
          subject: "Application received",
          snippet: "Thanks for applying to Stripe. We have received your application.",
          date: "2026-08-19T09:00:00Z",
          kind: "confirmation",
        },
      ],
    },
  },
  {
    url: "https://linear.app/careers/2",
    company: "Linear",
    title: "Product Engineer",
    source: "weworkremotely",
    status: "submitted",
    branch: "apply/product-engineer-linear",
    pdf: "/tmp/apply-product-engineer-linear.pdf",
    opened_at: "2026-08-18",
    applied_at: "2026-08-18",
    note: "submitted; matched fields: email; PDF uploaded: true",
    remote: true,
    location: "Remote (Global)",
    fields: {
      full_name: "Mueed Bhat",
      email: "mueed@example.com",
      website: "mueed.dev",
    },
    tracking: {
      status: "interview",
      last_checked: "2026-08-20T14:32:00Z",
      source: "gmail",
      emails: [
        {
          id: "l1",
          from: "people@linear.app",
          subject: "Next steps — Product Engineer",
          snippet: "We were impressed by your background. Could we schedule a call next week?",
          date: "2026-08-20T08:00:00Z",
          kind: "interview",
        },
        {
          id: "l2",
          from: "no-reply@linear.app",
          subject: "Got your application",
          snippet: "Thank you for applying to Linear.",
          date: "2026-08-18T10:00:00Z",
          kind: "confirmation",
        },
      ],
    },
  },
  {
    url: "https://vercel.com/careers/3",
    company: "Vercel",
    title: "Frontend Infrastructure Engineer",
    source: "remoteok",
    status: "prepared",
    branch: "apply/frontend-infra-vercel",
    pdf: "/tmp/apply-frontend-infra-vercel.pdf",
    opened_at: "2026-08-18",
    applied_at: "",
    note: "",
    remote: true,
    location: "Remote (US)",
    fields: {},
    tracking: null,
  },
  {
    url: "https://notion.so/careers/4",
    company: "Notion",
    title: "Senior Product Engineer",
    source: "linkedin",
    status: "submitted",
    branch: "apply/senior-pm-notion",
    pdf: "/tmp/apply-senior-pm-notion.pdf",
    opened_at: "2026-08-17",
    applied_at: "2026-08-17",
    note: "submitted; matched fields: full_name, email, phone; PDF uploaded: false (0 file inputs)",
    remote: false,
    location: "New York, NY",
    fields: {
      full_name: "Mueed Bhat",
      email: "mueed@example.com",
      phone: "+91 98765 43210",
    },
    tracking: {
      status: "confirmation",
      last_checked: "2026-08-20T14:32:00Z",
      source: "gmail",
      emails: [
        {
          id: "n1",
          from: "careers@notion.so",
          subject: "We received your application",
          snippet: "Thanks for your interest in Notion — your application was received.",
          date: "2026-08-17T16:00:00Z",
          kind: "confirmation",
        },
      ],
    },
  },
  {
    url: "https://datadog.com/careers/5",
    company: "Datadog",
    title: "Frontend Platform Engineer",
    source: "remoteok",
    status: "failed",
    branch: "apply/fe-platform-datadog",
    pdf: "/tmp/apply-fe-platform-datadog.pdf",
    opened_at: "2026-08-16",
    applied_at: "2026-08-16",
    note: "ego-browser failed: submit button not found",
    remote: true,
    location: "Remote (US)",
    fields: {},
    tracking: null,
  },
  {
    url: "https://figma.com/careers/6",
    company: "Figma",
    title: "Design Engineer",
    source: "weworkremotely",
    status: "submitted",
    branch: "apply/design-engineer-figma",
    pdf: "/tmp/apply-design-engineer-figma.pdf",
    opened_at: "2026-08-15",
    applied_at: "2026-08-15",
    note: "submitted; matched fields: email, linkedin; PDF uploaded: true",
    remote: false,
    location: "San Francisco, CA",
    fields: {
      email: "mueed@example.com",
      linkedin: "linkedin.com/in/mueedbhat",
    },
    tracking: {
      status: "rejected",
      last_checked: "2026-08-20T14:32:00Z",
      source: "gmail",
      emails: [
        {
          id: "f1",
          from: "talent@figma.com",
          subject: "Update on your application",
          snippet:
            "After careful consideration, we have decided to move forward with other candidates.",
          date: "2026-08-19T11:00:00Z",
          kind: "rejected",
        },
        {
          id: "f2",
          from: "no-reply@figma.com",
          subject: "Application received",
          snippet: "Thank you for applying to Figma.",
          date: "2026-08-15T13:00:00Z",
          kind: "confirmation",
        },
      ],
    },
  },
  {
    url: "https://gitlab.com/jobs/7",
    company: "GitLab",
    title: "Full-Stack Engineer",
    source: "remoteok",
    status: "prepared",
    branch: "apply/fullstack-gitlab",
    pdf: "/tmp/apply-fullstack-gitlab.pdf",
    opened_at: "2026-08-15",
    applied_at: "",
    note: "",
    remote: true,
    location: "Remote (Global)",
    fields: {},
    tracking: null,
  },
  {
    url: "https://cloudflare.com/careers/8",
    company: "Cloudflare",
    title: "Network Engineer",
    source: "linkedin",
    status: "skipped",
    branch: "apply/network-cf",
    pdf: "",
    opened_at: "2026-08-14",
    applied_at: "",
    note: "",
    remote: true,
    location: "Austin, TX",
    fields: {},
    tracking: null,
  },
  {
    url: "https://discord.com/careers/9",
    company: "Discord",
    title: "Staff Frontend Engineer",
    source: "remoteok",
    status: "submitted",
    branch: "apply/staff-fe-discord",
    pdf: "/tmp/apply-staff-fe-discord.pdf",
    opened_at: "2026-08-13",
    applied_at: "2026-08-13",
    note: "submitted; matched fields: full_name, email; PDF uploaded: true",
    remote: true,
    location: "Remote (US)",
    fields: {
      full_name: "Mueed Bhat",
      email: "mueed@example.com",
    },
    tracking: {
      status: "interview",
      last_checked: "2026-08-20T14:32:00Z",
      source: "gmail",
      emails: [
        {
          id: "d1",
          from: "recruiting@discord.com",
          subject: "Interview invitation",
          snippet: "We'd like to invite you to a technical interview with the hiring team.",
          date: "2026-08-19T15:00:00Z",
          kind: "interview",
        },
      ],
    },
  },
  {
    url: "https://anthropic.com/careers/10",
    company: "Anthropic",
    title: "Applied AI Engineer",
    source: "weworkremotely",
    status: "prepared",
    branch: "apply/applied-ai-anthropic",
    pdf: "/tmp/apply-applied-ai-anthropic.pdf",
    opened_at: "2026-08-12",
    applied_at: "",
    note: "",
    remote: true,
    location: "Remote (US)",
    fields: {},
    tracking: null,
  },
  {
    url: "https://supabase.com/careers/11",
    company: "Supabase",
    title: "Developer Experience Engineer",
    source: "remoteok",
    status: "submitted",
    branch: "apply/dx-supabase",
    pdf: "/tmp/apply-dx-supabase.pdf",
    opened_at: "2026-08-11",
    applied_at: "2026-08-11",
    note: "submitted; matched fields: email, website; PDF uploaded: true",
    remote: true,
    location: "Remote (Global)",
    fields: {
      email: "mueed@example.com",
      website: "mueed.dev",
    },
    tracking: {
      status: "confirmation",
      last_checked: "2026-08-20T14:32:00Z",
      source: "gmail",
      emails: [
        {
          id: "sb1",
          from: "people@supabase.com",
          subject: "Application received",
          snippet: "Thanks for applying to Supabase!",
          date: "2026-08-11T09:30:00Z",
          kind: "confirmation",
        },
      ],
    },
  },
  {
    url: "https://planetscale.com/careers/12",
    company: "PlanetScale",
    title: "Database Engineer",
    source: "linkedin",
    status: "submitted",
    branch: "apply/db-planetscale",
    pdf: "/tmp/apply-db-planetscale.pdf",
    opened_at: "2026-08-10",
    applied_at: "2026-08-10",
    note: "submitted; matched fields: full_name, email; PDF uploaded: true",
    remote: false,
    location: "San Francisco, CA",
    fields: {
      full_name: "Mueed Bhat",
      email: "mueed@example.com",
    },
    tracking: {
      status: "rejected",
      last_checked: "2026-08-20T14:32:00Z",
      source: "gmail",
      emails: [
        {
          id: "p1",
          from: "talent@planetscale.com",
          subject: "Your application",
          snippet: "We regret to inform you that we are unable to offer you the position.",
          date: "2026-08-14T10:00:00Z",
          kind: "rejected",
        },
      ],
    },
  },
  ] as SeedInput[]
).map(entry)

export function seedTrackingTotals(): TrackingSummary {
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
  for (const app of seedApplications) {
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

export function seedDays(): Record<string, ApplicationEntry[]> {
  const days: Record<string, ApplicationEntry[]> = {}
  for (const app of seedApplications) {
    const day = app.opened_at || app.applied_at || "unknown"
    ;(days[day] ??= []).push(app)
  }
  return days
}
