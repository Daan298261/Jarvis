import { createPortal } from "react-dom"
import { PermissionPrompt } from "./PermissionPrompt"
import { usePendingApprovals } from "./pendingApprovals"

export function PendingApprovalHost() {
  const { active, decide, syncError } = usePendingApprovals()
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
        {syncError && (
          <p className="permission-prompt-sync-error" role="status">
            {syncError}
          </p>
        )}
        <PermissionPrompt
          variant="modal"
          pendingId={pendingId}
          payload={active}
          onDecide={async (body) => {
            await decide(pendingId, body)
          }}
        />
      </div>
    </div>,
    document.body,
  )
}
