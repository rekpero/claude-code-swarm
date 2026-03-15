import { useState } from 'react'
import { Modal } from '../ui/Modal'
import { Button } from '../ui/Button'
import { Badge } from '../ui/Badge'
import { IssueStatusBadge } from './IssueStatusBadge'
import { ArrowRight, Check, AlertTriangle } from 'lucide-react'

const STATUSES = [
  { value: 'pending', label: 'Pending', variant: 'yellow', description: 'Queued for agent pickup' },
  { value: 'pr_created', label: 'PR Created', variant: 'blue', description: 'Pull request has been opened' },
  { value: 'needs_human', label: 'Needs Human', variant: 'red', description: 'Requires manual intervention' },
  { value: 'resolved', label: 'Resolved', variant: 'green', description: 'Issue is done' },
]

export function UpdateStatusModal({ open, onClose, issue, onUpdate }) {
  const [selected, setSelected] = useState(null)
  const [updating, setUpdating] = useState(false)
  const [error, setError] = useState(null)

  if (!issue) return null

  const currentStatus = issue.status
  const available = STATUSES.filter(s => s.value !== currentStatus)

  const handleUpdate = () => {
    if (!selected) return
    setUpdating(true)
    setError(null)
    onUpdate(
      { issueNumber: issue.issue_number, status: selected, workspaceId: issue.workspace_id },
      {
        onSuccess: () => {
          setUpdating(false)
          setSelected(null)
          setError(null)
          onClose()
        },
        onError: (err) => {
          setUpdating(false)
          setError(err?.message || 'Failed to update status')
        },
      }
    )
  }

  const handleClose = () => {
    setSelected(null)
    setError(null)
    onClose()
  }

  return (
    <Modal open={open} onClose={handleClose} title="Update Issue Status" maxWidth="400px">
      {/* Issue info */}
      <div className="mb-5 px-3 py-2.5 rounded-lg bg-[var(--bg)] border border-[var(--border-subtle)]">
        <div className="flex items-center gap-2 mb-1.5">
          <span className="text-[10px] font-mono text-[var(--text-muted)]">#{issue.issue_number}</span>
          <IssueStatusBadge status={currentStatus} />
        </div>
        <span className="text-[11px] text-[var(--text)] leading-snug line-clamp-2">
          {issue.title || `Issue #${issue.issue_number}`}
        </span>
      </div>

      {/* Status options */}
      <div className="space-y-1.5 mb-5">
        <label className="block text-[9px] uppercase tracking-widest text-[var(--text-muted)] font-medium mb-2">
          Change to
        </label>
        {available.map((status) => {
          const isSelected = selected === status.value
          return (
            <button
              key={status.value}
              onClick={() => setSelected(status.value)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg border transition-all duration-150 text-left cursor-pointer group ${
                isSelected
                  ? 'border-[var(--accent-border)] bg-[var(--accent-dim)]'
                  : 'border-[var(--border-subtle)] bg-[var(--bg)] hover:border-[var(--border)] hover:bg-[var(--surface-hover)]'
              }`}
            >
              <div className={`flex items-center justify-center w-4 h-4 rounded-full border transition-all duration-150 ${
                isSelected
                  ? 'border-[var(--accent)] bg-[var(--accent)]'
                  : 'border-[var(--text-muted)] group-hover:border-[var(--text-dim)]'
              }`}>
                {isSelected && <Check size={9} className="text-white" strokeWidth={3} />}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <Badge variant={status.variant}>{status.label}</Badge>
                </div>
                <span className="text-[10px] text-[var(--text-muted)] mt-0.5 block">
                  {status.description}
                </span>
              </div>
            </button>
          )
        })}
      </div>

      {/* Transition preview */}
      {selected && (
        <div className="flex items-center justify-center gap-3 mb-5 py-2.5 px-3 rounded-lg bg-[var(--bg)] border border-[var(--border-subtle)] animate-fade-in">
          <IssueStatusBadge status={currentStatus} />
          <ArrowRight size={12} className="text-[var(--text-muted)]" />
          <IssueStatusBadge status={selected} />
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 mb-4 px-3 py-2 rounded-lg bg-[var(--red-dim)] border border-[rgba(248,113,113,0.15)] animate-fade-in">
          <AlertTriangle size={11} className="text-[var(--red)] flex-shrink-0" />
          <span className="text-[10px] text-[var(--red)]">{error}</span>
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={handleClose} disabled={updating}>
          Cancel
        </Button>
        <Button
          variant="primary"
          size="sm"
          onClick={handleUpdate}
          loading={updating}
          disabled={!selected}
        >
          Update Status
        </Button>
      </div>
    </Modal>
  )
}
