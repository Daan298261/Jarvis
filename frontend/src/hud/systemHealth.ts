import type { LicenseStatus } from "../api"
import { SETUP_PROBLEM_WORKING, ownerFacingApiMessage } from "../setup/ownerFacing"

export type SelfCheckItem = {
  id: string
  label: string
  status: "ready" | "starting" | "degraded" | "missing"
  detail: string
}

export type SelfCheckSnapshot = {
  overall?: "ready" | "initializing" | "degraded" | "blocked"
  checks?: SelfCheckItem[]
}

export type HealthIssue = {
  id: string
  title: string
  detail: string
  href?: string
}

type ModelSnap = {
  loaded?: boolean
  loading?: boolean
  active_model?: string
  last_error?: string
} | null

const LICENSE_FAIL = new Set(["tamper_detected", "invalid_signature", "expired", "cluster_mismatch"])

export function collectHealthIssues(input: {
  model: ModelSnap
  license: LicenseStatus | null
  selfCheck: SelfCheckSnapshot | null
  apiError?: string | null
}): HealthIssue[] {
  const issues: HealthIssue[] = []
  const apiError = (input.apiError || "").trim()
  if (apiError) {
    issues.push({
      id: "api",
      title: "Portal cannot reach the local API",
      detail: ownerFacingApiMessage(apiError),
      href: "/system",
    })
  }

  const checks = input.selfCheck?.checks || []
  for (const check of checks) {
    if (check.status === "ready" || check.status === "starting") continue
    issues.push({
      id: `check-${check.id}`,
      title: check.label,
      detail: check.detail || `Status: ${check.status}`,
      href: check.id === "inference" ? "/model" : "/system",
    })
  }

  const model = input.model
  if (
    !checks.some((item) => item.id === "inference") &&
    model &&
    !model.loaded &&
    !model.loading &&
    model.last_error
  ) {
    issues.push({
      id: "model",
      title: "Local inference",
      detail: model.last_error,
      href: "/model",
    })
  }

  const code = String(input.license?.validation?.status || input.license?.last_status || "").toLowerCase()
  if (LICENSE_FAIL.has(code)) {
    issues.push({
      id: "license",
      title: "License",
      detail: SETUP_PROBLEM_WORKING,
      href: "/license",
    })
  }

  return issues
}

export function healthSpokenSummary(issues: HealthIssue[]): string {
  if (!issues.length) return ""
  const parts = issues.map((issue) => `${issue.title}: ${issue.detail}`.replace(/\s+/g, " ").trim())
  if (parts.length === 1) {
    return `Jarvis is degraded. ${parts[0]}`
  }
  return `Jarvis is degraded. ${parts.length} problems. ${parts.join(" ")}`
}
