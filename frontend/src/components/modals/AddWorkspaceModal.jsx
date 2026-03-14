import { useState, useEffect } from 'react'
import { Modal } from '../ui/Modal'
import { Button } from '../ui/Button'
import { useCreateWorkspace } from '../../hooks/useWorkspaces'
import { useWorkspaceContext } from '../../context/WorkspaceContext'

export function AddWorkspaceModal({ open, onClose }) {
  const { mutate: create, isPending } = useCreateWorkspace()
  const { setSelectedWorkspaceId } = useWorkspaceContext()
  const [form, setForm] = useState({ repo_url: '', name: '', base_branch: 'main' })
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) {
      setForm({ repo_url: '', name: '', base_branch: 'main' })
      setError('')
    }
  }, [open])

  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }))

  const inputClass = 'w-full px-3 py-2 text-[11px] bg-[var(--bg)] border border-[var(--border)] rounded-md text-[var(--text)] font-mono focus:border-[var(--accent)] outline-none placeholder:text-[var(--text-muted)] transition-colors'

  const handleSubmit = (e) => {
    e.preventDefault()
    setError('')
    if (!form.repo_url.trim()) {
      setError('Repository URL is required')
      return
    }
    create(
      { repo_url: form.repo_url.trim(), name: form.name.trim() || undefined, base_branch: form.base_branch || 'main' },
      {
        onSuccess: (data) => {
          if (data?.workspace?.id) setSelectedWorkspaceId(data.workspace.id)
          onClose()
          setForm({ repo_url: '', name: '', base_branch: 'main' })
        },
        onError: (err) => setError(err.message),
      }
    )
  }

  return (
    <Modal open={open} onClose={onClose} title="Add Workspace">
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <div>
          <label className="block text-[9px] uppercase tracking-widest text-[var(--text-muted)] mb-1.5 font-medium">Repository URL *</label>
          <input value={form.repo_url} onChange={set('repo_url')} placeholder="https://github.com/owner/repo" className={inputClass} />
        </div>
        <div>
          <label className="block text-[9px] uppercase tracking-widest text-[var(--text-muted)] mb-1.5 font-medium">Display Name</label>
          <input value={form.name} onChange={set('name')} placeholder="My Project (optional)" className={inputClass} />
        </div>
        <div>
          <label className="block text-[9px] uppercase tracking-widest text-[var(--text-muted)] mb-1.5 font-medium">Base Branch</label>
          <input value={form.base_branch} onChange={set('base_branch')} placeholder="main" className={inputClass} />
        </div>

        {error && <p className="text-[10px] text-[var(--red)]">{error}</p>}

        {isPending && (
          <p className="text-[10px] text-[var(--text-muted)] font-mono">Cloning repository...</p>
        )}

        <div className="flex justify-end gap-2 mt-1">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" loading={isPending}>
            Add Workspace
          </Button>
        </div>
      </form>
    </Modal>
  )
}
