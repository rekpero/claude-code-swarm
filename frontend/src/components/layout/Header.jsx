import { Settings, Plus } from 'lucide-react'
import { WorkspaceSwitcher } from './WorkspaceSwitcher'
import { useMetrics } from '../../hooks/useMetrics'
import { useWorkspaceContext } from '../../context/WorkspaceContext'
import { formatDistanceToNow } from 'date-fns'

export function Header({ onAddWorkspace, onOpenSettings }) {
  const { selectedWorkspaceId } = useWorkspaceContext()
  const { dataUpdatedAt } = useMetrics(selectedWorkspaceId)

  const lastUpdated = dataUpdatedAt
    ? formatDistanceToNow(new Date(dataUpdatedAt), { addSuffix: true })
    : null

  return (
    <header className="flex items-center justify-between px-5 py-3 border-b border-[var(--border)] bg-[var(--surface)]">
      <div className="flex items-center gap-4">
        <WorkspaceSwitcher onAddWorkspace={onAddWorkspace} />
        <h1 className="text-base font-semibold tracking-tight">Claude Code Swarm</h1>
      </div>
      <div className="flex items-center gap-3">
        {lastUpdated && (
          <span className="text-[11px] text-[var(--text-dim)]">Updated {lastUpdated}</span>
        )}
        <button
          onClick={onAddWorkspace}
          className="flex items-center gap-1.5 px-2.5 py-1.5 text-[11px] text-[var(--accent)] border border-[rgba(108,92,231,0.4)] rounded-md hover:bg-[rgba(108,92,231,0.1)] transition-colors"
        >
          <Plus size={12} />
          Add Workspace
        </button>
        <button
          onClick={onOpenSettings}
          className="p-1.5 rounded-md text-[var(--text-dim)] hover:text-[var(--text)] hover:bg-white/5 transition-colors"
          title="Settings"
        >
          <Settings size={15} />
        </button>
      </div>
    </header>
  )
}
