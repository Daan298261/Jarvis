import { api, ApiError, isApiError } from "../api"

export type PermissionCatalogItem = {
  id: string
  group: string
  title: string
  detail: string
  status: string
  persisted: string
  gated?: string | null
  offensive?: boolean
  gate_unlocked?: boolean
  reason?: string
}

export type ConfirmationPayload = {
  kind?: string
  id?: string
  pending_id?: string
  name?: string
  arguments?: Record<string, unknown>
  irreversible?: boolean
  permission_id?: string
  pending?: string[]
  title?: string
  detail?: string
  reason?: string
  options?: string[]
  catalog?: PermissionCatalogItem[]
  spoken_prompt?: string
  voice_reply_hint?: string
  requires_owner_input?: boolean
}

export type ApprovalDecideMode = "allow_once" | "always" | "deny"

export type PendingApprovalSummary = {
  pending_id: string
  status?: string
  title?: string
  action_kind?: string
  created_at?: string
}

export type PendingApprovalDetail = ConfirmationPayload & {
  pending_id: string
  status?: string
  permission_ids?: string[]
  action_kind?: string
  context?: Record<string, unknown>
  requires_owner_input?: boolean
}

export type PendingApprovalListResponse = {
  pending: PendingApprovalSummary[]
}

export type ApprovalDecideBody = {
  mode: ApprovalDecideMode
  owner_note?: string
}

export type ApprovalDecideResponse = {
  status?: string
  executed?: boolean
  result?: unknown
}

export function isPendingApprovalHttpError(err: unknown): err is ApiError {
  return isApiError(err) && err.status === 428
}

export function parsePendingApprovalFromHttpBody(body: unknown): PendingApprovalDetail | null {
  if (!body || typeof body !== "object") return null
  const record = body as Record<string, unknown>
  const detail = record.detail
  const payload =
    detail && typeof detail === "object"
      ? (detail as Record<string, unknown>)
      : record.status === "pending_approval"
        ? record
        : null
  if (!payload) return null
  const pendingId = String(payload.pending_id || payload.id || "").trim()
  if (!pendingId) return null
  return {
    ...(payload as ConfirmationPayload),
    pending_id: pendingId,
    status: typeof payload.status === "string" ? payload.status : "pending",
    requires_owner_input: inferRequiresOwnerInput(payload),
  }
}

export function inferRequiresOwnerInput(payload: Record<string, unknown>): boolean {
  if (payload.requires_owner_input === true) return true
  if (payload.requires_input === true) return true
  if (payload.input_required === true) return true
  const context = payload.context
  if (context && typeof context === "object") {
    const ctx = context as Record<string, unknown>
    if (ctx.requires_owner_input === true || ctx.requires_input === true || ctx.input_required === true) {
      return true
    }
  }
  return false
}

export function pendingDetailFromPayload(raw: unknown): PendingApprovalDetail | null {
  if (raw == null || raw === "") return null
  let payload: Record<string, unknown>
  if (typeof raw === "string") {
    try {
      payload = JSON.parse(raw) as Record<string, unknown>
    } catch {
      return null
    }
  } else if (typeof raw === "object") {
    payload = raw as Record<string, unknown>
  } else {
    return null
  }
  const pendingId = String(payload.pending_id || payload.id || "").trim()
  if (!pendingId) return null
  return {
    ...(payload as ConfirmationPayload),
    pending_id: pendingId,
    requires_owner_input: inferRequiresOwnerInput(payload),
  }
}

export async function listPendingApprovals(): Promise<PendingApprovalSummary[]> {
  const data = await api<PendingApprovalListResponse>("/api/approvals/pending")
  return data.pending || []
}

export async function getPendingApproval(pendingId: string): Promise<PendingApprovalDetail> {
  return api<PendingApprovalDetail>(`/api/approvals/pending/${encodeURIComponent(pendingId)}`)
}

export async function decidePendingApproval(
  pendingId: string,
  body: ApprovalDecideBody,
): Promise<ApprovalDecideResponse> {
  return api<ApprovalDecideResponse>(`/api/approvals/pending/${encodeURIComponent(pendingId)}/decide`, {
    method: "POST",
    body: JSON.stringify(body),
  })
}

export function extractPendingApprovalError(err: unknown): PendingApprovalDetail | null {
  if (!isPendingApprovalHttpError(err)) return null
  return parsePendingApprovalFromHttpBody(err.body)
}
