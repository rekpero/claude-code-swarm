import { Settings, Plus } from 'lucide-react'
import { WorkspaceSwitcher } from './WorkspaceSwitcher'
import { useMetrics } from '../../hooks/useMetrics'
import { useWorkspaceContext } from '../../context/WorkspaceContext'
import { formatDistanceToNow } from 'date-fns'

export function Header({ onAddWorkspace, onOpenSettings, onOpenPlanner }) {
  const { selectedWorkspaceId } = useWorkspaceContext()
  const { dataUpdatedAt } = useMetrics(selectedWorkspaceId)

  const lastUpdated = dataUpdatedAt
    ? formatDistanceToNow(new Date(dataUpdatedAt), { addSuffix: true })
    : null

  return (
    <header className="flex items-center justify-between px-6 py-3.5 border-b border-[var(--border)] bg-[var(--surface)]">
      <div className="flex items-center gap-5">
        <WorkspaceSwitcher onAddWorkspace={onAddWorkspace} />
        <div className="flex items-center gap-2.5">
          <div className="w-1.5 h-1.5 rounded-full bg-[var(--accent)] shadow-[0_0_6px_var(--accent)]" />
          <h1 className="text-[15px] font-semibold tracking-tight">Claude Code Swarm</h1>
        </div>
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
      </div>
    </header>
  )
}
