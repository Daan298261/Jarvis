import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react"
import { getPrivateKey } from "../api"
import {
  decidePendingApproval,
  getPendingApproval,
  listPendingApprovals,
  pendingDetailFromPayload,
  type ApprovalDecideBody,
  type PendingApprovalDetail,
  type PendingApprovalSummary,
} from "./approvalsApi"

type PendingApprovalsContextValue = {
  pending: PendingApprovalSummary[]
  active: PendingApprovalDetail | null
  hasPending: boolean
  loading: boolean
  refresh: () => Promise<void>
  ingestPayload: (raw: unknown) => void
  registerFrom428: (detail: PendingApprovalDetail) => void
  decide: (pendingId: string, body: ApprovalDecideBody) => Promise<void>
  clearLocal: (pendingId: string) => void
}

const PendingApprovalsContext = createContext<PendingApprovalsContextValue | null>(null)

const POLL_MS = 2000

export function PendingApprovalsProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<PendingApprovalSummary[]>([])
  const [active, setActive] = useState<PendingApprovalDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const localBoostRef = useRef<Map<string, PendingApprovalDetail>>(new Map())

  const mergeSummaries = useCallback((remote: PendingApprovalSummary[]) => {
    const map = new Map<string, PendingApprovalSummary>()
    for (const item of remote) {
      if (item.pending_id) map.set(item.pending_id, item)
    }
    for (const [id, detail] of localBoostRef.current) {
      if (!map.has(id)) {
        map.set(id, {
          pending_id: id,
          title: detail.title,
          status: detail.status || "pending",
          action_kind: detail.action_kind,
        })
      }
    }
    return [...map.values()].sort((a, b) => a.pending_id.localeCompare(b.pending_id))
  }, [])

  const loadActive = useCallback(async (pendingId: string) => {
    const boosted = localBoostRef.current.get(pendingId)
    if (boosted) {
      setActive(boosted)
      return
    }
    try {
      const detail = await getPendingApproval(pendingId)
      setActive({
        ...detail,
        pending_id: detail.pending_id || pendingId,
      })
    } catch {
      if (boosted) setActive(boosted)
    }
  }, [])

  const refresh = useCallback(async () => {
    if (!getPrivateKey()) {
      setPending([])
      setActive(null)
      return
    }
    setLoading(true)
    try {
      const remote = await listPendingApprovals()
      const merged = mergeSummaries(remote)
      setPending(merged)
      const nextId = merged[0]?.pending_id
      if (nextId) {
        await loadActive(nextId)
      } else {
        setActive(null)
      }
    } catch {
      const localOnly = mergeSummaries([])
      setPending(localOnly)
      const nextId = localOnly[0]?.pending_id
      if (nextId) await loadActive(nextId)
      else setActive(null)
    } finally {
      setLoading(false)
    }
  }, [loadActive, mergeSummaries])

  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => void refresh(), POLL_MS)
    return () => window.clearInterval(timer)
  }, [refresh])

  const registerFrom428 = useCallback(
    (detail: PendingApprovalDetail) => {
      localBoostRef.current.set(detail.pending_id, detail)
      setPending((current) => mergeSummaries(current))
      setActive(detail)
    },
    [mergeSummaries],
  )

  const ingestPayload = useCallback(
    (raw: unknown) => {
      const detail = pendingDetailFromPayload(raw)
      if (!detail) return
      registerFrom428(detail)
    },
    [registerFrom428],
  )

  const clearLocal = useCallback((pendingId: string) => {
    localBoostRef.current.delete(pendingId)
  }, [])

  const decide = useCallback(
    async (pendingId: string, body: ApprovalDecideBody) => {
      await decidePendingApproval(pendingId, body)
      clearLocal(pendingId)
      await refresh()
    },
    [clearLocal, refresh],
  )

  const value = useMemo(
    () => ({
      pending,
      active,
      hasPending: pending.length > 0,
      loading,
      refresh,
      ingestPayload,
      registerFrom428,
      decide,
      clearLocal,
    }),
    [pending, active, loading, refresh, ingestPayload, registerFrom428, decide, clearLocal],
  )

  return <PendingApprovalsContext.Provider value={value}>{children}</PendingApprovalsContext.Provider>
}

export function usePendingApprovals(): PendingApprovalsContextValue {
  const ctx = useContext(PendingApprovalsContext)
  if (!ctx) {
    throw new Error("usePendingApprovals must be used within PendingApprovalsProvider")
  }
  return ctx
}

export function useOptionalPendingApprovals(): PendingApprovalsContextValue | null {
  return useContext(PendingApprovalsContext)
}
