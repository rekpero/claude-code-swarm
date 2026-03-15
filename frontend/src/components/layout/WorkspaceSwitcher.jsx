import { useState, useRef, useEffect } from 'react'
import { ChevronDown, Plus, Layers } from 'lucide-react'
import { useWorkspaces } from '../../hooks/useWorkspaces'
import { useWorkspaceContext } from '../../context/WorkspaceContext'

function StatusDot({ status }) {
  const colors = {
    active: 'bg-[var(--green)] shadow-[0_0_4px_var(--green)]',
    cloning: 'bg-[var(--yellow)] shadow-[0_0_4px_var(--yellow)]',
    error: 'bg-[var(--red)] shadow-[0_0_4px_var(--red)]',
  }
  return (
    <span className={`inline-block w-1.5 h-1.5 rounded-full flex-shrink-0 ${colors[status] || colors.error}`} />
  )
}

export function WorkspaceSwitcher({ onAddWorkspace }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const { data, isLoading } = useWorkspaces()
  const { selectedWorkspaceId, setSelectedWorkspaceId } = useWorkspaceContext()

  const workspaces = data?.workspaces || []
  const selected = workspaces.find((w) => w.id === selectedWorkspaceId)

  useEffect(() => {
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  useEffect(() => {
    if (!isLoading && selectedWorkspaceId && workspaces.length > 0 && !selected) {
      setSelectedWorkspaceId(null)
    }
  }, [isLoading, selectedWorkspaceId, workspaces, selected, setSelectedWorkspaceId])

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 px-3 py-1.5 bg-[var(--bg-raised)] border border-[var(--border)] rounded-lg text-[12px] cursor-pointer hover:border-[var(--text-muted)] transition-all"
      >
        {selected ? (
          <>
            <StatusDot status={selected.status} />
            <span className="max-w-[140px] truncate font-medium">{selected.name || selected.repo_url}</span>
          </>
        ) : (
          <>
            <Layers size={12} className="text-[var(--text-muted)]" />
            <span className="text-[var(--text-dim)]">All Workspaces</span>
          </>
        )}
        <ChevronDown size={10} className="text-[var(--text-muted)]" />
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1.5 bg-[var(--surface)] border border-[var(--border)] rounded-lg shadow-[0_12px_40px_rgba(0,0,0,0.6)] min-w-[280px] z-50 overflow-hidden animate-fade-in">
          <div
            className={`flex items-center gap-2 px-3 py-2.5 cursor-pointer text-[11px] hover:bg-[var(--surface-hover)] transition-colors ${!selectedWorkspaceId ? 'bg-[var(--accent-dim)]' : ''}`}
            onClick={() => { setSelectedWorkspaceId(null); setOpen(false) }}
          >
            <Layers size={11} className="text-[var(--text-muted)]" />
            <span className="flex-1 font-medium">All Workspaces</span>
          </div>

          {workspaces.length > 0 && (
            <div className="border-t border-[var(--border-subtle)] mx-2" />
          )}

          {workspaces.map((ws) => (
            <div
              key={ws.id}
              className={`flex items-center gap-2 px-3 py-2.5 cursor-pointer text-[11px] hover:bg-[var(--surface-hover)] transition-colors ${selectedWorkspaceId === ws.id ? 'bg-[var(--accent-dim)]' : ''}`}
              onClick={() => { setSelectedWorkspaceId(ws.id); setOpen(false) }}
            >
              <StatusDot status={ws.status} />
              <span className="flex-1 truncate font-medium">{ws.name || ws.repo_url}</span>
              <span className="text-[var(--text-muted)] text-[9px] font-mono truncate max-w-[100px]">
                {ws.repo_url?.replace(/^https?:\/\/github\.com\//, '')}
              </span>
            </div>
          ))}

          <div className="border-t border-[var(--border-subtle)] mx-2" />
          <div
            className="flex items-center gap-2 px-3 py-2.5 cursor-pointer text-[11px] text-[var(--accent)] hover:bg-[var(--accent-dim)] transition-colors font-medium"
            onClick={() => { onAddWorkspace?.(); setOpen(false) }}
          >
            <Plus size={11} />
            <span>Add Workspace</span>
          </div>
        </div>
      )}
    </div>
  )
}
