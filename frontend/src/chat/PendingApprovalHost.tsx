import { createPortal } from "react-dom"
import { PermissionPrompt } from "./PermissionPrompt"
import { usePendingApprovals } from "./pendingApprovals"

export function PendingApprovalHost() {
  const { active, decide, refresh, clearLocal } = usePendingApprovals()
  if (!active?.pending_id) return null

  const pendingId = active.pending_id

  return createPortal(
    <div className="permission-modal-backdrop" role="presentation">
      <div
        className="permission-modal-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="permission-modal-title"
      >
        <PermissionPrompt
          variant="modal"
          pendingId={pendingId}
          payload={active}
          onDecide={async (body) => {
            await decide(pendingId, body)
          }}
          onDismiss={() => {
            clearLocal(pendingId)
            void refresh()
          }}
        />
      </div>
    </div>,
    document.body,
  )
}
