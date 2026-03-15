import { Settings, Plus, Check, AlertTriangle, LogOut } from 'lucide-react'
import { WorkspaceSwitcher } from './WorkspaceSwitcher'
import { useMetrics } from '../../hooks/useMetrics'
import { useGitSync } from '../../hooks/useGitSync'
import { useWorkspaceContext } from '../../context/WorkspaceContext'
import { useAuth } from '../../context/AuthContext'
import { formatDistanceToNow } from 'date-fns'

function SyncIndicator({ wsId }) {
  const { data, isLoading } = useGitSync(wsId)

  if (!wsId || isLoading || !data) return null

  if (data.synced) {
    return (
      <span
        className="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium text-[var(--green)] bg-[rgba(34,197,94,0.08)] border border-[rgba(34,197,94,0.15)]"
        title={`Local ${data.local_sha} = Remote ${data.remote_sha}`}
      >
        <Check size={9} />
        Synced
      </span>
    )
  }

  const behind = data.behind || 0
  const label = behind > 0 ? `${behind} behind` : 'Out of sync'

  return (
    <span
      className="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium text-[var(--yellow)] bg-[rgba(234,179,8,0.08)] border border-[rgba(234,179,8,0.15)]"
      title={`Local ${data.local_sha} ← Remote ${data.remote_sha}`}
    >
      <AlertTriangle size={9} />
      {label}
    </span>
  )
}

export function Header({ onAddWorkspace, onOpenSettings, onOpenPlanner }) {
  const { selectedWorkspaceId } = useWorkspaceContext()
  const { logout } = useAuth()
  const { dataUpdatedAt } = useMetrics(selectedWorkspaceId)

  const lastUpdated = dataUpdatedAt
    ? formatDistanceToNow(new Date(dataUpdatedAt), { addSuffix: true })
    : null

  return (
    <header className="flex items-center justify-between px-6 py-3.5 border-b border-[var(--border)] bg-[var(--surface)]">
      <div className="flex items-center gap-5">
        <WorkspaceSwitcher onAddWorkspace={onAddWorkspace} />
        <img src="/logo.svg" alt="SwarmOps" className="h-7 w-auto" />
        <SyncIndicator wsId={selectedWorkspaceId} />
      </div>
      <div className="flex items-center gap-2.5">
        {lastUpdated && (
          <span className="text-[10px] text-[var(--text-muted)] font-mono mr-1">
            {lastUpdated}
          </span>
        )}
        <button
          onClick={onOpenPlanner}
          className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-semibold bg-[var(--accent)] text-white rounded-md hover:brightness-110 transition-all shadow-[0_0_16px_rgba(139,92,246,0.2)]"
        >
          + Plan Issue
        </button>
        <button
          onClick={onAddWorkspace}
          className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[var(--text-dim)] border border-[var(--border)] rounded-md hover:border-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)] transition-all"
        >
          <Plus size={11} />
          Add Workspace
        </button>
        {selectedWorkspaceId && (
          <button
            onClick={onOpenSettings}
            className="p-1.5 rounded-md text-[var(--text-muted)] hover:text-[var(--text-dim)] hover:bg-[var(--surface-hover)] transition-colors"
            title="Settings"
          >
            <Settings size={14} />
          </button>
        )}
        <button
          onClick={logout}
          className="p-1.5 rounded-md text-[var(--text-muted)] hover:text-[var(--red)] hover:bg-[var(--surface-hover)] transition-colors"
          title="Sign out"
        >
          <LogOut size={14} />
        </button>
      </div>
    </header>
  )
}
