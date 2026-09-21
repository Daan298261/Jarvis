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
import {
  decidePendingApproval,
  getPendingApproval,
  listPendingApprovals,
  pendingDetailFromPayload,
  pendingIdFromRow,
  type ApprovalDecideBody,
  type PendingApprovalDetail,
  type PendingApprovalSummary,
} from "./approvalsApi"

type PendingApprovalsContextValue = {
  pending: PendingApprovalSummary[]
  active: PendingApprovalDetail | null
  hasPending: boolean
  loading: boolean
  syncError: string | null
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
  const [syncError, setSyncError] = useState<string | null>(null)
  const localBoostRef = useRef<Map<string, PendingApprovalDetail>>(new Map())

  const mergeSummaries = useCallback((remote: PendingApprovalSummary[]) => {
    const map = new Map<string, PendingApprovalSummary>()
    for (const item of remote) {
      const id = pendingIdFromRow(item)
      if (id) map.set(id, { ...item, pending_id: id })
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
    try {
      const detail = await getPendingApproval(pendingId)
      localBoostRef.current.delete(pendingId)
      setActive(detail)
      setSyncError(null)
    } catch (err: unknown) {
      const boosted = localBoostRef.current.get(pendingId)
      if (boosted) {
        setActive(boosted)
        setSyncError(err instanceof Error ? err.message : "Could not load approval detail.")
        return
      }
      setActive(null)
      throw err
    }
  }, [])

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const remote = await listPendingApprovals()
      const merged = mergeSummaries(remote)
      setPending(merged)
      setSyncError(null)
      const remoteIds = new Set(remote.map((row) => pendingIdFromRow(row)))
      for (const id of [...localBoostRef.current.keys()]) {
        if (remoteIds.has(id)) localBoostRef.current.delete(id)
      }
      const nextId = merged[0]?.pending_id
      if (nextId) {
        await loadActive(nextId)
      } else {
        setActive(null)
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Approval queue unavailable."
      const boosted = mergeSummaries([])
      if (boosted.length > 0) {
        setPending(boosted)
        setSyncError(message)
        const nextId = boosted[0]?.pending_id
        if (nextId) {
          try {
            await loadActive(nextId)
          } catch {
            setActive(localBoostRef.current.get(nextId) || null)
          }
        }
      } else {
        setPending([])
        setActive(null)
        setSyncError(message)
      }
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
      const id = pendingIdFromRow(detail)
      if (!id) return
      const normalized = { ...detail, pending_id: id }
      localBoostRef.current.set(id, normalized)
      setActive(normalized)
      void refresh()
    },
    [refresh],
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
      syncError,
      refresh,
      ingestPayload,
      registerFrom428,
      decide,
      clearLocal,
    }),
    [pending, active, loading, syncError, refresh, ingestPayload, registerFrom428, decide, clearLocal],
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
