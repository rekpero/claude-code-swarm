import { useState, useEffect } from 'react'
import { Modal } from '../ui/Modal'
import { Button } from '../ui/Button'
import { EnvEditor } from './EnvEditor'
import { useUpdateWorkspace, useDeleteWorkspace, useWorkspaces } from '../../hooks/useWorkspaces'
import { useWorkspaceContext } from '../../context/WorkspaceContext'

const TABS = ['General', 'Env Files', 'Structure']

export function WorkspaceSettingsModal({ open, onClose }) {
  const [activeTab, setActiveTab] = useState('General')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [updateError, setUpdateError] = useState(null)
  const { selectedWorkspaceId, setSelectedWorkspaceId } = useWorkspaceContext()
  const { data } = useWorkspaces()
  const { mutate: update, isPending: isUpdating } = useUpdateWorkspace()
  const { mutate: del, isPending: isDeleting } = useDeleteWorkspace()

  const workspace = data?.workspaces?.find((w) => w.id === selectedWorkspaceId)
  const [form, setForm] = useState({ name: '', repo_url: '', base_branch: '' })

  useEffect(() => {
    if (workspace) {
      setForm({
        name: workspace.name || '',
        repo_url: workspace.repo_url || '',
        base_branch: workspace.base_branch || '',
      })
      setUpdateError(null)
    } else {
      setForm({ name: '', repo_url: '', base_branch: '' })
    }
  }, [workspace?.id, workspace?.name, workspace?.repo_url, workspace?.base_branch])

  useEffect(() => {
    if (!open) {
      setConfirmDelete(false)
    } else {
      setUpdateError(null)
    }
  }, [open])

  const handleUpdate = (e) => {
    e.preventDefault()
    if (!selectedWorkspaceId) return
    setUpdateError(null)
    update(
      { id: selectedWorkspaceId, data: form },
      {
        onSuccess: onClose,
        onError: (err) => setUpdateError(err?.message || 'Failed to update workspace.'),
      }
    )
  }

  const handleDelete = () => {
    if (!selectedWorkspaceId) return
    del(selectedWorkspaceId, {
      onSuccess: () => {
        setSelectedWorkspaceId(null)
        onClose()
      },
      onError: (err) => setUpdateError(err?.message || 'Failed to delete workspace.'),
    })
  }

  if (!workspace) {
    return (
      <Modal open={open} onClose={onClose} title="Workspace Settings">
        <p className="text-sm text-[var(--text-dim)]">No workspace selected. Select a workspace first.</p>
        <div className="flex justify-end mt-4">
          <Button variant="ghost" onClick={onClose}>Close</Button>
        </div>
      </Modal>
    )
  }

  return (
    <Modal open={open} onClose={onClose} title={`Settings — ${workspace.name || workspace.repo_url}`} maxWidth="560px">
      {/* Tabs */}
      <div className="flex gap-1 border-b border-[var(--border)] mb-4">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-3 py-1.5 text-xs border-b-2 transition-colors ${
              activeTab === tab
                ? 'border-[var(--accent)] text-[var(--text)]'
                : 'border-transparent text-[var(--text-dim)] hover:text-[var(--text)]'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {activeTab === 'General' && (
        <form onSubmit={handleUpdate} className="flex flex-col gap-3">
          <div>
            <label className="block text-[10px] uppercase tracking-wide text-[var(--text-dim)] mb-1">Display Name</label>
            <input
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              className="w-full px-2.5 py-2 text-[12px] bg-[var(--bg)] border border-[var(--border)] rounded-md text-[var(--text)] font-mono focus:border-[var(--accent)] outline-none"
            />
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-wide text-[var(--text-dim)] mb-1">Repository URL</label>
            <input
              value={form.repo_url}
              onChange={(e) => setForm((f) => ({ ...f, repo_url: e.target.value }))}
              className="w-full px-2.5 py-2 text-[12px] bg-[var(--bg)] border border-[var(--border)] rounded-md text-[var(--text)] font-mono focus:border-[var(--accent)] outline-none"
            />
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-wide text-[var(--text-dim)] mb-1">Base Branch</label>
            <input
              value={form.base_branch}
              onChange={(e) => setForm((f) => ({ ...f, base_branch: e.target.value }))}
              className="w-full px-2.5 py-2 text-[12px] bg-[var(--bg)] border border-[var(--border)] rounded-md text-[var(--text)] font-mono focus:border-[var(--accent)] outline-none"
            />
          </div>
          {updateError && (
            <p className="text-[11px] text-[var(--red)]">{updateError}</p>
          )}
          <div className="flex justify-between items-center mt-2">
            <div>
              {confirmDelete ? (
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-[var(--red)]">Are you sure?</span>
                  <Button size="sm" variant="danger" loading={isDeleting} onClick={handleDelete}>
                    Yes, Delete
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(false)}>
                    Cancel
                  </Button>
                </div>
              ) : (
                <Button size="sm" variant="danger" onClick={() => setConfirmDelete(true)}>
                  Delete Workspace
                </Button>
              )}
            </div>
            <div className="flex gap-2">
              <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
              <Button type="submit" variant="primary" loading={isUpdating}>Save</Button>
            </div>
          </div>
        </form>
      )}

      {activeTab === 'Env Files' && (
        <EnvEditor workspaceId={selectedWorkspaceId} />
      )}

      {activeTab === 'Structure' && (
        <div className="text-[12px] text-[var(--text-dim)]">
          <p className="mb-2">Workspace: <span className="text-[var(--text)]">{workspace.local_path || '—'}</span></p>
          <p>Status: <span className="text-[var(--text)]">{workspace.status || '—'}</span></p>
        </div>
      )}
    </Modal>
  )
}
