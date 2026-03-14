import { useState, useRef, useEffect } from 'react'
import { ChevronDown, Plus, Layers } from 'lucide-react'
import { useWorkspaces } from '../../hooks/useWorkspaces'
import { useWorkspaceContext } from '../../context/WorkspaceContext'

function StatusDot({ status }) {
  const color = status === 'active' ? 'var(--green)' : status === 'cloning' ? 'var(--yellow)' : 'var(--red)'
  return (
    <span
      className="inline-block w-2 h-2 rounded-full flex-shrink-0"
      style={{ background: color }}
    />
  )
}

export function WorkspaceSwitcher({ onAddWorkspace }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const { data } = useWorkspaces()
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

  // If selected workspace was deleted, fall back to null
  useEffect(() => {
    if (selectedWorkspaceId && workspaces.length > 0 && !selected) {
      setSelectedWorkspaceId(null)
    }
  }, [selectedWorkspaceId, workspaces, selected, setSelectedWorkspaceId])

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 px-3 py-1.5 bg-[var(--surface)] border border-[var(--border)] rounded-md text-sm cursor-pointer hover:border-[var(--accent)] transition-colors"
      >
        {selected ? (
          <>
            <StatusDot status={selected.status} />
            <span className="max-w-[160px] truncate">{selected.name || selected.repo_url}</span>
          </>
        ) : (
          <>
            <Layers size={13} className="text-[var(--text-dim)]" />
            <span className="text-[var(--text-dim)]">All Workspaces</span>
          </>
        )}
        <ChevronDown size={12} className="text-[var(--text-dim)]" />
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1 bg-[var(--surface)] border border-[var(--border)] rounded-lg shadow-2xl min-w-[280px] z-50 overflow-hidden">
          <div
            className={`flex items-center gap-2 px-3 py-2 cursor-pointer text-xs hover:bg-white/5 transition-colors ${!selectedWorkspaceId ? 'bg-[rgba(108,92,231,0.1)]' : ''}`}
            onClick={() => { setSelectedWorkspaceId(null); setOpen(false) }}
          >
            <Layers size={12} className="text-[var(--text-dim)]" />
            <span className="flex-1">All Workspaces</span>
          </div>

          {workspaces.length > 0 && (
            <div className="border-t border-[var(--border)] my-1" />
          )}

          {workspaces.map((ws) => (
            <div
              key={ws.id}
              className={`flex items-center gap-2 px-3 py-2 cursor-pointer text-xs hover:bg-white/5 transition-colors ${selectedWorkspaceId === ws.id ? 'bg-[rgba(108,92,231,0.1)]' : ''}`}
              onClick={() => { setSelectedWorkspaceId(ws.id); setOpen(false) }}
            >
              <StatusDot status={ws.status} />
              <span className="flex-1 truncate">{ws.name || ws.repo_url}</span>
              <span className="text-[var(--text-dim)] text-[10px] truncate max-w-[100px]">
                {ws.repo_url?.replace(/^https?:\/\/github\.com\//, '')}
              </span>
            </div>
          ))}

          <div className="border-t border-[var(--border)] my-1" />
          <div
            className="flex items-center gap-2 px-3 py-2 cursor-pointer text-xs text-[var(--accent)] hover:bg-[rgba(108,92,231,0.1)] transition-colors"
            onClick={() => { onAddWorkspace?.(); setOpen(false) }}
          >
            <Plus size={12} />
            <span>Add Workspace</span>
          </div>
        </div>
      )}
    </div>
  )
}
